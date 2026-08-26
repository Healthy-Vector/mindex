import test from "node:test";
import assert from "node:assert/strict";
import { computeContractStatus } from "./contractStatus.js";

test("BEFORE_TERM을 계약 전과 유효기간 전으로 구분한다", () => {
  const today = new Date("2026-01-01T00:00:00Z");
  assert.equal(computeContractStatus({ signedDate: "2026-02-01", periodStart: "2026-03-01", periodEnd: "2027-01-01" }, today).label, "계약 전");
  assert.equal(computeContractStatus({ signedDate: "2025-12-01", periodStart: "2026-03-01", periodEnd: "2027-01-01" }, today).label, "유효기간 전");
});
