#!/usr/bin/env python3
"""
Ollama 없이 service.run_extraction() 전체 배선(Document retrieval Mock -> Contract extraction)을 확인한다.
fixture_raw_extraction.json 을 "LLM이 이미 뽑아낸 결과"로 가정하는 FixtureExtractor 를 주입한다.

실행: python3 tests/test_service_smoke.py  (contract extraction/ 안에서)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

from service.worker.contract_extraction.service import run_extraction  # noqa: E402
from tests.contract_extraction.mock_retrieval import retrieve_contract_chunks  # noqa: E402


class FixtureExtractor:
    """extractor.OllamaExtractor 대신 fixture 를 돌려주는 테스트용 stub."""

    def __init__(self, fixture_path: str):
        with open(fixture_path, encoding="utf-8") as f:
            self._raw = json.load(f)

    def extract_raw(self, bundle: dict) -> dict:
        # 실제로는 dict 를 매번 복사해서 반환해야 attach_evidence_location 이
        # 원본 fixture 파일을 오염시키지 않는다.
        import copy
        return copy.deepcopy(self._raw)


def test_service_smoke():
    fixture_path = os.path.join(HERE, "fixture_raw_extraction.json")
    result = run_extraction(
        pdf_bytes=b"dummy-pdf-bytes",
        retrieve_fn=retrieve_contract_chunks,
        extractor=FixtureExtractor(fixture_path),
    )

    print("=== Document retrieval(Mock) -> Contract extraction 배선 확인 ===")
    assert result.raw["contract"]["evidence"][0].get("start_char") is not None, \
        "evidence-1 위치가 attach_evidence_location 에서 채워져야 한다"
    print("  ✅ evidence 위치 후처리까지 정상 연결됨")

    assert result.validation["ref_problems"], "grant-9 참조 무결성 위반이 잡혀야 한다"
    print(f"  ✅ validator 연결 확인 — confidence={result.validation['confidence']}, "
          f"route={result.validation['route']}")

    assert result.normalized["contract"]["rights_grants"][0]["_territory_effective"]["effective"] == ["JP"]
    print("  ✅ normalizer 연결 확인 — territory effective=['JP']")

    assert result.compact["payload"]["contract"]["title"] == "콘텐츠 이용허락 계약서"
    assert result.compact["source_document_ref"] == "mockcontract0001hash"
    print("  ✅ projector 연결 확인 — compact 출력 정상, source_document_ref 는 Mock bundle 의 document.file_hash 그대로")

    print("\n✅ service.run_extraction(pdf_bytes) 전체 배선(Document retrieval Mock -> Contract extraction) 정상 동작")


if __name__ == "__main__":
    test_service_smoke()
