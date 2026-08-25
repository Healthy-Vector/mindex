import test from "node:test";
import assert from "node:assert/strict";
import { normalizeContract, normalizeJob } from "./apiNormalizers.js";

test("extract result를 화면 상태로 분리한다", () => {
  const normalized = normalizeJob({ tmpid: "tmp-1", status: "DONE", result: { contractInfo: { title: "계약" }, rights: [{ contentAssetId: 1 }] } });
  assert.equal(normalized.stage, "extract");
  assert.equal(normalized.contractInfo.title, "계약");
  assert.equal(normalized.rights.length, 1);
});

test("계약 상세의 중첩 contentAsset과 기존 rightsType을 정규화한다", () => {
  const normalized = normalizeContract({ contractId: 3, rights: [{ rightsGrantId: 8, rightsType: "TRANSMISSION", contentAsset: { contentAssetId: 11, scopeType: "SEASON" } }] });
  assert.equal(normalized.id, 3);
  assert.deepEqual(normalized.rightsGrants[0], {
    rightsGrantId: 8,
    rightsType: "TRANSMISSION",
    contentAsset: { contentAssetId: 11, scopeType: "SEASON" },
    id: 8,
    contentAssetId: 11,
    scopeType: "SEASON",
    legalRight: "TRANSMISSION",
  });
});
