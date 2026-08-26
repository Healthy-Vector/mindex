import test from "node:test";
import assert from "node:assert/strict";
import { normalizeContract, normalizeContractListItem, normalizeJob, normalizeVerifyResult } from "./apiNormalizers.js";

test("extract result를 화면 상태로 분리한다", () => {
  const normalized = normalizeJob({ tmpid: "tmp-1", status: "DONE", result: { contractInfo: { title: "계약" }, rights: [{ contentAssetId: 1 }] } });
  assert.equal(normalized.stage, "extract");
  assert.equal(normalized.contractInfo.title, "계약");
  assert.equal(normalized.rights.length, 1);
});

test("실 API conflictReport와 PostgreSQL 기간을 화면 구조로 변환한다", () => {
  const normalized = normalizeVerifyResult({ hasConflict: true, conflictReport: { conflicts: [{ existingContractId: 7, existingGrantId: 8, incoming: { period: "[2026-01-01,2027-01-01)", territory: "KR" }, overlapPeriod: "[2026-06-01,2026-07-01)" }] } });
  assert.equal(normalized.conflicts[0].existing.title, "기존 계약 #7");
  assert.deepEqual(normalized.conflicts[0].incoming.period, { start: "2026-01-01", end: "2026-12-31" });
  assert.deepEqual(normalized.conflicts[0].overlap, { start: "2026-06-01", end: "2026-06-30" });
});

test("계약 상세의 중첩 contentAsset과 기존 rightsType을 정규화한다", () => {
  const normalized = normalizeContract({ contractId: 3, ips: [{ ipId: 23, title: "test1" }], rights: [{ rightsGrantId: 8, rightsType: "TRANSMISSION", periodStart: "2026-01-01", periodEnd: "2026-12-31", contentAsset: { contentAssetId: 11, scopeType: "SEASON", title: "시즌 1", ipId: 23, ipTitle: "test1" } }] });
  assert.equal(normalized.id, 3);
  assert.equal(normalized.ipId, 23);
  assert.equal(normalized.rightsGrants[0].id, 8);
  assert.equal(normalized.rightsGrants[0].contentAssetId, 11);
  assert.equal(normalized.rightsGrants[0].contentAssetTitle, "시즌 1");
  assert.equal(normalized.rightsGrants[0].scopeType, "SEASON");
  assert.equal(normalized.rightsGrants[0].legalRight, "TRANSMISSION");
  assert.deepEqual(normalized.rightsGrants[0].period, { start: "2026-01-01", end: "2026-12-31" });
});

test("처리 중 계약 목록 항목은 고정 임시 title을 사용한다", () => {
  const normalized = normalizeContractListItem({ kind: "processing", tmpid: "tmp-1", filename: "CTR-KO-9004.pdf" });
  assert.equal(normalized.title, "추출 작업 진행 중");
});

test("업로드 추출 결과는 대표 권리 1건만 화면 상태로 사용한다", () => {
  const normalized = normalizeJob({
    tmpid: "tmp-1",
    status: "DONE",
    result: { rights: [{ legalRight: "A" }, { legalRight: "B" }] },
  });
  assert.equal(normalized.rights.length, 1);
  assert.equal(normalized.rights[0].legalRight, "A");
});
