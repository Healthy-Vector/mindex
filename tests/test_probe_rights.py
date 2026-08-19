"""probe_rights() — 검증 probe (D-28).

핵심 계약 세 가지를 확인한다.
  1. 판정 결과와 사유를 evaluate_candidate()와 동일하게 돌려준다
  2. EXCLUDE가 실제로 터져 제약명을 받아온다 (D-08, RFP §6.3.2)
  3. 호출 후 DB에 아무것도 남지 않는다 — 호출자가 커밋해도 마찬가지다
"""

from __future__ import annotations

import json

import psycopg2
import pytest

PROBE = """
SELECT result_type, reason_code, is_primary,
       conflicting_grant_id, overlap_period, detail, constraint_name
FROM probe_rights(%s, %s, %s, %s, %s::daterange, %s)
"""

# 기본 후보값은 conftest의 make_candidate와 같다 (JP/TRANSMISSION/SVOD/2027/exclusive).
DEFAULT = ("JP", "TRANSMISSION", "SVOD", "[2027-01-01,2028-01-01)", "exclusive")


def probe(cur, ctx, *, ip_id=..., **kw):
    territory, legal_right, mode, period, exclusivity = DEFAULT
    args = {
        "territory": territory, "legal_right": legal_right,
        "exploitation_mode": mode, "period": period, "exclusivity": exclusivity,
    }
    args.update(kw)
    cur.execute(
        PROBE,
        (
            ctx["ip_id"] if ip_id is ... else ip_id,
            args["territory"], args["legal_right"], args["exploitation_mode"],
            args["period"], args["exclusivity"],
        ),
    )
    return cur.fetchall()


def counts(cur):
    """probe 전후 전체 행 수를 테이블별로 센다."""
    out = {}
    for table in (
        "ip", "contract", "contract_document", "rights_grant_candidate", "candidate_evidence",
        "rights_evaluation", "rights_evaluation_reason", "rights_grant",
    ):
        cur.execute(f"SELECT count(*) FROM {table}")
        out[table] = cur.fetchone()[0]
    return out


# ── 1. 판정 결과 ────────────────────────────────────────────────

def test_normal_when_no_existing_grant(cur, ctx):
    # KR을 쓴다 — JP+TRANSMISSION+SVOD에는 right_mapping advisory가 붙어 있어
    # 충돌이 없어도 WARNING이 나온다(아래 test_advisory_is_warning_not_conflict).
    rows = probe(cur, ctx, territory="KR")
    assert len(rows) == 1
    assert rows[0][0] == "NORMAL"
    assert rows[0][1] is None          # 사유 없음
    assert rows[0][6] is None          # 제약 위반 없음


def test_new_ip_probes_clean(cur, ctx):
    """신규 작품(ip_id NULL)은 비교 대상이 없어 자명하게 통과한다."""
    rows = probe(cur, ctx, ip_id=None, territory="KR")
    assert rows[0][0] == "NORMAL"


def test_advisory_is_warning_not_conflict(cur, ctx):
    """자문 경고는 업무 리스크이지 권리 충돌이 아니다 — 등록을 막지 않는다."""
    rows = probe(cur, ctx, territory="JP")      # JP+TRANSMISSION+SVOD advisory
    assert rows[0][0] == "WARNING"
    assert rows[0][6] is None                   # 제약은 안 걸렸다


def test_missing_field_reported(cur, ctx):
    rows = probe(cur, ctx, territory=None)
    assert rows[0][0] == "REVIEW_REQUIRED"
    assert "TERRITORY_MISSING" in {r[1] for r in rows}


def test_probe_accepts_multiple_evidence_rows(cur, ctx):
    evidence = [
        {"page_start": 3, "source_clause": "제3조", "source_quote": "권리 범위 근거"},
        {"page_start": 8, "page_end": 9, "source_clause": "제8조", "source_quote": "기간 근거"},
    ]
    cur.execute(
        "SELECT result_type FROM probe_rights(%s, %s, %s, %s, %s::daterange, %s, %s, %s::jsonb)",
        (ctx["ip_id"], "KR", "TRANSMISSION", "SVOD",
         "[2027-01-01,2028-01-01)", "exclusive", 0.99, json.dumps(evidence)),
    )
    assert cur.fetchone()[0] == "NORMAL"


def test_probe_rejects_empty_evidence(cur, ctx):
    with pytest.raises(psycopg2.errors.RaiseException, match="evidence 배열이 한 건 이상"):
        cur.execute(
            "SELECT * FROM probe_rights(%s, %s, %s, %s, %s::daterange, %s, %s, %s::jsonb)",
            (ctx["ip_id"], "KR", "TRANSMISSION", "SVOD",
             "[2027-01-01,2028-01-01)", "exclusive", 0.99, "[]"),
        )


# ── 2. 충돌 판정과 EXCLUDE 실검증 ──────────────────────────────

def test_conflict_reports_reason_and_constraint(cur, ctx, make_grant):
    make_grant()                                   # 동일 조건 독점 권리를 먼저 등록
    rows = probe(cur, ctx)

    assert rows[0][0] == "CONFLICT"
    assert "EXCLUSIVE_RIGHT_OVERLAP" in {r[1] for r in rows}

    # D-08 · RFP §6.3.2 — 재구현한 SELECT가 아니라 진짜 제약이 잡은 이름이어야 한다
    assert rows[0][6] == "no_exclusive_overlap"


def test_exclusivity_xor_caught_by_trigger(cur, ctx, make_grant):
    """독점 x 비독점은 EXCLUDE가 아니라 statement 트리거가 잡는다 (D-05)."""
    make_grant(exclusivity="exclusive")
    rows = probe(cur, ctx, exclusivity="non_exclusive")
    assert rows[0][6] == "no_exclusivity_conflict"


def test_hierarchy_overlap_caught(cur, ctx, make_grant):
    """상위-하위 포함관계도 EXCLUDE가 잡는다 (D-27, JA-C05)."""
    make_grant(legal_right="PUBLIC_TRANSMISSION")
    rows = probe(cur, ctx, legal_right="TRANSMISSION")
    assert rows[0][0] == "CONFLICT"
    assert rows[0][6] == "no_exclusive_overlap"


def test_sibling_window_passes(cur, ctx, make_grant):
    """형제 이용형태는 공존한다 — SVOD vs TVOD."""
    make_grant(exploitation_mode="SVOD")
    rows = probe(cur, ctx, exploitation_mode="TVOD")
    assert rows[0][0] == "NORMAL"
    assert rows[0][6] is None


# ── 3. 아무것도 남지 않는다 ────────────────────────────────────

@pytest.mark.parametrize("case", ["normal", "conflict"])
def test_probe_leaves_nothing_behind(cur, ctx, make_grant, case):
    if case == "conflict":
        make_grant()
    before = counts(cur)
    probe(cur, ctx)
    assert counts(cur) == before


def test_probe_survives_caller_commit(conn, cur, ctx, make_grant):
    """호출자가 커밋해도 probe가 만든 행은 없다 — 롤백이 함수 안에서 끝난다."""
    make_grant()
    before = counts(cur)
    probe(cur, ctx)
    conn.commit()                    # 앱이 커밋해버리는 상황을 그대로 재현
    assert counts(cur) == before

    # 이 테스트만 자기 데이터를 커밋했으므로 직접 치운다 (conftest의 rollback으로는 안 지워진다).
    # contract 삭제가 document → candidate/grant/history까지 CASCADE로 끌고 간다.
    cur.execute("DELETE FROM rights_grant WHERE contract_id = %s", (ctx["contract_id"],))
    cur.execute("DELETE FROM contract WHERE id = %s", (ctx["contract_id"],))
    cur.execute("DELETE FROM ip WHERE id = %s", (ctx["ip_id"],))
    conn.commit()


def test_sequence_gap_is_the_only_trace(cur, ctx):
    """시퀀스는 롤백해도 되돌아가지 않는다 — 알려진 유일한 부작용."""
    cur.execute("SELECT last_value FROM rights_grant_candidate_id_seq")
    before = cur.fetchone()[0]
    probe(cur, ctx)
    cur.execute("SELECT last_value FROM rights_grant_candidate_id_seq")
    assert cur.fetchone()[0] > before
