import test from "node:test";
import assert from "node:assert/strict";
import { groupEvidenceByQuote, missingEvidenceFields, updateFirstEvidenceEntry } from "./evidence.js";

test("evidence 단일 객체와 배열을 같은 방식으로 묶는다", () => {
  const grouped = groupEvidenceByQuote({
    legalRight: { clause: "제3조", quote: "동일 원문" },
    exploitationMode: [{ clause: "제3조", quote: "동일 원문" }],
  });
  assert.equal(grouped.length, 1);
  assert.deepEqual(grouped[0].fields, ["legalRight", "exploitationMode"]);
});

test("빈 quote가 있는 필드를 누락으로 판정한다", () => {
  const missing = missingEvidenceFields({ legalRight: [{ quote: "전송권" }] });
  assert.ok(!missing.includes("legalRight"));
  assert.ok(missing.includes("period"));
});

test("첫 evidence 수정 시 기본 배열 구조를 만든다", () => {
  const next = updateFirstEvidenceEntry({}, "territory", { quote: "대한민국" });
  assert.equal(next.territory[0].location, "본문");
  assert.equal(next.territory[0].quote, "대한민국");
});
