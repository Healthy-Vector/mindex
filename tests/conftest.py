"""DB 테스트 공용 픽스처 (D-29 스키마 기준).

실행 전 `docker compose up -d`로 DB가 떠 있어야 한다.

각 테스트는 자기 트랜잭션에서 ip · contract · document를 만들고 teardown에서
통째로 rollback한다.
"""

from __future__ import annotations

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
    """테스트 1건이 쓸 ip · contract · document 한 벌."""
    cur.execute(
        "INSERT INTO ip (title_ko, title_en, kind) "
        "VALUES ('겨울의 신호', 'Signal of Winter', '드라마') RETURNING id",
    )
    ip_id = cur.fetchone()[0]

    cur.execute(
        "INSERT INTO contract (counterparty) VALUES ('테스트 상대방') RETURNING id",
    )
    contract_id = cur.fetchone()[0]

    cur.execute(
        "INSERT INTO contract_document "
        "  (contract_id, version, file_name, storage_key, file_hash) "
        "VALUES (%s, 1, 'test.pdf', 's3://test/1.pdf', 'sha256:test') RETURNING id",
        (contract_id,),
    )
    document_id = cur.fetchone()[0]

    return {
        "ip_id": ip_id,
        "contract_id": contract_id,
        "document_id": document_id,
    }


@pytest.fixture
def make_candidate(cur, ctx):
    """rights_grant_candidate 한 행을 만든다. 기본값은 '전부 확정된 정상 후보'다."""

    def _make(
        legal_right="TRANSMISSION",
        exploitation_mode="SVOD",
        territory="JP",
        period="[2027-01-01,2028-01-01)",
        exclusivity="exclusive",
        confidence=0.99,
        review_reason_code=None,
    ):
        cur.execute(
            """
            INSERT INTO rights_grant_candidate
              (contract_id, document_id, ip_id,
               territory, legal_right, exploitation_mode, period, exclusivity,
               confidence, review_reason_code)
            VALUES (%s, %s, %s,
                    %s, %s, %s, %s::daterange, %s,
                    %s, %s)
            RETURNING id
            """,
            (
                ctx["contract_id"], ctx["document_id"], ctx["ip_id"],
                territory, legal_right, exploitation_mode, period, exclusivity,
                confidence, review_reason_code,
            ),
        )
        candidate_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO candidate_evidence "
            "(candidate_id, page_start, source_clause, source_quote) "
            "VALUES (%s, 8, '제8조', '제8조 (권리의 부여) 본 계약에 따라...')",
            (candidate_id,),
        )
        return candidate_id

    return _make


@pytest.fixture
def make_grant(cur, ctx, make_candidate):
    """rights_grant 행을 EXCLUDE 경로로 직접 INSERT한다.

    register_candidate()를 거치지 않는다 — 이 픽스처를 쓰는 테스트가 검증하려는
    것은 판정 함수가 아니라 EXCLUDE/트리거 자체이기 때문이다.
    span 두 컬럼은 넘기지 않는다: sync_rights_grant_spans()가 채운다.
    """

    def _make(
        legal_right="TRANSMISSION",
        exploitation_mode="SVOD",
        territory="JP",
        period="[2027-01-01,2028-01-01)",
        exclusivity="exclusive",
    ):
        candidate_id = make_candidate(
            legal_right=legal_right,
            exploitation_mode=exploitation_mode,
            territory=territory,
            period=period,
            exclusivity=exclusivity,
        )
        cur.execute(
            """
            INSERT INTO rights_grant
              (contract_id, document_id, source_candidate_id, ip_id,
               territory, legal_right, exploitation_mode, period, exclusivity, verified_by)
            VALUES (%s, %s, %s, %s,
                    %s, %s, %s, %s::daterange, %s, 'tester')
            RETURNING id
            """,
            (
                ctx["contract_id"], ctx["document_id"], candidate_id,
                ctx["ip_id"], territory, legal_right, exploitation_mode, period, exclusivity,
            ),
        )
        return cur.fetchone()[0]

    return _make
