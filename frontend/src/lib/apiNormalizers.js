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
    contractInfo: result?.contractInfo ?? {},
    rights: result?.rights ?? [],
    ipCandidates: result?.ipCandidates ?? [],
    rawText: result?.rawText ?? "",
    confidence: result?.confidence ?? null,
  };
}

export function normalizeRights(rights = []) {
  return rights.map((right) => ({
    ...right,
    id: right.id ?? right.rightsGrantId,
    contentAssetId: right.contentAssetId ?? right.contentAsset?.contentAssetId ?? right.contentAsset?.id ?? null,
    scopeType: right.scopeType ?? right.contentAsset?.scopeType ?? null,
    legalRight: right.legalRight ?? right.rightsType ?? null,
  }));
}

export function normalizeContract(contract) {
  if (!contract) return contract;
  return {
    ...contract,
    id: contract.id ?? contract.contractId,
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
