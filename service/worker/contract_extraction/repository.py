#!/usr/bin/env python3
"""
Contract extraction — repository.py

추출 결과(payload)를 staging.extract_result 에 적재한다.

권한 전제 (2026-08-22 체크리스트 6번 확정 — 이전 "insert/select만" 가정에서 갱신됨):
    워커 role 은 staging.extract_result 에 SELECT·INSERT·UPDATE 를 전부 가진다
    (staging.pdf_blob 은 SELECT만, staging.extract_job 은 SELECT·UPDATE — sql/staging_schema.sql 참고).
    → UPDATE 권한이 있으므로 ON CONFLICT (tmpid) DO UPDATE 를 쓴다.
      같은 tmpid 로 재시도(예: 워커가 죽었다 재기동)가 들어오면 이전 결과를 최신 값으로 덮어쓴다.

⚠️ extract_job.status 를 'RUNNING'/'DONE'/'FAILED' 로 바꾸는 것은 이 모듈의 책임이 아니다.
   그건 워커 하네스(worker.py, P1 담당)가 처리한다. repository.py 는 여전히
   "결과를 staging.extract_result 에 적재하는 것"까지만 한다 — 책임 범위는 그대로 유지.
"""
from __future__ import annotations

import json
import os
from typing import Protocol


def dsn_from_env() -> str:
    """DATABASE_URL(K8s Deployment 표준, 체크리스트 13번) 이 있으면 그걸 그대로 쓰고,
    없으면 PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD 로 조립한다 (로컬 개발용 폴백).

    배포 환경에서 값을 명시적으로 안 넣으면 접속 시점에 바로 에러가 나서
    설정 누락이 조용히 묻히지 않는다 (extractor.py 의 OLLAMA_BASE_URL 처리와 같은 패턴)."""
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url
    host = os.getenv("PGHOST", "localhost")
    port = os.getenv("PGPORT", "5432")
    dbname = os.getenv("PGDATABASE", "mindex")
    user = os.getenv("PGUSER", "mindex")
    password = os.getenv("PGPASSWORD", "")
    return f"host={host} port={port} dbname={dbname} user={user} password={password}"


class ExtractResultRepository(Protocol):
    def save(self, tmpid: str, payload: dict) -> None: ...
    def exists(self, tmpid: str) -> bool: ...


class MockRepository:
    """DB 연결 없이 테스트하기 위한 메모리 저장소."""

    def __init__(self):
        self._store: dict[str, dict] = {}

    def save(self, tmpid: str, payload: dict) -> None:
        self._store[tmpid] = {"payload": payload}

    def exists(self, tmpid: str) -> bool:
        return tmpid in self._store

    def get(self, tmpid: str) -> dict | None:
        return self._store.get(tmpid)


class PgExtractResultRepository:
    """staging.extract_result 에 적재하는 실제 구현.

    연결 role 은 staging 스키마에 INSERT·SELECT 권한만 가진 것을 전제로 한다.
    """

    def __init__(self, dsn: str | None = None, conn=None):
        """dsn 을 주면 매 호출마다 새 연결을 연다. conn 을 주면 그 연결을 재사용한다
        (워커 루프처럼 커넥션을 계속 들고 있는 경우).
        dsn 을 안 주면 dsn_from_env() 로 환경변수에서 채운다."""
        self._dsn = dsn or dsn_from_env()
        self._conn = conn

    def _get_conn(self):
        if self._conn is not None:
            return self._conn
        import psycopg2
        return psycopg2.connect(self._dsn)

    def save(self, tmpid: str, payload: dict) -> None:
        conn = self._get_conn()
        owns_conn = self._conn is None
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO staging.extract_result (tmpid, payload)
                    VALUES (%s, %s)
                    ON CONFLICT (tmpid) DO UPDATE
                        SET payload = EXCLUDED.payload
                    """,
                    (tmpid, json.dumps(payload, ensure_ascii=False)),
                )
            if owns_conn:
                conn.commit()
        finally:
            if owns_conn:
                conn.close()

    def exists(self, tmpid: str) -> bool:
        conn = self._get_conn()
        owns_conn = self._conn is None
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM staging.extract_result WHERE tmpid = %s", (tmpid,))
                return cur.fetchone() is not None
        finally:
            if owns_conn:
                conn.close()


def get_repository(kind: str = "mock", **kwargs) -> ExtractResultRepository:
    """kind='mock' | 'pg'. 환경변수 MINDEX_REPOSITORY 로도 선택 가능."""
    kind = os.getenv("MINDEX_REPOSITORY", kind)
    if kind == "pg":
        return PgExtractResultRepository(**kwargs)
    return MockRepository()


if __name__ == "__main__":
    repo = get_repository("mock")
    repo.save("tmpid-demo", {"contract": {"contract_title": {"value": "테스트"}}}, 0.9)
    print("saved:", repo.exists("tmpid-demo"))
    print("get:", repo.get("tmpid-demo"))
