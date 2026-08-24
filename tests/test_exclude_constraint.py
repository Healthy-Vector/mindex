"""§8.1 EXCLUDE 제약 자체 (E1~E7). 실 DB 필요."""
from __future__ import annotations

import pytest

from tests.conftest import requires_db, insert_grant

try:
    import psycopg2
except Exception:  # noqa: BLE001
    psycopg2 = None


@requires_db
def test_E1_exclusive_overlap_other_contract_rejected(conn, seed):
    cur = conn.cursor()
    insert_grant(cur, seed, "A")
    conn.commit()
    with pytest.raises(psycopg2.errors.ExclusionViolation):
        insert_grant(cur, seed, "B", period="[2026-06-01,2029-01-01)")
    conn.rollback()


@requires_db
def test_E2_non_exclusive_both_ok(conn, seed):
    cur = conn.cursor()
    insert_grant(cur, seed, "A", exclusivity="non_exclusive")
    insert_grant(cur, seed, "B", exclusivity="non_exclusive", period="[2026-06-01,2029-01-01)")
    conn.commit()


@requires_db
def test_E3_terminated_does_not_block(conn, seed):
    cur = conn.cursor()
    insert_grant(cur, seed, "A", status="terminated")
    insert_grant(cur, seed, "B", period="[2026-06-01,2029-01-01)")
    conn.commit()


@requires_db
def test_E4_same_contract_two_territories_ok(conn, seed):
    cur = conn.cursor()
    insert_grant(cur, seed, "A", territory="JP")
    insert_grant(cur, seed, "A", territory="SG")  # contract_id WITH <> → 자기충돌 없음
    conn.commit()


@requires_db
def test_E5_touching_but_not_overlapping_ok(conn, seed):
    cur = conn.cursor()
    insert_grant(cur, seed, "A", period="[2024-01-01,2026-07-01)")   # ~06-30
    insert_grant(cur, seed, "B", period="[2026-07-01,2029-01-01)")   # 07-01~ ([) 확인)
    conn.commit()


@requires_db
def test_E6_different_country_ok(conn, seed):
    cur = conn.cursor()
    insert_grant(cur, seed, "A", territory="JP")
    insert_grant(cur, seed, "B", territory="KR", period="[2026-06-01,2029-01-01)")
    conn.commit()


@requires_db
def test_E7_exclusive_vs_sole_rejected(conn, seed):
    cur = conn.cursor()
    insert_grant(cur, seed, "A", exclusivity="exclusive")
    conn.commit()
    with pytest.raises(psycopg2.errors.ExclusionViolation):
        insert_grant(cur, seed, "B", exclusivity="sole", period="[2026-06-01,2029-01-01)")
    conn.rollback()
