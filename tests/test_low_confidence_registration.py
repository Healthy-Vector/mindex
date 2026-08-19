"""LOW_CONFIDENCE가 등록을 막지 않는다 (D-28).

`is_blocking=true`이던 시절에는 사람이 이미 검수한 후보가 영영 등록되지 못했다.
register_candidate()가 review 상태를 거부하고, evaluate_candidate()는 이 사유를
매번 다시 옮겨 review로 되돌리며, 해제 수단인 rights_evaluation_reason.status
='resolved'는 세팅하는 코드가 없었다(O-09). 이 테스트가 그 회귀를 잡는다.
"""

from __future__ import annotations


def test_low_confidence_still_flags_review(cur, make_candidate):
    """분류 자체는 그대로다 — 화면이 '신뢰도 낮음'을 표시할 근거는 남는다."""
    candidate_id = make_candidate(confidence=0.42)
    cur.execute(
        "SELECT status, review_reason_code FROM rights_grant_candidate WHERE id = %s",
        (candidate_id,),
    )
    assert cur.fetchone() == ("review", "LOW_CONFIDENCE")


def test_low_confidence_is_not_blocking(cur):
    cur.execute("SELECT is_blocking FROM reason_code WHERE code = 'LOW_CONFIDENCE'")
    assert cur.fetchone()[0] is False


def test_low_confidence_candidate_can_be_registered(cur, make_candidate):
    """재판정하면 검토 상태를 벗어나고 등록까지 간다."""
    candidate_id = make_candidate(confidence=0.42)

    cur.execute("SELECT evaluate_candidate(%s)", (candidate_id,))
    cur.execute("SELECT status FROM rights_grant_candidate WHERE id = %s", (candidate_id,))
    assert cur.fetchone()[0] == "extracted", "blocking 사유가 없으면 검토 큐에서 빠져야 한다"

    cur.execute("SELECT register_candidate(%s, 'reviewer@test')", (candidate_id,))
    grant_id = cur.fetchone()[0]
    assert grant_id is not None

    cur.execute("SELECT status FROM rights_grant WHERE id = %s", (grant_id,))
    assert cur.fetchone()[0] == "approved"


def test_low_confidence_reason_survives_in_evaluation(cur, make_candidate):
    """등록을 막지는 않지만 판정 사유로는 남는다 — 왜 검토가 필요했는지의 이력."""
    candidate_id = make_candidate(confidence=0.42)
    cur.execute("SELECT evaluate_candidate(%s)", (candidate_id,))
    cur.execute(
        """
        SELECT r.reason_code
        FROM rights_evaluation e
        JOIN rights_evaluation_reason r ON r.evaluation_id = e.id
        WHERE e.candidate_id = %s
        """,
        (candidate_id,),
    )
    assert "LOW_CONFIDENCE" in {row[0] for row in cur.fetchall()}
