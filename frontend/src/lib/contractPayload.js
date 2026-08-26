export function buildContractPayload({ tmpId, mode, contractId, ipId, contractInfo, rights }) {
  return {
    tmpId,
    mode,
    ...(contractId ? { contractId: Number(contractId) } : {}),
    ...(ipId ? { ipId: Number(ipId) } : {}),
    contractInfo: { ...contractInfo },
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
  const verifyPayload = { ...payload };
  delete verifyPayload.contractInfo;
  return verifyPayload;
}

export function contractPayloadViolations(payload, { contentAssetIds } = {}) {
  const violations = [];
  if (!payload.tmpId) violations.push("추출 작업 ID가 없습니다.");
  if (!payload.ipId) violations.push("IP를 선택해야 합니다.");
  if (payload.ipId && contentAssetIds && contentAssetIds.size === 0) violations.push("선택한 IP의 Content Asset 목록을 불러오지 못했습니다.");
  if (["revision", "final"].includes(payload.mode) && !payload.contractId) violations.push("기존 계약 ID가 없습니다.");
  if (!payload.contractInfo?.title?.trim()) violations.push("계약명을 입력해야 합니다.");
  if (!payload.rights.length) violations.push("권리를 한 건 이상 추가해야 합니다.");
  payload.rights.forEach((right, index) => {
    const prefix = `권리 #${index + 1}`;
    if (!right.contentAssetId) violations.push(`${prefix}: Content Asset을 선택해야 합니다.`);
    else if (contentAssetIds?.size && !contentAssetIds.has(Number(right.contentAssetId))) {
      violations.push(`${prefix}: 선택한 Content Asset이 현재 IP에 속하지 않습니다.`);
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
