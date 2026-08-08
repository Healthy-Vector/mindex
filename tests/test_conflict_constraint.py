"""프로젝트 핵심 기능 스모크 테스트 (TER-001 관련).

이게 통과하면 EXCLUDE 제약조건이 정상 동작한다는 뜻이고,
그러면 프로젝트의 기술적 핵심(DB가 충돌을 판정한다)이 검증된 것이다.

실행 전 docker compose up 으로 DB가 떠 있어야 한다.
"""

from __future__ import annotations

import uuid

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


def test_exclusive_overlap_is_rejected(conn):
    cur = conn.cursor()
    tenant_id = str(uuid.uuid4())

    cur.execute(
        "INSERT INTO content (tenant_id, title) VALUES (%s, %s) RETURNING id",
        (tenant_id, "사랑의 온도"),
    )
    content_id = cur.fetchone()[0]

    cur.execute(
        "INSERT INTO contract (tenant_id, counterparty) VALUES (%s, %s) RETURNING id",
        (tenant_id, "A사"),
    )
    contract_a = cur.fetchone()[0]

    cur.execute(
        "INSERT INTO contract (tenant_id, counterparty) VALUES (%s, %s) RETURNING id",
        (tenant_id, "B사"),
    )
    contract_b = cur.fetchone()[0]

    # A사: 일본 · 스트리밍 · 2024~2028 · 독점 — 성공해야 한다
    cur.execute(
        """
        INSERT INTO rights_grant
          (tenant_id, contract_id, content_id, territory, rights_type, period, is_exclusive)
        VALUES (%s, %s, %s, 'JP', 'STREAMING', daterange('2024-01-01','2028-01-01'), true)
        """,
        (tenant_id, contract_a, content_id),
    )
    conn.commit()

    # B사: 일본 · 스트리밍 · 2026~2029 · 독점 (기간 겹침) — 실패해야 한다
    with pytest.raises(psycopg2.errors.ExclusionViolation):
        cur.execute(
            """
            INSERT INTO rights_grant
              (tenant_id, contract_id, content_id, territory, rights_type, period, is_exclusive)
            VALUES (%s, %s, %s, 'JP', 'STREAMING', daterange('2026-06-01','2029-01-01'), true)
            """,
            (tenant_id, contract_b, content_id),
        )
    conn.rollback()
