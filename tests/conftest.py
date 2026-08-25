"""통합 테스트 픽스처 (P2-DB 정렬).

실제 PostgreSQL(P2-DB sql/init 적용: public 스키마 + 함수 + 참조데이터)이 있어야 돈다.
없으면 통합 테스트를 skip 한다. 환경변수 TEST_DATABASE_URL (없으면 settings.database_url).
"""
from __future__ import annotations

import os

import pytest

try:
    import psycopg2
except Exception:  # noqa: BLE001
    psycopg2 = None


def _dsn():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        try:
            from app.core.config import get_settings
            url = get_settings().database_url
        except Exception:  # noqa: BLE001
            return None
    if not url:
        return None
    return url.replace("postgresql+psycopg2", "postgresql").replace("postgresql+psycopg", "postgresql")


def _db_available() -> bool:
    if psycopg2 is None:
        return False
    dsn = _dsn()
    if not dsn:
        return False
    try:
        c = psycopg2.connect(dsn, connect_timeout=2)
        c.close()
        return True
    except Exception:  # noqa: BLE001
        return False


requires_db = pytest.mark.skipif(not _db_available(), reason="P2-DB 적용 PostgreSQL 필요")

_MASTER = ["rights_grant", "contract_chunk", "contract_history", "contract",
           "content_asset", "ip_alias", "ip", "team"]
_STAGING = ["extract_result", "extract_job", "pdf_blob"]


@pytest.fixture
def conn():
    c = psycopg2.connect(_dsn())
    c.autocommit = False
    yield c
    c.rollback()
    c.close()


@pytest.fixture
def clean_db(conn):
    """도메인/ staging 테이블만 비우고 단일 팀 + IP 시드. 참조 어휘(legal_right 등)는 보존."""
    cur = conn.cursor()
    cur.execute("TRUNCATE " + ", ".join(_MASTER) + ", "
                + ", ".join(f"staging.{t}" for t in _STAGING) + " RESTART IDENTITY CASCADE")
    import bcrypt
    ph = bcrypt.hashpw(b"1234", bcrypt.gensalt()).decode()
    cur.execute("INSERT INTO team(name, pin_hash) VALUES ('T', %s) RETURNING id", (ph,))
    team_id = cur.fetchone()[0]
    cur.execute("INSERT INTO ip(title, kind) VALUES ('겨울의 신호', 'DRAMA') RETURNING id", ())
    ip_id = cur.fetchone()[0]  # 트리거가 기본 content_asset 생성
    cur.execute("SELECT id FROM content_asset WHERE ip_id=%s ORDER BY id LIMIT 1", (ip_id,))
    asset_id = cur.fetchone()[0]
    conn.commit()
    return {"team_id": team_id, "ip_id": ip_id, "asset_id": asset_id}


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.main import app
    from app.core.db import get_db

    engine = create_engine(_dsn(), future=True)
    TS = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _override():
        db = TS()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()


def evidence():
    q = {"quote": "제8조 제1항 …"}
    return {"legal_right": q, "exploitation_mode": q, "territory": q, "period": q, "exclusivity": q}


def body(clean_db, *, exclusivity="exclusive", territory="KR",
         legal_right="TRANSMISSION", exploitation_mode="SVOD",
         start="2027-01-01", end="2027-12-31", source_tmpid=None, ip_id="__seed__"):
    b = {
        "grantor": "C사",
        "grantee": "T사",
        "ipId": clean_db["ip_id"] if ip_id == "__seed__" else ip_id,
        "fileName": "contract.pdf", "filePath": "/tmp/contract.pdf", "fileHash": "h" * 8,
        "documentKind": "final",
        "rights": [{
            "contentAssetId": clean_db["asset_id"],
            "legalRight": legal_right, "exploitationMode": exploitation_mode,
            "territories": [territory], "period": {"start": start, "end": end},
            "exclusivity": exclusivity, "evidence": evidence(),
        }],
    }
    if source_tmpid:
        b["sourceTmpid"] = str(source_tmpid)
    return b
