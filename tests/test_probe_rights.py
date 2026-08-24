"""validate_rights_batch() — 검증 (D-28 계승, D-30).

probe_rights()/evaluate_candidate()를 대체한다. 핵심 계약 세 가지를 확인한다.
  1. 배치가 충돌 없으면 APPLIED, 있으면 CONFLICTED를 돌려준다
  2. EXCLUDE가 실제로 터져 제약명을 받아온다 (D-08, RFP §6.3.2)
  3. 호출 후 DB에 아무것도 남지 않는다 — 호출자가 커밋해도 마찬가지다
"""

from __future__ import annotations

import json

import psycopg2
import pytest

VALIDATE = """
SELECT batch_result, constraint_name, conflict_report
FROM validate_rights_batch(%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
"""


def validate(cur, *, contract_id=None, grantor="mindex", grantee="검증용", ip_id, rights):
    cur.execute(
        VALIDATE,
        (contract_id, grantor, grantee, ip_id, "v.pdf", "s3://v/1.pdf", "sha256:v",
         json.dumps(rights)),
    )
    return cur.fetchone()


def counts(cur):
    """probe 전후 전체 행 수를 테이블별로 센다."""
    out = {}
    for table in ("ip", "content_asset", "contract", "contract_history", "rights_grant"):
        cur.execute(f"SELECT count(*) FROM {table}")
        out[table] = cur.fetchone()[0]
    return out


# ── 1. 판정 결과 ────────────────────────────────────────────────

def test_applied_when_no_existing_grant(cur, ctx, make_batch_row):
    result, constraint, report = validate(
        cur, ip_id=ctx["ip_id"], rights=[make_batch_row(territory="KR")]
    )
    assert result == "APPLIED"
    assert constraint is None
    assert report is None


def test_new_ip_validates_clean(cur, make_batch_row):
    """신규 작품(ip_id NULL)은 비교 대상이 없어 자명하게 통과한다."""
    result, _constraint, _report = validate(
        cur, ip_id=None, rights=[make_batch_row(territory="KR")]
    )
    assert result == "APPLIED"


def test_empty_batch_validates_clean(cur, ctx):
    """빈 배치는 비교할 행이 없어 자명하게 APPLIED다 (현재 계약 동작)."""
    result, _constraint, _report = validate(cur, ip_id=ctx["ip_id"], rights=[])
    assert result == "APPLIED"


# ── 2. 충돌 판정과 EXCLUDE 실검증 ──────────────────────────────

def test_conflict_reports_reason_and_constraint(cur, ctx, make_grant, make_batch_row):
    make_grant(territory="KR")  # 동일 조건 독점 권리를 먼저 등록 (ctx 소속 contract)
    result, constraint, report = validate(
        cur, ip_id=ctx["ip_id"],
        rights=[make_batch_row(territory="KR")],
    )
    assert result == "CONFLICTED"
    # D-08 · RFP §6.3.2 — 재구현한 SELECT가 아니라 진짜 제약이 잡은 이름이어야 한다
    assert constraint == "no_exclusive_overlap"
    assert report["constraint_name"] == "no_exclusive_overlap"
    assert len(report["conflicts"]) == 1
    assert report["conflicts"][0]["existing_grant_id"] is not None


def test_exclusivity_xor_caught_by_trigger(cur, ctx, make_grant, make_batch_row):
    """독점 x 비독점은 EXCLUDE가 아니라 statement 트리거가 잡는다 (D-05)."""
    make_grant(territory="KR", exclusivity="exclusive")
    _result, constraint, report = validate(
        cur, ip_id=ctx["ip_id"],
        rights=[make_batch_row(territory="KR", exclusivity="non_exclusive")],
    )
    assert constraint == "no_exclusivity_conflict"
    assert report["conflicts"][0]["blocking_layer"] == "no_exclusivity_conflict"


def test_hierarchy_overlap_caught(cur, ctx, make_grant, make_batch_row):
    """상위-하위 포함관계도 EXCLUDE가 잡는다 (D-27, JA-C05)."""
    make_grant(territory="KR", legal_right="PUBLIC_TRANSMISSION")
    result, constraint, report = validate(
        cur, ip_id=ctx["ip_id"],
        rights=[make_batch_row(territory="KR", legal_right="TRANSMISSION")],
    )
    assert result == "CONFLICTED"
    assert constraint == "no_exclusive_overlap"
    assert report["conflicts"][0]["legal_right_relation"] == "existing_is_broader"


def test_sibling_window_passes(cur, ctx, make_grant, make_batch_row):
    """형제 이용형태는 공존한다 — SVOD vs TVOD."""
    make_grant(territory="KR", exploitation_mode="SVOD")
    result, constraint, _report = validate(
        cur, ip_id=ctx["ip_id"],
        rights=[make_batch_row(territory="KR", exploitation_mode="TVOD")],
    )
    assert result == "APPLIED"
    assert constraint is None


def test_one_conflicting_row_reports_all_conflicts_in_batch(cur, ctx, make_grant, make_batch_row):
    """배치 전체 진단 — 첫 충돌 1건이 아니라 배치의 모든 충돌 행을 보고한다."""
    make_grant(territory="KR", exploitation_mode="SVOD")
    make_grant(territory="KR", exploitation_mode="AVOD")
    result, _constraint, report = validate(
        cur, ip_id=ctx["ip_id"],
        rights=[
            make_batch_row(territory="KR", exploitation_mode="SVOD"),
            make_batch_row(territory="KR", exploitation_mode="AVOD"),
        ],
    )
    assert result == "CONFLICTED"
    assert len(report["conflicts"]) == 2


# ── 3. 아무것도 남지 않는다 ────────────────────────────────────

@pytest.mark.parametrize("case", ["normal", "conflict"])
def test_validate_leaves_nothing_behind(cur, ctx, make_grant, make_batch_row, case):
    if case == "conflict":
        make_grant(territory="KR")
    before = counts(cur)
    validate(cur, ip_id=ctx["ip_id"], rights=[make_batch_row(territory="KR")])
    assert counts(cur) == before


def test_validate_survives_caller_commit(conn, cur, ctx, make_grant, make_batch_row):
    """호출자가 커밋해도 validate가 만든 행은 없다 — 롤백이 함수 안에서 끝난다."""
    make_grant(territory="KR")
    before = counts(cur)
    validate(cur, ip_id=ctx["ip_id"], rights=[make_batch_row(territory="KR")])
    conn.commit()                    # 앱이 커밋해버리는 상황을 그대로 재현
    assert counts(cur) == before

    # 이 테스트만 자기 데이터를 커밋했으므로 직접 치운다.
    cur.execute("DELETE FROM rights_grant WHERE contract_id = %s", (ctx["contract_id"],))
    cur.execute("DELETE FROM contract WHERE id = %s", (ctx["contract_id"],))
    cur.execute("DELETE FROM content_asset WHERE ip_id = %s", (ctx["ip_id"],))
    cur.execute("DELETE FROM ip WHERE id = %s", (ctx["ip_id"],))
    conn.commit()


def test_sequence_gap_is_the_only_trace(cur, ctx, make_batch_row):
    """시퀀스는 롤백해도 되돌아가지 않는다 — 알려진 유일한 부작용."""
    cur.execute("SELECT last_value FROM rights_grant_id_seq")
    before = cur.fetchone()[0]
    validate(cur, ip_id=ctx["ip_id"], rights=[make_batch_row(territory="KR")])
    cur.execute("SELECT last_value FROM rights_grant_id_seq")
    assert cur.fetchone()[0] > before


# ── 4. 근거 CHECK는 검증 단계에서도 진짜로 걸린다 ────────────────

def test_validate_rejects_blank_evidence_quote(conn, cur, ctx, make_batch_row):
    """P-3 — 원문 인용 없는 근거는 검증 단계에서도 통과하지 못한다."""
    row = make_batch_row(territory="KR", evidence={"legal_right": {"quote": ""}})
    with pytest.raises(psycopg2.errors.CheckViolation):
        validate(cur, ip_id=ctx["ip_id"], rights=[row])
    conn.rollback()
