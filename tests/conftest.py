"""DB 테스트 공용 픽스처 (D-30 스키마 기준).

실행 전 DB가 떠 있어야 한다(`docker compose up -d`, 또는 동등한 PostgreSQL 16 인스턴스).

각 테스트는 자기 트랜잭션에서 ip · content_asset · contract · contract_history를
만들고 teardown에서 통째로 rollback한다.
"""

from __future__ import annotations

import json
import os
import uuid

import psycopg2
import pytest

from app.core.config import get_settings


def _dsn():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        try:
            url = get_settings().database_url
        except Exception:  # noqa: BLE001
            return None
    if not url:
        return None
    return url.replace("postgresql+psycopg2", "postgresql").replace(
        "postgresql+psycopg", "postgresql"
    )


def _db_available() -> bool:
    dsn = _dsn()
    if not dsn:
        return False
    try:
        connection = psycopg2.connect(dsn, connect_timeout=2)
        connection.close()
        return True
    except Exception:  # noqa: BLE001
        return False


requires_db = pytest.mark.skipif(
    not _db_available(), reason="P2-DB 적용 PostgreSQL 필요"
)


@pytest.fixture
def conn():
    dsn = _dsn()
    if not dsn or not _db_available():
        pytest.skip("P2-DB 적용 PostgreSQL 필요")
    connection = psycopg2.connect(dsn)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


@pytest.fixture
def cur(conn):
    return conn.cursor()


@pytest.fixture
def ctx(cur):
    """테스트 1건이 쓸 ip · content_asset · contract · contract_history 한 벌."""
    cur.execute(
        "INSERT INTO ip (title, kind) VALUES ('겨울의 신호', '드라마') RETURNING id",
    )
    ip_id = cur.fetchone()[0]

    cur.execute(
        "SELECT id FROM content_asset WHERE ip_id = %s AND scope_type = 'SERIES_ALL'",
        (ip_id,),
    )
    content_asset_id = cur.fetchone()[0]

    cur.execute(
        "INSERT INTO contract (grantor, grantee) VALUES ('mindex', '테스트 상대방') RETURNING id",
    )
    contract_id = cur.fetchone()[0]

    cur.execute(
        "INSERT INTO contract_history "
        "  (contract_id, version, status, file_name, file_path, file_hash) "
        "VALUES (%s, 1, 'applied', 'test.pdf', 's3://test/1.pdf', 'sha256:test') "
        "RETURNING id",
        (contract_id,),
    )
    history_id = cur.fetchone()[0]

    return {
        "ip_id": ip_id,
        "content_asset_id": content_asset_id,
        "contract_id": contract_id,
        "history_id": history_id,
    }


def _default_evidence():
    entry = {"quote": "제8조 (권리의 부여) 본 계약에 따라...", "page": 8, "clause": "제8조"}
    return {
        "legal_right": entry,
        "exploitation_mode": entry,
        "territory": entry,
        "period": entry,
        "exclusivity": entry,
    }


@pytest.fixture
def make_grant(cur, ctx):
    """rights_grant 행을 EXCLUDE 경로로 직접 INSERT한다.

    save_rights_batch()를 거치지 않는다 — 이 픽스처를 쓰는 테스트가 검증하려는
    것은 판정 함수가 아니라 EXCLUDE/트리거 자체이기 때문이다.
    span 두 컬럼과 lineage_id는 넘기지 않는다: 트리거가 채운다.
    """

    def _make(
        legal_right="TRANSMISSION",
        exploitation_mode="SVOD",
        territory="JP",
        period="[2027-01-01,2028-01-01)",
        exclusivity="exclusive",
        contract_id=None,
        content_asset_id=None,
        evidence=None,
    ):
        cur.execute(
            """
            INSERT INTO rights_grant
              (contract_id, contract_history_id, content_asset_id,
               territory, legal_right, exploitation_mode, period, exclusivity, evidence)
            VALUES (%s, %s, %s,
                    %s, %s, %s, %s::daterange, %s, %s::jsonb)
            RETURNING id
            """,
            (
                contract_id or ctx["contract_id"], ctx["history_id"],
                content_asset_id or ctx["content_asset_id"],
                territory, legal_right, exploitation_mode, period, exclusivity,
                json.dumps(evidence or _default_evidence()),
            ),
        )
        return cur.fetchone()[0]

    return _make


@pytest.fixture
def make_batch_row():
    """save_rights_batch()/validate_rights_batch()의 p_rights 배열 원소 하나."""

    def _make(
        legal_right="TRANSMISSION",
        exploitation_mode="SVOD",
        territory="JP",
        period="[2027-01-01,2028-01-01)",
        exclusivity="exclusive",
        content_asset_id=None,
        evidence=None,
        conditions_raw=None,
    ):
        row = {
            "territory": territory,
            "legal_right": legal_right,
            "exploitation_mode": exploitation_mode,
            "period": period,
            "exclusivity": exclusivity,
            "evidence": evidence or _default_evidence(),
        }
        if content_asset_id is not None:
            row["content_asset_id"] = content_asset_id
        if conditions_raw is not None:
            row["conditions_raw"] = conditions_raw
        return row

    return _make


@pytest.fixture
def make_staging_job(cur):
    """staging.pdf_blob + staging.extract_job(status='DONE') 한 벌을 만들고 tmpid를 반환한다.

    D-33 — contract.source_tmpid가 staging.extract_job.tmpid에 실제 FK로 걸려
    있어서, save_rights_batch(p_source_tmpid=>...)에 넘길 tmpid는 이제
    staging 쪽에 실제로 존재해야 한다(없으면 ForeignKeyViolation).
    """

    def _make(status="DONE"):
        tmpid = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO staging.pdf_blob (tmpid, data) VALUES (%s::uuid, %s)",
            (tmpid, b"%PDF-1.4 test"),
        )
        cur.execute(
            "INSERT INTO staging.extract_job (tmpid, status) VALUES (%s::uuid, %s)",
            (tmpid, status),
        )
        return tmpid

    return _make


_MASTER = [
    "rights_grant",
    "contract_chunk",
    "contract_history",
    "contract",
    "content_asset",
    "ip_alias",
    "ip",
    "team",
]
_STAGING = ["extract_result", "extract_job", "pdf_blob"]


@pytest.fixture
def clean_db(conn):
    """API 통합 테스트용 초기 데이터와 단일 팀을 만든다."""
    cur = conn.cursor()
    cur.execute(
        "TRUNCATE "
        + ", ".join(_MASTER)
        + ", "
        + ", ".join(f"staging.{table}" for table in _STAGING)
        + " RESTART IDENTITY CASCADE"
    )
    import bcrypt

    pin_hash = bcrypt.hashpw(b"1234", bcrypt.gensalt()).decode()
    cur.execute(
        "INSERT INTO team(name, pin_hash) VALUES ('T', %s) RETURNING id",
        (pin_hash,),
    )
    team_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO ip(title, kind) VALUES ('겨울의 신호', 'DRAMA') RETURNING id"
    )
    ip_id = cur.fetchone()[0]
    cur.execute(
        "SELECT id FROM content_asset WHERE ip_id=%s ORDER BY id LIMIT 1", (ip_id,)
    )
    asset_id = cur.fetchone()[0]
    conn.commit()
    return {"team_id": team_id, "ip_id": ip_id, "asset_id": asset_id}


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.db import get_db
    from app.main import app

    engine = create_engine(_dsn(), future=True)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _override():
        db = test_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


def evidence():
    quote = {"quote": "제8조 제1항 …"}
    return {
        "legal_right": quote,
        "exploitation_mode": quote,
        "territory": quote,
        "period": quote,
        "exclusivity": quote,
    }


def body(
    clean_db,
    *,
    exclusivity="exclusive",
    territory="KR",
    legal_right="TRANSMISSION",
    exploitation_mode="SVOD",
    start="2027-01-01",
    end="2027-12-31",
    source_tmpid=None,
    ip_id="__seed__",
):
    request_body = {
        "grantor": "C사",
        "grantee": "T사",
        "ipId": clean_db["ip_id"] if ip_id == "__seed__" else ip_id,
        "fileName": "contract.pdf",
        "filePath": "/tmp/contract.pdf",
        "fileHash": "h" * 8,
        "documentKind": "final",
        "rights": [
            {
                "contentAssetId": clean_db["asset_id"],
                "legalRight": legal_right,
                "exploitationMode": exploitation_mode,
                "territories": [territory],
                "period": {"start": start, "end": end},
                "exclusivity": exclusivity,
                "evidence": evidence(),
            }
        ],
    }
    if source_tmpid:
        request_body["sourceTmpid"] = str(source_tmpid)
    return request_body
