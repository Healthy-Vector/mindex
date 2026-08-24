"""프로젝트 핵심 스모크 (신규 스키마 §3.2).

구버전(content/tenant_id/is_exclusive) 초안 테스트를 지시서 §3 스키마로 교체.
상세 케이스는 tests/test_exclude_constraint.py 참조.
"""
from __future__ import annotations

import pytest

from tests.conftest import requires_db, insert_grant

try:
    import psycopg2
except Exception:  # noqa: BLE001
    psycopg2 = None


@requires_db
def test_exclusive_overlap_is_rejected(conn, seed):
    cur = conn.cursor()
    insert_grant(cur, seed, "A", territory="JP", rights_type="SVOD",
                 period="[2024-01-01,2028-01-01)", exclusivity="exclusive")
    conn.commit()
    with pytest.raises(psycopg2.errors.ExclusionViolation):
        insert_grant(cur, seed, "B", territory="JP", rights_type="SVOD",
                     period="[2026-06-01,2029-01-01)", exclusivity="exclusive")
    conn.rollback()
