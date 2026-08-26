export function buildContractPayload({ tmpId, mode, contractId, ipId, contractInfo, rights, fileMeta = {} }) {
  return {
    tmpId,
    mode,
    ...(contractId ? { contractId: Number(contractId) } : {}),
    ...(ipId ? { ipId: Number(ipId) } : {}),
    contractInfo: { ...contractInfo },
    fileMeta: { ...fileMeta },
    rights: rights.map((right) => ({
      ...right,
      contentAssetId: right.contentAssetId == null ? null : Number(right.contentAssetId),
      territories: [...(right.territories ?? [])],
      period: { ...right.period },
      evidence: structuredClone(right.evidence ?? {}),
    })),
  };
}

export function buildVerifyPayload(payload) {
  return buildApiContractPayload(payload);
}

export function buildConfirmPayload(payload) {
  return {
    ...buildApiContractPayload(payload),
    chunks: payload.fileMeta?.chunks ?? [],
    ...(payload.tmpId ? { sourceTmpid: payload.tmpId } : {}),
  };
}

function buildApiContractPayload(payload) {
  const info = payload.contractInfo ?? {};
  const file = payload.fileMeta ?? {};
  return {
    ...(payload.contractId ? { contractId: Number(payload.contractId) } : {}),
    grantor: info.grantor?.trim() ?? "",
    grantee: info.grantee?.trim() ?? "",
    ...(payload.ipId ? { ipId: Number(payload.ipId) } : {}),
    fileName: file.fileName ?? "",
    filePath: file.filePath ?? "",
    fileHash: file.fileHash ?? "",
    mimeType: file.mimeType ?? "application/pdf",
    rawText: file.rawText ?? "",
    documentKind: payload.mode === "final" ? "final" : "draft",
    rights: (payload.rights ?? []).map((right) => ({
      ...(right.contentAssetId ? { contentAssetId: Number(right.contentAssetId) } : {}),
      legalRight: right.legalRight,
      exploitationMode: right.exploitationMode,
      territories: [...(right.territories ?? [])],
      period: { ...right.period },
      exclusivity: right.exclusivity,
      evidence: normalizeEvidenceKeys(right.evidence),
      ...(right.conditionsRaw ? { conditionsRaw: structuredClone(right.conditionsRaw) } : {}),
    })),
  };
}

function normalizeEvidenceKeys(evidence = {}) {
  return {
    legal_right: evidence.legal_right ?? evidence.legalRight,
    exploitation_mode: evidence.exploitation_mode ?? evidence.exploitationMode,
    territory: evidence.territory,
    period: evidence.period,
    exclusivity: evidence.exclusivity,
  };
}

export function contractPayloadViolations(payload, { contentAssetIds } = {}) {
  const violations = [];
  if (!payload.tmpId) violations.push("추출 작업 ID가 없습니다.");
  if (!payload.ipId) violations.push("IP를 선택해야 합니다.");
  if (payload.ipId && contentAssetIds && contentAssetIds.size === 0) violations.push("선택한 IP의 권리 대상 목록을 불러오지 못했습니다.");
  if (["revision", "final"].includes(payload.mode) && !payload.contractId) violations.push("기존 계약 ID가 없습니다.");
  if (!payload.contractInfo?.grantor?.trim()) violations.push("권리 허락자를 입력해야 합니다.");
  if (!payload.contractInfo?.grantee?.trim()) violations.push("권리 이용자를 입력해야 합니다.");
  if (!payload.fileMeta?.fileName) violations.push("원본 파일명이 없습니다.");
  if (!payload.fileMeta?.filePath) violations.push("원본 파일 경로가 없습니다.");
  if (!payload.fileMeta?.fileHash) violations.push("원본 파일 해시가 없습니다.");
  if (!payload.rights.length) violations.push("권리를 한 건 이상 추가해야 합니다.");
  payload.rights.forEach((right, index) => {
    const prefix = `권리 #${index + 1}`;
    if (!right.contentAssetId) violations.push(`${prefix}: 권리 대상을 선택해야 합니다.`);
    else if (contentAssetIds?.size && !contentAssetIds.has(Number(right.contentAssetId))) {
      violations.push(`${prefix}: 선택한 권리 대상이 현재 IP에 속하지 않습니다.`);
    }
    if (!right.territories?.length) violations.push(`${prefix}: 지역을 한 곳 이상 선택해야 합니다.`);
    if (!right.legalRight || !right.exploitationMode || !right.exclusivity) violations.push(`${prefix}: 권리 판정값을 모두 선택해야 합니다.`);
    if (!right.period?.start || !right.period?.end) violations.push(`${prefix}: 시작일과 종료일을 입력해야 합니다.`);
    else if (right.period.start > right.period.end) violations.push(`${prefix}: 종료일이 시작일보다 빠릅니다.`);
    for (const field of missingEvidenceFields(right.evidence)) {
      violations.push(`${prefix}: ${EVIDENCE_FIELDS[field]} 판정 근거 원문을 입력해야 합니다.`);
    }
  });
  return violations;
}

import { EVIDENCE_FIELDS, missingEvidenceFields } from "./evidence.js";
