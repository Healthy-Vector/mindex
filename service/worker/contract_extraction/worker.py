#!/usr/bin/env python3
"""
Contract extraction — worker.py (체크리스트 7번)

⚠️ 실제 mindex 저장소에서는 이 파일이 app/worker.py 경로에 들어간다.

extract_job 을 QUEUED 상태로 클레임 -> RUNNING(stage=OCR→LLM) -> service.run_extraction() 실행
-> repository 로 저장 -> DONE/FAILED. K8s Worker Deployment 의 진입점.

⚠️ 2026-08-23 갱신 — Notion "api 명세서"(§3)에서 확인한 origin/P2-DB 실제 SQL 기준으로
   컬럼명을 다시 맞췄다. 이전(가희 임시안)과 실제가 달랐던 부분:
     pdf_blob.content -> data,  extract_job.last_error -> reason,
     updated_at 컬럼 자체가 없음(전 테이블),  max_attempts 컬럼 없음(아래 MAX_ATTEMPTS 상수로 관리),
     extract_job.stage(OCR|LLM) 컬럼 추가 — Document retrieval(OCR)+Contract extraction(LLM)가 한 job 안에서 순차 실행되는 걸
     반영해, service.run_extraction() 의 on_stage 콜백으로 이 컬럼을 갱신한다(화면 폴링 API가
     "파싱 중"/"추출 중" 문구를 이 값으로 구분해서 보여준다 — api 명세서 §3 GET /extract/{tmpid}).

⚠️ OCR/E5 모델 1회 로딩(팀 확정 사항)은 이 워커 프로세스가 아니라 실제 Document retrieval
   코드(retrieve_contract_chunks 구현) 쪽 책임이다. task1_mock 은 모델을 안 쓰므로
   여기선 해당 없음 — 실제 Document retrieval로 교체될 때 모듈 최상단에서 1회 로딩되는지 확인 필요.
"""
from __future__ import annotations

import importlib
import os
import signal
import time
import uuid
from typing import Protocol

from .repository import ExtractResultRepository, get_repository
from .service import RetrieveFn, run_extraction

MAX_ATTEMPTS = 3  # DB에 컬럼 없음 — 앱 코드 상수로 관리 (api 명세서 §3 실 SQL 기준)


def load_retrieve_fn(spec: str | None = None) -> RetrieveFn:
    """`모듈:함수` 경로에서 Document retrieval 함수를 불러온다."""
    spec = spec or os.getenv("MINDEX_RETRIEVE_FN")

    if not spec:
        raise RuntimeError(
            "MINDEX_RETRIEVE_FN이 필요합니다. "
            "형식: package.module:retrieve_contract_chunks"
        )

    module_name, separator, function_name = spec.partition(":")

    if not separator or not module_name or not function_name:
        raise ValueError("MINDEX_RETRIEVE_FN 형식은 `모듈:함수`여야 합니다.")

    function = getattr(importlib.import_module(module_name), function_name)

    if not callable(function):
        raise TypeError(f"{spec}는 호출 가능한 함수가 아닙니다.")

    return function


class JobStore(Protocol):
    def claim_next_job(self) -> dict | None: ...
    def load_pdf_bytes(self, tmpid: str) -> bytes: ...
    def update_stage(self, tmpid: str, stage: str) -> None: ...
    def mark_done(self, tmpid: str) -> None: ...
    def mark_failed(self, tmpid: str, reason: str) -> None: ...


class MockJobStore:
    """DB 없이 워커 루프를 확인하기 위한 메모리 큐. 테스트 전용."""

    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._blobs: dict[str, bytes] = {}

    def seed(self, tmpid: str, pdf_bytes: bytes, max_attempts: int = MAX_ATTEMPTS) -> None:
        self._blobs[tmpid] = pdf_bytes
        self._jobs[tmpid] = {
            "tmpid": tmpid, "status": "QUEUED", "stage": None, "attempts": 0,
            "max_attempts": max_attempts, "reason": None,
        }

    def claim_next_job(self) -> dict | None:
        for job in self._jobs.values():
            if job["status"] == "QUEUED":
                job["status"] = "RUNNING"
                job["attempts"] += 1
                return dict(job)
        return None

    def load_pdf_bytes(self, tmpid: str) -> bytes:
        return self._blobs[tmpid]

    def update_stage(self, tmpid: str, stage: str) -> None:
        self._jobs[tmpid]["stage"] = stage

    def mark_done(self, tmpid: str) -> None:
        self._jobs[tmpid]["status"] = "DONE"
        self._jobs[tmpid]["stage"] = None

    def mark_failed(self, tmpid: str, reason: str) -> None:
        job = self._jobs[tmpid]
        job["reason"] = reason
        if job["attempts"] >= job["max_attempts"]:
            job["status"] = "FAILED"
        else:
            job["status"] = "QUEUED"  # 재시도 대기열로 복귀
            job["stage"] = None

    def status_of(self, tmpid: str) -> str:
        return self._jobs[tmpid]["status"]


def _reason_code(stage: str | None, exc: Exception) -> str:
    """api 명세서 §6 에 나열된 FAILED reason 코드로 매핑한다.
    (OCR_TIMEOUT · OCR_FAILED · LLM_EXTRACTION_FAILED — 백엔드 확정 미확인이지만 프론트가 이 값을 처리함)"""
    if stage == "OCR":
        return "OCR_TIMEOUT" if isinstance(exc, TimeoutError) else "OCR_FAILED"
    return "LLM_EXTRACTION_FAILED"


class PgJobStore:
    """staging.extract_job/pdf_blob 을 실제로 다루는 구현.

    claim_next_job() 은 짧은 트랜잭션으로 FOR UPDATE SKIP LOCKED 클레임만 하고 즉시
    커밋한다 — 실제 추출(수십 초~수 분) 은 그 트랜잭션 밖에서 실행해 락을 오래 안 쥔다.
    권한 전제: staging.extract_job 에 SELECT·UPDATE (체크리스트 6번, sql/staging_schema.sql).
    """

    LEASE_SECONDS = 600  # 워커가 죽었을 때 다른 워커가 재클레임할 수 있는 시간

    def __init__(self, dsn: str | None = None):
        from repository import dsn_from_env
        self._dsn = dsn or dsn_from_env()

    def _conn(self):
        import psycopg2
        return psycopg2.connect(self._dsn)

    def claim_next_job(self) -> dict | None:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT tmpid, attempts FROM staging.extract_job
                    WHERE status = 'QUEUED'
                       OR (status = 'RUNNING' AND lease_until < now())
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
                if row is None:
                    conn.commit()
                    return None
                tmpid, attempts = row
                cur.execute(
                    """
                    UPDATE staging.extract_job
                       SET status = 'RUNNING',
                           attempts = attempts + 1,
                           lease_until = now() + make_interval(secs => %s)
                     WHERE tmpid = %s
                    """,
                    (self.LEASE_SECONDS, tmpid),
                )
            conn.commit()
            return {"tmpid": str(tmpid), "attempts": attempts + 1}
        finally:
            conn.close()

    def load_pdf_bytes(self, tmpid: str) -> bytes:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT data FROM staging.pdf_blob WHERE tmpid = %s", (tmpid,))
                row = cur.fetchone()
                if row is None:
                    raise RuntimeError(f"pdf_blob 에 tmpid={tmpid} 없음")
                return bytes(row[0])
        finally:
            conn.close()

    def update_stage(self, tmpid: str, stage: str) -> None:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE staging.extract_job SET stage=%s WHERE tmpid=%s", (stage, tmpid))
            conn.commit()
        finally:
            conn.close()

    def mark_done(self, tmpid: str) -> None:
        """AI 추출 완료만 표시한다. consumed_at은 사용자 확정 API에서 갱신한다."""
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE staging.extract_job SET status='DONE', stage=NULL WHERE tmpid=%s",
                    (tmpid,),
                )
            conn.commit()
        finally:
            conn.close()

    def mark_failed(self, tmpid: str, reason: str) -> None:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE staging.extract_job
                       SET status = CASE WHEN attempts >= %s THEN 'FAILED' ELSE 'QUEUED' END,
                           stage = CASE WHEN attempts >= %s THEN stage ELSE NULL END,
                           reason = %s
                     WHERE tmpid = %s
                    """,
                    (MAX_ATTEMPTS, MAX_ATTEMPTS, reason[:2000], tmpid),
                )
            conn.commit()
        finally:
            conn.close()


def get_job_store(kind: str = "mock", **kwargs) -> JobStore:
    import os
    kind = os.getenv("MINDEX_JOB_STORE", kind)
    if kind == "pg":
        return PgJobStore(**kwargs)
    return MockJobStore()


def process_one(job_store: JobStore, repo: ExtractResultRepository,
                retrieve_fn: RetrieveFn, extractor=None) -> bool:
    """대기 중인 job 하나를 처리한다. 처리할 게 없으면 False."""
    job = job_store.claim_next_job()
    if job is None:
        return False

    tmpid = job["tmpid"]
    current_stage = {"value": None}

    def on_stage(stage: str) -> None:
        current_stage["value"] = stage
        job_store.update_stage(tmpid, stage)

    try:
        pdf_bytes = job_store.load_pdf_bytes(tmpid)
        result = run_extraction(
            pdf_bytes, retrieve_fn=retrieve_fn, extractor=extractor,
            request_id=f"req-{uuid.uuid4().hex[:12]}",
            on_stage=on_stage,
        )
        repo.save(tmpid, result.to_dict())
        job_store.mark_done(tmpid)
    except Exception as e:  # noqa: BLE001 — 어떤 예외든 FAILED/재시도로 전환하고 삼킨다
        job_store.mark_failed(tmpid, reason=_reason_code(current_stage["value"], e))
    return True


def run_worker(job_store: JobStore, repo: ExtractResultRepository,
               retrieve_fn: RetrieveFn, extractor=None,
               poll_interval: float = 5.0, max_empty_polls: int | None = None) -> None:
    """K8s Worker Deployment 진입점이 되는 메인 루프.

    max_empty_polls 를 주면 그만큼 연속으로 빈 큐를 확인한 뒤 종료한다 (테스트용).
    None 이면 SIGTERM 받을 때까지 무한 루프.
    """
    stop = {"flag": False}

    def _handle_sigterm(signum, frame):
        stop["flag"] = True  # 현재 처리 중인 job은 끝까지 마치고 다음 루프에서 종료

    signal.signal(signal.SIGTERM, _handle_sigterm)

    empty_polls = 0
    while not stop["flag"]:
        did_work = process_one(
            job_store, repo, retrieve_fn=retrieve_fn, extractor=extractor
        )
        if did_work:
            empty_polls = 0
            continue
        empty_polls += 1
        if max_empty_polls is not None and empty_polls >= max_empty_polls:
            return
        time.sleep(poll_interval)


if __name__ == "__main__":
    print("Contract extraction worker starting")
    _retrieve_fn = load_retrieve_fn()
    _job_store = get_job_store()
    _repo = get_repository()
    run_worker(_job_store, _repo, retrieve_fn=_retrieve_fn)
