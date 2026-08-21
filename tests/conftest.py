"""DB 테스트 공용 픽스처 (D-30 스키마 기준).

실행 전 DB가 떠 있어야 한다(`docker compose up -d`, 또는 동등한 PostgreSQL 16 인스턴스).

각 테스트는 자기 트랜잭션에서 ip · content_asset · contract · contract_history를
만들고 teardown에서 통째로 rollback한다.
"""

from __future__ import annotations

import json

import psycopg2
import pytest

from app.core.config import get_settings


@pytest.fixture
def conn():
    settings = get_settings()
    dsn = settings.database_url.replace("postgresql+psycopg2", "postgresql")
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
        "INSERT INTO contract (counterparty) VALUES ('테스트 상대방') RETURNING id",
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
