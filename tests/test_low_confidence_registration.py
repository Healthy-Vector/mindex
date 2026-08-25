"""낮은 confidence는 DB로 들어오지 않는다 (D-30).

D-28 시절에는 candidate.confidence < 0.85를 DB가 직접 분류해 LOW_CONFIDENCE
사유로 review 큐에 올렸다(classify_candidate()). D-30에서 candidate 스테이징
자체가 사라지면서 confidence는 DB 스키마 밖의 값이 됐다 — 신뢰도 필터링은
전적으로 앱 레이어(P5) 책임이고, save_rights_batch()/validate_rights_batch()에
넘어오는 시점에는 이미 사람이 확인했거나 임계치를 통과한 값이라는 전제다.

이 파일은 그 경계를 명시하는 짧은 계약(contract) 테스트다 — DB에 confidence를
저장할 컬럼도, 신뢰도를 이유로 등록을 막는 로직도 없다는 것만 확인한다.
"""

from __future__ import annotations

import json


def test_rights_grant_has_no_confidence_column(cur):
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'rights_grant'"
    )
    columns = {r[0] for r in cur.fetchall()}
    assert "confidence" not in columns


def test_low_confidence_reason_code_is_pure_vocabulary(cur):
    """LOW_CONFIDENCE 코드 자체는 앱 레이어 참고용으로 남지만, 이제 어떤 DB
    함수도 이 코드를 직접 산출하지 않는다 — is_blocking 같은 차단 플래그가
    없다(reason_code 테이블 자체에 그 컬럼이 없다)."""
    cur.execute("SELECT is_decision_reason FROM reason_code WHERE code = 'LOW_CONFIDENCE'")
    row = cur.fetchone()
    assert row is not None, "코드는 어휘로 남아 있어야 한다"


def test_batch_registration_does_not_require_confidence(cur, ctx, make_batch_row):
    """save_rights_batch()는 confidence 파라미터 자체를 받지 않는다 — 배치가
    등록되는 데 신뢰도 값이 관여할 자리가 구조적으로 없다."""
    cur.execute(
        """
        SELECT batch_result FROM save_rights_batch(%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        """,
        (
            ctx["contract_id"], "mindex", "테스트", ctx["ip_id"], "x.pdf", "s3://x", "sha:x",
            json.dumps([make_batch_row(territory="KR")]),
        ),
    )
    assert cur.fetchone()[0] == "APPLIED"
