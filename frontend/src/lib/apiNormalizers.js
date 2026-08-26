const REAL_JOB_STAGE = { QUEUED: "queued", DONE: "extract", FAILED: "failed" };

// 계약체결일 등 OCR/LLM이 뽑은 날짜가 "2026년 7월 19일"처럼 원문 자연어 그대로 올 수
// 있다 — <input type="date">는 ISO(YYYY-MM-DD)가 아니면 빈 값으로 보여서 사람이
// "값이 없나?" 하고 지나치기 쉽다. 흔한 표기만 최선을 다해 ISO로 바꿔 미리 채워두고,
// 못 알아보는 형식은 원본 그대로 둔다(파싱 실패를 숨기지 않고 사람이 직접 채우게 한다).
function normalizeDateString(value) {
  if (!value || typeof value !== "string") return value;
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const korean = value.match(/(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일/);
  if (korean) {
    const [, y, m, d] = korean;
    return `${y}-${m.padStart(2, "0")}-${d.padStart(2, "0")}`;
  }
  const delimited = value.match(/^(\d{4})[./](\d{1,2})[./](\d{1,2})$/);
  if (delimited) {
    const [, y, m, d] = delimited;
    return `${y}-${m.padStart(2, "0")}-${d.padStart(2, "0")}`;
  }
  return value;
}

export function normalizeJob(json) {
  const stage = json.status === "RUNNING" ? json.stage?.toLowerCase() : (REAL_JOB_STAGE[json.status] ?? "failed");
  const result = json.result ?? null;
  return {
    id: json.tmpid,
    fileName: json.filename,
    stage,
    queuePosition: json.queuePosition ?? null,
    reason: json.reason,
    // D-37 — 업로드 시점 맥락(서버가 tmpId로 복원할 수 있도록 저장해 둔 값). 화면 상태
    // 없이 재진입(목록의 "처리 중" 클릭 등)할 때 URL 쿼리 대신 이 값으로 복원한다.
    mode: json.mode ?? null,
    contractId: json.contractId ?? null,
    ipId: json.ipId ?? null,
    result,
    contractInfo: {
      ...(result?.contractInfo ?? {}),
      grantor: result?.contractInfo?.grantor ?? result?.grantor ?? "",
      grantee: result?.contractInfo?.grantee ?? result?.contractInfo?.counterparty ?? result?.grantee ?? "",
      signedDate: normalizeDateString(result?.contractInfo?.signedDate),
    },
    rights: (result?.rights ?? []).slice(0, 1),
    ipCandidates: result?.ipCandidates ?? [],
    rawText: result?.rawText ?? "",
    confidence: result?.confidence ?? null,
    fileMeta: {
      fileName: result?.fileName ?? json.filename ?? "",
      filePath: result?.filePath ?? "",
      fileHash: result?.fileHash ?? "",
      mimeType: result?.mimeType ?? "application/pdf",
      rawText: result?.rawText ?? "",
      chunks: result?.chunks ?? [],
    },
  };
}

export function normalizeVerifyResult(json, payload = {}) {
  const rawConflicts = json?.conflictReport?.conflicts ?? json?.conflicts ?? [];
  return {
    ...json,
    conflicts: rawConflicts.map(normalizeConflict),
    candidate: json?.candidate ?? { title: payload.fileMeta?.fileName, ip: payload.ipId ? `IP #${payload.ipId}` : null },
  };
}

function normalizeConflict(conflict) {
  if (conflict.existing && conflict.incoming) return conflict;
  const incoming = { ...(conflict.incoming ?? {}), period: parsePgRange(conflict.incoming?.period) };
  return {
    ...conflict,
    severity: conflict.severity ?? "CONFLICT",
    existing: {
      contractId: conflict.existingContractId,
      rightsGrantId: conflict.existingGrantId,
      title: conflict.existingContractId ? `기존 계약 #${conflict.existingContractId}` : "기존 계약",
      period: null,
    },
    incoming,
    overlap: parsePgRange(conflict.overlapPeriod),
  };
}

function parsePgRange(value) {
  if (!value || typeof value !== "string") return value ?? null;
  const comma = value.indexOf(",");
  if (comma < 0) return null;
  const start = value.slice(1, comma);
  const rawEnd = value.slice(comma + 1, -1);
  const endMark = value.at(-1);
  let end = rawEnd;
  if (end && endMark === ")") {
    const date = new Date(`${end}T00:00:00Z`);
    if (!Number.isNaN(date.getTime())) {
      date.setUTCDate(date.getUTCDate() - 1);
      end = date.toISOString().slice(0, 10);
    }
  }
  return { start, end };
}

export function normalizeRights(rights = []) {
  return rights.map((right) => ({
    ...right,
    id: right.id ?? right.rightsGrantId,
    contentAssetId: right.contentAssetId ?? right.contentAsset?.contentAssetId ?? right.contentAsset?.id ?? null,
    contentAssetTitle: right.contentAssetTitle ?? right.contentAsset?.title ?? null,
    ipId: right.ipId ?? right.contentAsset?.ipId ?? null,
    ipTitle: right.ipTitle ?? right.contentAsset?.ipTitle ?? null,
    scopeType: right.scopeType ?? right.contentAsset?.scopeType ?? null,
    legalRight: right.legalRight ?? right.rightsType ?? null,
    period: right.period ?? (right.periodStart || right.periodEnd
      ? { start: right.periodStart ?? null, end: right.periodEnd ?? null }
      : null),
  }));
}

export function normalizeContract(contract) {
  if (!contract) return contract;
  const primaryIp = contract.ips?.[0];
  return {
    ...contract,
    id: contract.id ?? contract.contractId,
    ipId: contract.ipId ?? primaryIp?.ipId ?? primaryIp?.id ?? null,
    rightsGrants: normalizeRights(contract.rightsGrants ?? contract.rights),
  };
}

export function normalizeContractListItem(item) {
  if (item.kind === "processing") {
    return {
      ...item,
      title: item.title ?? "추출 작업 진행 중",
    };
  }
  return {
    ...item,
    kind: item.kind ?? "contract",
    contractId: item.contractId ?? item.id,
    mainLegalRights: item.mainLegalRights ?? [],
    mainExploitationModes: item.mainExploitationModes ?? [],
  };
}

export function normalizeIp(ip) {
  if (!ip) return ip;
  return {
    ...ip,
    id: ip.id ?? ip.ipId,
    activity: ip.activity ?? (ip.isActive === false ? "deactive" : "active"),
  };
}
