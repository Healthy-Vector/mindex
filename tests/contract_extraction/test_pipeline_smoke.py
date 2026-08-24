#!/usr/bin/env python3
"""
Ollama 없이 돌리는 스모크 테스트.
fixture_raw_extraction.json 을 "LLM이 이미 뽑아낸 결과"로 가정하고
extractor(후처리) → validator → normalizer → projector 전체 체인을 확인한다.

실행: python3 tests/test_pipeline_smoke.py  (contract extraction/ 안에서)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

from service.worker.contract_extraction.extractor import attach_evidence_location  # noqa: E402
from service.worker.contract_extraction.normalizer import normalize_contract  # noqa: E402
from service.worker.contract_extraction.projector import project  # noqa: E402
from service.worker.contract_extraction.validator import validate, verify_evidence_text  # noqa: E402


def test_pipeline_smoke():
    with open(os.path.join(HERE, "fixtures", "mock_retrieved_chunks.json"), encoding="utf-8") as f:
        bundle = json.load(f)
    with open(os.path.join(HERE, "fixture_raw_extraction.json"), encoding="utf-8") as f:
        raw = json.load(f)

    # ① extractor 후처리 — evidence 위치 채우기
    raw = attach_evidence_location(raw, bundle)
    print("=== ① evidence 위치 부여 ===")
    for ev in raw["contract"]["evidence"]:
        print(f"  {ev['evidence_ref']}: section={ev.get('section')!r} "
              f"page={ev.get('page_start')} chars=[{ev.get('start_char')},{ev.get('end_char')})")

    # ② validator — 환각·참조 무결성·논리
    report = validate(raw, bundle)
    print("\n=== ② 검증 리포트 ===")
    for k, v in report.items():
        print(f"  {k}: {v}")

    assert report["ref_problems"], "grant-9 를 가리키는 evidence-3 이 잡혀야 한다"
    from service.worker.contract_extraction.validator import _joined_source_text
    source_text = _joined_source_text(bundle)
    halluc_results = [verify_evidence_text(ev, source_text) for ev in raw["contract"]["evidence"]]
    assert any(not ok and "환각" in reason for ok, reason in halluc_results), \
        "evidence-3 텍스트 환각이 잡혀야 한다"
    print("\n  ✅ 환각(evidence-3)과 참조 무결성 위반(grant-9) 둘 다 정상적으로 잡혔다")

    # ⚠️ 커버리지 갭 확인 — bundle["chunks"] 가 6개 질의(territory/rights_type/period/
    # exclusivity/payment/parties)에 안 걸린 청크(c-1 제1조/c-5 제5조)를 아예 안 담고
    # 있어서, agreement_type·authority_constraints 근거가 여기선 "환각"으로 오탐된다.
    # 실제 LLM 잘못이 아니라 Document retrieval 검색 커버리지 문제 — dropped_fields 로 확인.
    if report["dropped_fields"]:
        print(f"\n  ⚠️ 커버리지 갭으로 오탐된 필드: {report['dropped_fields']}")
        print("     (c-1/c-5 가 6개 질의 밖이라 bundle에서 아예 빠짐 — 팀 논의 필요)")

    # ③ normalizer — territory 실효범위
    normalized = normalize_contract(raw)
    print("\n=== ③ territory 정규화 ===")
    g0 = normalized["contract"]["rights_grants"][0]
    print(f"  effective: {g0['_territory_effective']}")
    print(f"  scopes:    {g0['_territory_scopes']}")

    # ④ projector — Compact DB Projection
    compact = project(normalized, request_id="req-smoke-1", source_document_ref="mock-contract-001")
    print("\n=== ④ Compact DB Projection ===")
    print(json.dumps(compact, ensure_ascii=False, indent=2))

    print("\n✅ 전체 체인(extractor 후처리 → validator → normalizer → projector) 정상 동작")


if __name__ == "__main__":
    test_pipeline_smoke()
