"""판정 사유 파이프라인 검증 — D-27.

classify_candidate() → evaluate_candidate() → register_candidate() → WAIVER의
전체 경로에서 reason_code 마스터가 단일 코드셋으로 동작하는지 확인한다.

실행 전 `docker compose up -d`로 DB가 떠 있어야 한다.
"""

from __future__ import annotations

import psycopg2
import pytest


def evaluate(cur, candidate_id):
    cur.execute("SELECT evaluate_candidate(%s)", (candidate_id,))
    return cur.fetchone()[0]


def reasons_of(cur, candidate_id):
    """최신 판정의 사유 목록 — (code, is_primary, conflicting_grant_id)."""
    cur.execute(
        """
        SELECT r.reason_code, r.is_primary, r.conflicting_grant_id
        FROM rights_evaluation e
        JOIN rights_evaluation_reason r ON r.evaluation_id = e.id
        WHERE e.candidate_id = %s
          AND e.id = (SELECT MAX(id) FROM rights_evaluation WHERE candidate_id = %s)
        ORDER BY r.id
        """,
        (candidate_id, candidate_id),
    )
    return cur.fetchall()


def candidate_state(cur, candidate_id):
    cur.execute(
        "SELECT status, review_reason_code FROM rights_grant_candidate WHERE id = %s",
        (candidate_id,),
    )
    return cur.fetchone()


# ─────────────────────────────────────────────────────────────
# classify_candidate() — MISSING은 DB가 결정론적으로 판단한다
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "field, expected_code",
    [
        ("territory", "TERRITORY_MISSING"),
        ("period", "PERIOD_MISSING"),
        ("exclusivity", "EXCLUSIVITY_MISSING"),
        ("legal_right", "RIGHT_MISSING"),
        ("exploitation_mode", "EXPLOITATION_MODE_MISSING"),
    ],
)
def test_missing_field_gets_its_own_code(cur, make_candidate, field, expected_code):
    """D-25의 뭉뚱그린 MISSING_FIELD 대신 필드별 코드가 붙는다."""
    candidate_id = make_candidate(**{field: None})
    assert candidate_state(cur, candidate_id) == ("review", expected_code)


def test_most_severe_missing_code_wins(cur, make_candidate):
    """여러 필드가 비면 severity가 가장 높은 사유가 대표로 붙는다."""
    candidate_id = make_candidate(legal_right=None, territory=None, period=None)
    status, code = candidate_state(cur, candidate_id)
    assert (status, code) == ("review", "RIGHT_MISSING")


def test_all_missing_fields_appear_as_reasons(cur, make_candidate):
    """대표 사유는 하나지만, 무엇을 채워야 하는지는 전부 보여야 한다."""
    candidate_id = make_candidate(territory=None, period=None)
    assert evaluate(cur, candidate_id) == "REVIEW_REQUIRED"
    codes = {code for code, _, _ in reasons_of(cur, candidate_id)}
    assert {"TERRITORY_MISSING", "PERIOD_MISSING"} <= codes


def test_low_confidence_when_fields_complete(cur, make_candidate):
    candidate_id = make_candidate(confidence=0.42)
    assert candidate_state(cur, candidate_id) == ("review", "LOW_CONFIDENCE")


# ─────────────────────────────────────────────────────────────
# MISSING vs UNRESOLVED — 책임 분담
# ─────────────────────────────────────────────────────────────
def test_app_supplied_unresolved_is_not_overwritten(cur, make_candidate):
    """"Worldwide except Korea"처럼 표현은 있는데 정규화 실패한 경우.

    DB는 territory가 NULL이라는 것만 알 수 있어 TERRITORY_MISSING으로 볼 수밖에
    없다. 원문에 표현이 있었다는 사실은 추출기만 아므로, 앱이 실어 보낸
    TERRITORY_UNRESOLVED를 트리거가 존중해야 한다.
    """
    candidate_id = make_candidate(territory=None, review_reason_code="TERRITORY_UNRESOLVED")
    assert candidate_state(cur, candidate_id) == ("review", "TERRITORY_UNRESOLVED")

    assert evaluate(cur, candidate_id) == "REVIEW_REQUIRED"
    codes = {code for code, _, _ in reasons_of(cur, candidate_id)}
    assert "TERRITORY_UNRESOLVED" in codes


def test_non_review_code_is_rejected_as_review_reason(conn, cur, make_candidate):
    """is_review_trigger=false인 코드를 검토 사유로 넘기면 앱 로직 에러다."""
    with pytest.raises(psycopg2.errors.RaiseException):
        make_candidate(review_reason_code="CROSS_BORDER_MUSIC_CLEARANCE")
    conn.rollback()


def test_unknown_reason_code_is_rejected(conn, cur, make_candidate):
    """정의되지 않은 코드는 FK 이전에 classify_candidate()가 먼저 잡는다."""
    with pytest.raises(psycopg2.errors.RaiseException) as excinfo:
        make_candidate(review_reason_code="NOT_A_REAL_CODE")
    assert "검토 사유로 쓸 수 없는 코드" in str(excinfo.value)
    conn.rollback()


def test_stale_conflict_reason_does_not_resurrect(cur, make_grant, make_candidate):
    """candidate에 남은 충돌 사유가 재판정에 따라 들어오면 안 된다.

    그러면 WAIVER로 충돌 원인을 없앤 뒤에도 판정이 영영 CONFLICT로 굳는다.
    candidate.review_reason_code는 이력이지 현재 사실이 아니다.
    """
    grant_id = make_grant(territory="KR")
    candidate_id = make_candidate(territory="KR")
    assert evaluate(cur, candidate_id) == "CONFLICT"
    assert candidate_state(cur, candidate_id)[1] == "EXCLUSIVE_RIGHT_OVERLAP"

    cur.execute("UPDATE rights_grant SET status = 'terminated' WHERE id = %s", (grant_id,))
    assert evaluate(cur, candidate_id) == "NORMAL"
    # 이력은 남되 판정에는 영향을 주지 않는다 (D-25)
    assert candidate_state(cur, candidate_id) == ("extracted", "EXCLUSIVE_RIGHT_OVERLAP")


# ─────────────────────────────────────────────────────────────
# evaluate_candidate() — Result / Reason 2층
# ─────────────────────────────────────────────────────────────
def test_clean_candidate_is_normal_with_no_reasons(cur, make_candidate):
    candidate_id = make_candidate(territory="KR")
    assert evaluate(cur, candidate_id) == "NORMAL"
    assert reasons_of(cur, candidate_id) == []


def test_conflict_records_grant_and_overlap(cur, make_grant, make_candidate):
    grant_id = make_grant(territory="KR", period="[2027-01-01,2028-01-01)")
    candidate_id = make_candidate(territory="KR", period="[2027-06-01,2029-01-01)")

    assert evaluate(cur, candidate_id) == "CONFLICT"
    rows = reasons_of(cur, candidate_id)
    assert len(rows) == 1
    code, is_primary, conflicting = rows[0]
    assert (code, is_primary, conflicting) == ("EXCLUSIVE_RIGHT_OVERLAP", True, grant_id)


def test_conflict_against_two_grants_yields_two_reasons(cur, make_grant, make_candidate):
    """한 판정에 사유 N건 — 상대 grant가 다르면 행도 따로 남는다."""
    first = make_grant(territory="KR", exploitation_mode="SVOD",
                       period="[2027-01-01,2028-01-01)")
    second = make_grant(territory="KR", exploitation_mode="AVOD",
                        period="[2027-01-01,2028-01-01)")

    # VOD는 SVOD와 AVOD를 모두 포함하므로 둘 다와 부딪힌다
    candidate_id = make_candidate(territory="KR", exploitation_mode="VOD",
                                  period="[2027-06-01,2029-01-01)")
    assert evaluate(cur, candidate_id) == "CONFLICT"

    rows = reasons_of(cur, candidate_id)
    assert {r[2] for r in rows} == {first, second}
    assert sum(1 for r in rows if r[1]) == 1, "대표 사유는 정확히 하나"


def test_hierarchy_relation_is_recorded(cur, make_grant, make_candidate):
    """어느 축이 어느 방향으로 포함했는지를 화면이 설명할 수 있어야 한다."""
    make_grant(territory="KR", legal_right="PUBLIC_TRANSMISSION", exploitation_mode="VOD")
    candidate_id = make_candidate(territory="KR", legal_right="TRANSMISSION",
                                  exploitation_mode="SVOD")
    evaluate(cur, candidate_id)

    cur.execute(
        """
        SELECT r.deterministic_detail
        FROM rights_evaluation e JOIN rights_evaluation_reason r ON r.evaluation_id = e.id
        WHERE e.candidate_id = %s AND r.reason_code = 'EXCLUSIVE_RIGHT_OVERLAP'
        """,
        (candidate_id,),
    )
    detail = cur.fetchone()[0]
    assert detail["legal_right_relation"] == "existing_is_broader"
    assert detail["exploitation_mode_relation"] == "existing_is_broader"
    assert detail["blocking_layer"] == "no_exclusive_overlap"


def test_atypical_axis_combination_is_flagged(cur, make_candidate):
    """right_mapping에 없는 조합은 자동 변환하지 않고 사람에게 넘긴다 (P-1)."""
    candidate_id = make_candidate(territory="KR", legal_right="DERIVATIVE_WORK_CREATION",
                                  exploitation_mode="AUDIO_STREAMING")
    assert evaluate(cur, candidate_id) == "REVIEW_REQUIRED"
    codes = {code for code, _, _ in reasons_of(cur, candidate_id)}
    assert "AMBIGUOUS_CLAUSE" in codes


def test_advisory_becomes_warning(cur, make_candidate):
    """겨울연가·NHK 유형 — 충돌은 아니지만 확인이 필요한 업무 리스크."""
    candidate_id = make_candidate(territory="JP", legal_right="TRANSMISSION",
                                  exploitation_mode="SVOD")
    assert evaluate(cur, candidate_id) == "WARNING"
    codes = {code for code, _, _ in reasons_of(cur, candidate_id)}
    assert codes == {"CROSS_BORDER_MUSIC_CLEARANCE"}


def test_conflict_outranks_warning(cur, make_grant, make_candidate):
    """사유가 섞이면 가장 중대한 것이 판정 결과가 된다."""
    make_grant(territory="JP")
    candidate_id = make_candidate(territory="JP")
    assert evaluate(cur, candidate_id) == "CONFLICT"


# ─────────────────────────────────────────────────────────────
# register_candidate() — is_blocking이 게이트를 결정한다
# ─────────────────────────────────────────────────────────────
def test_registration_requires_at_least_one_evidence(conn, cur, make_candidate):
    candidate_id = make_candidate(territory="KR")
    cur.execute("DELETE FROM candidate_evidence WHERE candidate_id = %s", (candidate_id,))
    evaluate(cur, candidate_id)

    with pytest.raises(psycopg2.errors.RaiseException) as excinfo:
        cur.execute("SELECT register_candidate(%s, 'tester')", (candidate_id,))
    assert "인용 근거가 없어" in str(excinfo.value)
    conn.rollback()


def test_candidate_can_have_multiple_evidence_rows(cur, make_candidate):
    candidate_id = make_candidate(territory="KR")
    cur.execute(
        "INSERT INTO candidate_evidence "
        "(candidate_id, page_start, page_end, source_clause, source_quote) "
        "VALUES (%s, 12, 13, '제12조', '계약 기간과 지역에 관한 추가 근거')",
        (candidate_id,),
    )
    cur.execute("SELECT count(*) FROM candidate_evidence WHERE candidate_id = %s", (candidate_id,))
    assert cur.fetchone()[0] == 2


def test_warning_does_not_block_registration(cur, make_candidate):
    """WARNING(is_blocking=false)은 화면에 뜨되 등록을 막지 않는다."""
    candidate_id = make_candidate(territory="JP")
    assert evaluate(cur, candidate_id) == "WARNING"

    cur.execute("SELECT register_candidate(%s, 'tester')", (candidate_id,))
    assert cur.fetchone()[0] is not None
    assert candidate_state(cur, candidate_id)[0] == "approved"


def test_conflict_blocks_registration(conn, cur, make_grant, make_candidate):
    make_grant(territory="KR")
    candidate_id = make_candidate(territory="KR")
    evaluate(cur, candidate_id)

    with pytest.raises(psycopg2.errors.RaiseException) as excinfo:
        cur.execute("SELECT register_candidate(%s, 'tester')", (candidate_id,))
    assert "검토 상태" in str(excinfo.value)
    conn.rollback()


def test_registration_passes_exclude_after_re_evaluation(cur, make_grant, make_candidate):
    """충돌 상대가 사라지면 재판정으로 검토 상태가 풀리고 등록된다."""
    grant_id = make_grant(territory="KR")
    candidate_id = make_candidate(territory="KR")
    assert evaluate(cur, candidate_id) == "CONFLICT"
    assert candidate_state(cur, candidate_id)[0] == "review"

    cur.execute("UPDATE rights_grant SET status = 'terminated' WHERE id = %s", (grant_id,))
    assert evaluate(cur, candidate_id) == "NORMAL"
    assert candidate_state(cur, candidate_id)[0] == "extracted"

    cur.execute("SELECT register_candidate(%s, 'tester')", (candidate_id,))
    assert cur.fetchone()[0] is not None


# ─────────────────────────────────────────────────────────────
# WAIVER — 충돌 원인을 제거한다 (D-24)
# ─────────────────────────────────────────────────────────────
def resolution_target(cur, candidate_id):
    cur.execute(
        """
        SELECT r.id
        FROM rights_evaluation e JOIN rights_evaluation_reason r ON r.evaluation_id = e.id
        WHERE e.candidate_id = %s AND r.reason_code = 'EXCLUSIVE_RIGHT_OVERLAP'
        ORDER BY r.id DESC LIMIT 1
        """,
        (candidate_id,),
    )
    return cur.fetchone()


def test_waiver_terminates_conflicting_grant_and_logs_history(cur, make_grant, make_candidate):
    grant_id = make_grant(territory="KR")
    candidate_id = make_candidate(territory="KR")
    evaluate(cur, candidate_id)
    reason_id = resolution_target(cur, candidate_id)[0]

    cur.execute(
        "INSERT INTO conflict_resolution "
        "  (evaluation_reason_id, resolution_type, status, reason, approved_by) "
        "VALUES (%s, 'waiver', 'approved', '기존 권리자 포기 합의서 접수', 'approver')",
        (reason_id,),
    )

    cur.execute("SELECT status FROM rights_grant WHERE id = %s", (grant_id,))
    assert cur.fetchone()[0] == "terminated"

    cur.execute(
        "SELECT event_type, change_reason FROM rights_grant_history "
        "WHERE rights_grant_id = %s AND event_type = 'terminated'",
        (grant_id,),
    )
    event, change_reason = cur.fetchone()
    assert event == "terminated"
    assert change_reason.startswith("WAIVER: ")

    # 충돌 원인이 사라졌으므로 재판정 후 정상 등록된다
    assert evaluate(cur, candidate_id) == "NORMAL"
    cur.execute("SELECT register_candidate(%s, 'tester')", (candidate_id,))
    assert cur.fetchone()[0] is not None


def test_waiver_is_idempotent(cur, make_grant, make_candidate):
    grant_id = make_grant(territory="KR")
    candidate_id = make_candidate(territory="KR")
    evaluate(cur, candidate_id)
    reason_id = resolution_target(cur, candidate_id)[0]

    cur.execute(
        "INSERT INTO conflict_resolution "
        "  (evaluation_reason_id, resolution_type, status, reason, approved_by) "
        "VALUES (%s, 'waiver', 'approved', '합의', 'approver') RETURNING id",
        (reason_id,),
    )
    resolution_id = cur.fetchone()[0]

    cur.execute("UPDATE conflict_resolution SET approved_by = 'approver2' WHERE id = %s",
                (resolution_id,))

    cur.execute(
        "SELECT count(*) FROM rights_grant_history "
        "WHERE rights_grant_id = %s AND event_type = 'terminated'",
        (grant_id,),
    )
    assert cur.fetchone()[0] == 1, "이미 terminated면 0행 UPDATE라 이력이 늘지 않는다"


def test_waiver_cannot_target_non_conflict_reason(conn, cur, make_candidate):
    """REVIEW_REQUIRED·WARNING 사유에는 WAIVER를 걸 수 없다 — 포기시킬 권리가 없다."""
    candidate_id = make_candidate(territory="JP")
    evaluate(cur, candidate_id)
    cur.execute(
        """
        SELECT r.id
        FROM rights_evaluation e JOIN rights_evaluation_reason r ON r.evaluation_id = e.id
        WHERE e.candidate_id = %s ORDER BY r.id DESC LIMIT 1
        """,
        (candidate_id,),
    )
    reason_id = cur.fetchone()[0]

    with pytest.raises(psycopg2.errors.RaiseException) as excinfo:
        cur.execute(
            "INSERT INTO conflict_resolution "
            "  (evaluation_reason_id, resolution_type, status, reason) "
            "VALUES (%s, 'waiver', 'pending', '시도')",
            (reason_id,),
        )
    assert "CONFLICT가 아니라" in str(excinfo.value)
    conn.rollback()


# ─────────────────────────────────────────────────────────────
# reason_code 마스터의 무결성
# ─────────────────────────────────────────────────────────────
def test_every_constraint_name_maps_to_a_reason_code(cur):
    """DB가 던지는 제약명은 전부 사용자에게 보여줄 코드로 번역돼야 한다 (D-08)."""
    cur.execute(
        "SELECT constraint_name FROM constraint_reason_map ORDER BY constraint_name"
    )
    assert [r[0] for r in cur.fetchall()] == [
        "no_exclusive_overlap",
        "no_exclusivity_conflict",
    ]


def test_scenario_reason_codes_all_exist(cur):
    """합성데이터 시나리오 문서의 Reason Code 15종이 전부 등록돼 있어야 한다."""
    expected = {
        "EXCLUSIVE_RIGHT_OVERLAP", "CONTENT_SCOPE_OVERLAP", "AUTHORITY_SCOPE_EXCEEDED",
        "AUTHORITY_PERIOD_EXCEEDED", "UNAUTHORIZED_SUBLICENSE", "DERIVATIVE_RIGHT_OVERLAP",
        "HOLDBACK_VIOLATION", "TERRITORY_UNRESOLVED", "PERIOD_UNRESOLVED",
        "EXCLUSIVITY_UNRESOLVED", "CONTENT_IDENTITY_UNRESOLVED",
        "SUBLICENSE_CONSENT_UNVERIFIED", "DERIVATIVE_SCOPE_UNRESOLVED",
        "CROSS_BORDER_MUSIC_CLEARANCE", "PRIOR_NEGOTIATION_OBLIGATION",
    }
    cur.execute("SELECT code FROM reason_code")
    assert expected <= {r[0] for r in cur.fetchall()}
