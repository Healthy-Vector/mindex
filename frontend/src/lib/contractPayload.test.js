import test from "node:test";
import assert from "node:assert/strict";
import { buildConfirmPayload, buildContractPayload, buildVerifyPayload, contractPayloadViolations } from "./contractPayload.js";

const quote = [{ quote: "원문" }];
const evidence = { legalRight: quote, exploitationMode: quote, territory: quote, period: quote, exclusivity: quote };

test("HITL 권리와 계약 정보를 저장 payload에 보존한다", () => {
  const payload = buildContractPayload({ tmpId: "tmp-1", mode: "new", ipId: "3", contractInfo: { grantor: "A", grantee: "B" }, fileMeta: { fileName: "a.pdf", filePath: "tmp/a.pdf", fileHash: "abc" }, rights: [{ contentAssetId: "10", territories: ["KR"], legalRight: "TRANSMISSION", exploitationMode: "SVOD", exclusivity: "exclusive", period: { start: "2026-01-01", end: "2026-12-31" }, evidence }] });
  assert.equal(payload.ipId, 3);
  assert.equal(payload.rights[0].contentAssetId, 10);
  assert.equal(payload.rights[0].legalRight, "TRANSMISSION");
});

test("다른 IP의 Content Asset과 evidence 누락을 차단한다", () => {
  const payload = buildContractPayload({ tmpId: "tmp-1", mode: "new", ipId: 3, contractInfo: { grantor: "A", grantee: "B" }, fileMeta: { fileName: "a.pdf", filePath: "tmp/a.pdf", fileHash: "abc" }, rights: [{ contentAssetId: 99, territories: ["KR"], legalRight: "TRANSMISSION", exploitationMode: "SVOD", exclusivity: "exclusive", period: { start: "2026-01-01", end: "2026-12-31" }, evidence: {} }] });
  const violations = contractPayloadViolations(payload, { contentAssetIds: new Set([10]) });
  assert.ok(violations.some((message) => message.includes("현재 IP")));
  assert.ok(violations.some((message) => message.includes("판정 근거")));
});

test("verify payload를 실 API 계약으로 변환한다", () => {
  const payload = { tmpId: "tmp-1", mode: "final", ipId: 3, contractInfo: { grantor: "A", grantee: "B" }, fileMeta: { fileName: "a.pdf", filePath: "tmp/a.pdf", fileHash: "abc" }, rights: [{ legalRight: "TRANSMISSION", exploitationMode: "SVOD", territories: ["KR"], period: { start: "2026-01-01", end: "2026-12-31" }, exclusivity: "exclusive", evidence }] };
  const verifyPayload = buildVerifyPayload(payload);
  assert.equal(verifyPayload.contractInfo, undefined);
  assert.equal(verifyPayload.grantor, "A");
  assert.equal(verifyPayload.documentKind, "final");
  assert.deepEqual(verifyPayload.rights[0].evidence.legal_right, quote);
  assert.equal(verifyPayload.rights[0].legalRight, "TRANSMISSION");
  assert.ok(payload.contractInfo);
  assert.equal(buildConfirmPayload(payload).sourceTmpid, "tmp-1");
});
