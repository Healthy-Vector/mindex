export function buildContractPayload({ tmpId, mode, contractId, ipId, contractInfo, rights, fileMeta = {} }) {
  const primaryRights = (rights ?? []).slice(0, 1);
  return {
    tmpId,
    mode,
    ...(contractId ? { contractId: Number(contractId) } : {}),
    ...(ipId ? { ipId: Number(ipId) } : {}),
    contractInfo: { ...contractInfo },
    fileMeta: { ...fileMeta },
    rights: primaryRights.map((right) => ({
      ...right,
      contentAssetId: right.contentAssetId == null ? null : Number(right.contentAssetId),
      territories: [...(right.territories ?? [])],
      period: { ...right.period },
      evidence: structuredClone(right.evidence ?? {}),
    })),
  };
}

export function buildVerifyPayload(payload) {
  return buildStagingPayload(payload);
}

export function buildConfirmPayload(payload) {
  return buildStagingPayload(payload);
}

function buildStagingPayload(payload) {
  if (!payload.tmpId) return buildDirectContractPayload(payload);
  return {
    tmpId: payload.tmpId,
    ...(payload.contractId ? { contractId: Number(payload.contractId) } : {}),
    ...(payload.ipId ? { ipId: Number(payload.ipId) } : {}),
    documentKind: payload.mode === "final" ? "final" : "draft",
    patch: buildStagingPatch(payload),
  };
}

function buildStagingPatch(payload) {
  const info = payload.contractInfo ?? {};
  const primaryRights = (payload.rights ?? []).slice(0, 1);
  return {
    contractInfo: { ...info },
    rights: primaryRights.map(toApiRight),
  };
}

function buildDirectContractPayload(payload) {
  const info = payload.contractInfo ?? {};
  const file = payload.fileMeta ?? {};
  const primaryRights = (payload.rights ?? []).slice(0, 1);
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
    rights: primaryRights.map(toApiRight),
  };
}

function toApiRight(right) {
  return {
    ...(right.contentAssetId ? { contentAssetId: Number(right.contentAssetId) } : {}),
    legalRight: right.legalRight,
    exploitationMode: right.exploitationMode,
    territories: [...(right.territories ?? [])],
    period: { ...right.period },
    exclusivity: right.exclusivity,
    evidence: normalizeEvidenceKeys(right.evidence),
    ...(right.conditionsRaw ? { conditionsRaw: structuredClone(right.conditionsRaw) } : {}),
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
  if (!payload.rights.length) violations.push("권리를 한 건 이상 추가해야 합니다.");
  const selectedAssetIds = new Set(payload.rights.map((right) => right.contentAssetId).filter(Boolean).map(Number));
  if (payload.rights.length && selectedAssetIds.size === 0) violations.push("권리 대상을 선택해야 합니다.");
  if (selectedAssetIds.size > 1) violations.push("권리 대상은 하나만 선택할 수 있습니다.");
  for (const contentAssetId of selectedAssetIds) {
    if (contentAssetIds?.size && !contentAssetIds.has(contentAssetId)) {
      violations.push("선택한 권리 대상이 현재 IP에 속하지 않습니다.");
    }
  }
  payload.rights.forEach((right, index) => {
    const prefix = `권리 #${index + 1}`;
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
