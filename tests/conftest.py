"""통합 테스트 픽스처.

실제 PostgreSQL(확장 btree_gist/vector/pgcrypto, 마이그레이션 적용)이 있어야 돈다.
없으면 전 통합 테스트를 skip 한다.

환경변수: TEST_DATABASE_URL (없으면 settings.database_url).
사전 준비: alembic upgrade head 로 스키마·시드가 적용되어 있어야 한다.
"""
from __future__ import annotations

import os
import uuid

import pytest

try:
    import psycopg2
except Exception:  # noqa: BLE001
    psycopg2 = None


def _dsn() -> str | None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        try:
            from app.core.config import get_settings

            url = get_settings().database_url
        except Exception:  # noqa: BLE001
            return None
    if not url:
        return None
    return url.replace("postgresql+psycopg2", "postgresql").replace(
        "postgresql+psycopg", "postgresql"
    )


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


requires_db = pytest.mark.skipif(not _db_available(), reason="실제 PostgreSQL 이 필요합니다")


@pytest.fixture
def conn():
    dsn = _dsn()
    c = psycopg2.connect(dsn)
    c.autocommit = False
    c.cursor().execute("SET search_path = master, public")
    yield c
    c.rollback()
    c.close()


@pytest.fixture
def seed(conn):
    """team + ip + content_asset + 두 계약/이력 을 만들고 id 를 돌려준다.

    pin '1234' 의 bcrypt 해시를 team.pin_hash 에 넣어 인증 테스트에 쓴다.
    """
    import bcrypt

    cur = conn.cursor()
    pin_hash = bcrypt.hashpw(b"1234", bcrypt.gensalt()).decode()
    cur.execute(
        "INSERT INTO master.team(name,pin_hash) VALUES ('T',%s) RETURNING id", (pin_hash,)
    )
    team_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO master.ip(team_id,title,kind) VALUES (%s,'사랑의 온도','TV_OTT_SERIES') RETURNING id",
        (team_id,),
    )
    ip_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO master.content_asset(team_id,ip_id,scope_type,title) "
        "VALUES (%s,%s,'SERIES_ALL','전편') RETURNING id",
        (team_id, ip_id),
    )
    asset_id = cur.fetchone()[0]

    contracts = {}
    for cp in ("A", "B"):
        cur.execute(
            "INSERT INTO master.contract(team_id,title,counterparty,status) "
            "VALUES (%s,%s,%s,'draft') RETURNING id",
            (team_id, f"{cp}사 계약", f"{cp}사"),
        )
        cid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO master.contract_history(team_id,contract_id,version,status) "
            "VALUES (%s,%s,'v1','applied') RETURNING id",
            (team_id, cid),
        )
        hid = cur.fetchone()[0]
        contracts[cp] = (cid, hid)
    conn.commit()
    return {
        "team_id": team_id,
        "ip_id": ip_id,
        "asset_id": asset_id,
        "contract_a": contracts["A"][0],
        "history_a": contracts["A"][1],
        "contract_b": contracts["B"][0],
        "history_b": contracts["B"][1],
    }


def insert_grant(cur, seed, contract_key, *, territory="JP", rights_type="SVOD",
                 period="[2024-01-01,2028-01-01)", exclusivity="exclusive",
                 status="active"):
    cid, hid = (seed[f"contract_{contract_key.lower()}"], seed[f"history_{contract_key.lower()}"])
    cur.execute(
        "INSERT INTO master.rights_grant "
        "(team_id,contract_id,contract_history_id,content_asset_id,territory,rights_type,"
        " period,exclusivity,status) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s::daterange,%s,%s) RETURNING id",
        (seed["team_id"], cid, hid, seed["asset_id"], territory, rights_type,
         period, exclusivity, status),
    )
    return cur.fetchone()[0]


# ─── API 테스트용 (TestClient + 깨끗한 단일 팀 DB) ───
_MASTER_TABLES = [
    "rights_grant", "contract_chunk", "contract_history", "contract",
    "content_asset", "ip_relation", "ip_alias", "ip", "team",
]
_STAGING_TABLES = ["extract_result", "extract_job", "pdf_blob"]


def _truncate(conn):
    cur = conn.cursor()
    cur.execute(
        "TRUNCATE "
        + ", ".join(f"master.{t}" for t in _MASTER_TABLES)
        + ", "
        + ", ".join(f"staging.{t}" for t in _STAGING_TABLES)
        + " RESTART IDENTITY CASCADE"
    )
    conn.commit()


def _do_seed(conn):
    import bcrypt

    cur = conn.cursor()
    pin_hash = bcrypt.hashpw(b"1234", bcrypt.gensalt()).decode()
    cur.execute("INSERT INTO master.team(name,pin_hash) VALUES ('T',%s) RETURNING id", (pin_hash,))
    team_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO master.ip(team_id,title,kind) VALUES (%s,'사랑의 온도','TV_OTT_SERIES') RETURNING id",
        (team_id,),
    )
    ip_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO master.content_asset(team_id,ip_id,scope_type,title) "
        "VALUES (%s,%s,'SERIES_ALL','전편') RETURNING id",
        (team_id, ip_id),
    )
    asset_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO master.contract(team_id,title,counterparty,status) "
        "VALUES (%s,'A사 계약','A사','draft') RETURNING id",
        (team_id,),
    )
    cid = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO master.contract_history(team_id,contract_id,version,status) "
        "VALUES (%s,%s,'v1','applied') RETURNING id",
        (team_id, cid),
    )
    hid = cur.fetchone()[0]
    conn.commit()
    return {"team_id": team_id, "ip_id": ip_id, "asset_id": asset_id,
            "contract_a": cid, "history_a": hid}


@pytest.fixture
def clean_db(conn):
    """전 테이블 TRUNCATE 후 단일 팀 재시드 → resolve_team_id 가 이 팀을 고르게 한다."""
    _truncate(conn)
    return _do_seed(conn)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.main import app
    from app.core.db import get_db

    engine = create_engine(
        _dsn(), connect_args={"options": "-csearch_path=master,public"}, future=True
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _override():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()


def make_verify_body(seed, *, mode="new", territory="JP", exclusivity="exclusive",
                     start="2026-06-01", end="2028-12-31", source_tmpid=None):
    body = {
        "mode": mode,
        "title": "신규 계약",
        "counterparty": "C사",
        "rights": [
            {
                "contentAssetId": seed["asset_id"],
                "rightsType": "SVOD",
                "territories": [territory],
                "period": {"start": start, "end": end},
                "exclusivity": exclusivity,
            }
        ],
    }
    if source_tmpid:
        body["sourceTmpid"] = source_tmpid
    return body
