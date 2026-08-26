const REAL_JOB_STAGE = { QUEUED: "queued", DONE: "extract", FAILED: "failed" };

export function normalizeJob(json) {
  const stage = json.status === "RUNNING" ? json.stage?.toLowerCase() : (REAL_JOB_STAGE[json.status] ?? "failed");
  const result = json.result ?? null;
  return {
    id: json.tmpid,
    fileName: json.filename,
    stage,
    queuePosition: json.queuePosition ?? null,
    reason: json.reason,
    result,
    contractInfo: {
      ...(result?.contractInfo ?? {}),
      grantor: result?.contractInfo?.grantor ?? result?.grantor ?? "",
      grantee: result?.contractInfo?.grantee ?? result?.contractInfo?.counterparty ?? result?.grantee ?? "",
    },
    rights: result?.rights ?? [],
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
  if (item.kind === "processing") return item;
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
