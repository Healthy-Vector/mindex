#!/usr/bin/env python3
"""
DB/Ollama 없이 worker.py 의 QUEUED -> RUNNING -> extract_result 저장 -> DONE 흐름을 확인한다.
MockJobStore(메모리 큐) + MockRepository(메모리 저장소) + FixtureExtractor(가짜 LLM) 사용.

실행: python3 tests/test_worker_smoke.py  (contract extraction/ 안에서)
"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

from service.worker.contract_extraction.repository import MockRepository  # noqa: E402
from service.worker.contract_extraction.worker import MockJobStore, run_worker  # noqa: E402
from tests.contract_extraction.mock_retrieval import retrieve_contract_chunks  # noqa: E402


class FixtureExtractor:
    def __init__(self, fixture_path: str):
        with open(fixture_path, encoding="utf-8") as f:
            self._raw = json.load(f)

    def extract_raw(self, bundle: dict) -> dict:
        return copy.deepcopy(self._raw)


def test_worker_smoke():
    job_store = MockJobStore()
    repo = MockRepository()
    tmpid = "job-smoke-1"
    job_store.seed(tmpid, pdf_bytes=b"dummy-pdf-bytes")  # document retrieval_mock 이 내용은 안 봄

    fixture_path = os.path.join(HERE, "fixture_raw_extraction.json")
    run_worker(
        job_store, repo,
        retrieve_fn=retrieve_contract_chunks,
        extractor=FixtureExtractor(fixture_path),
        max_empty_polls=1,   # job 하나 처리하고 큐 비면 바로 종료 (테스트용)
        poll_interval=0,
    )

    print("=== worker 스모크 테스트 ===")
    status = job_store.status_of(tmpid)
    print(f"  job 상태: {status}")
    assert status == "DONE", f"DONE 이어야 하는데 {status}"

    assert repo.exists(tmpid), "repository 에 결과가 저장돼야 한다"
    saved = repo.get(tmpid)
    assert saved is not None
    assert "confidence" not in saved, "대표 confidence는 별도 저장하지 않아야 한다"
    assert "compact" in saved["payload"], "ExtractionResult 전체(raw/validation/normalized/compact)가 저장돼야 한다"

    print("\n✅ QUEUED -> RUNNING -> extract_result 저장 -> DONE 전체 흐름 정상 동작")


def test_retry_then_fail():
    """의도적으로 실패하는 extractor 로 재시도 -> FAILED 전환을 확인한다."""
    class BoomExtractor:
        def extract_raw(self, retrieved_chunks):
            raise RuntimeError("의도된 실패 (테스트)")

    job_store = MockJobStore()
    repo = MockRepository()
    tmpid = "job-smoke-fail"
    job_store.seed(tmpid, pdf_bytes=b"dummy", max_attempts=2)

    # max_attempts=2 라 두 번 실패하면 FAILED. 매번 큐에서 하나씩만 처리하도록 반복 호출.
    from service.worker.contract_extraction.worker import process_one
    process_one(job_store, repo, retrieve_fn=retrieve_contract_chunks, extractor=BoomExtractor())
    assert job_store.status_of(tmpid) == "QUEUED", "1차 실패는 재시도 대기열로 돌아가야 한다"
    process_one(job_store, repo, retrieve_fn=retrieve_contract_chunks, extractor=BoomExtractor())
    assert job_store.status_of(tmpid) == "FAILED", "attempts 소진 후엔 FAILED 여야 한다"
    print("✅ 실패 재시도 -> attempts 소진 후 FAILED 전환 정상 동작")


if __name__ == "__main__":
    test_worker_smoke()
    test_retry_then_fail()
