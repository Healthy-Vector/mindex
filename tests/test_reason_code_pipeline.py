"""배치 저장 파이프라인 검증 — D-30.

save_rights_batch()의 성공/실패/개정판 세대 전환/lineage 승계/WAIVER 재시도
흐름과, attempt_rights_batch_insert()의 배치 원자성, content_asset/ip_alias
자동화, contract 최종화 검증을 확인한다. candidate 스테이징이 사라지면서
옛 classify_candidate()/evaluate_candidate()/register_candidate() 테스트는
전부 이 파일에서 배치 함수 기준으로 재작성됐다.

실행 전 DB가 떠 있어야 한다.
"""

from __future__ import annotations

import json
import uuid

import psycopg2
import pytest


def save(cur, *, contract_id=None, counterparty="배치 상대방", ip_id, rights,
         file_name="batch.pdf", file_path="s3://batch/1.pdf", file_hash="sha256:batch",
         document_kind="final", source_tmpid=None):
    cur.execute(
        """
        SELECT batch_result, out_contract_id, out_history_id, constraint_name, conflict_report
        FROM save_rights_batch(
          %s, %s, %s, %s, %s, %s, %s::jsonb,
          p_document_kind => %s::contract_document_kind,
          p_source_tmpid => %s::uuid
        )
        """,
        (contract_id, counterparty, ip_id, file_name, file_path, file_hash,
         json.dumps(rights), document_kind, source_tmpid),
    )
    return cur.fetchone()


def grants_of(cur, contract_id):
    cur.execute(
        "SELECT id, status, lineage_id, territory, legal_right, exploitation_mode, period "
        "FROM rights_grant WHERE contract_id = %s ORDER BY id",
        (contract_id,),
    )
    return cur.fetchall()


def histories_of(cur, contract_id):
    cur.execute(
        "SELECT id, version, status FROM contract_history WHERE contract_id = %s ORDER BY version",
        (contract_id,),
    )
    return cur.fetchall()


# ─────────────────────────────────────────────────────────────
# save_rights_batch() — 성공 경로
# ─────────────────────────────────────────────────────────────
def test_save_registers_batch_and_signs_contract(cur, ctx, make_batch_row):
    result, _out_contract, out_history, constraint, report = save(
        cur, contract_id=ctx["contract_id"], ip_id=ctx["ip_id"],
        rights=[make_batch_row(territory="KR")],
    )
    assert result == "APPLIED"
    assert constraint is None
    assert report is None

    cur.execute("SELECT status, current_history_id FROM contract WHERE id = %s", (ctx["contract_id"],))
    status, current_history_id = cur.fetchone()
    assert status == "signed"
    assert current_history_id == out_history

    rows = grants_of(cur, ctx["contract_id"])
    assert len(rows) == 1
    assert rows[0][1] == "active"
    assert rows[0][2] == rows[0][0], "최초 등록은 자기 id가 lineage_id다"


def test_save_creates_new_contract_and_ip_when_omitted(cur, make_batch_row):
    result, out_contract, _out_history, _constraint, _report = save(
        cur, contract_id=None, ip_id=None, rights=[make_batch_row(territory="KR")],
    )
    assert result == "APPLIED"
    cur.execute("SELECT count(*) FROM contract WHERE id = %s", (out_contract,))
    assert cur.fetchone()[0] == 1


def test_save_batch_of_multiple_rights_all_succeed_together(cur, ctx, make_batch_row):
    result, _out_contract, _out_history, _constraint, _report = save(
        cur, contract_id=ctx["contract_id"], ip_id=ctx["ip_id"],
        rights=[
            make_batch_row(territory="KR", exploitation_mode="SVOD"),
            make_batch_row(territory="JP", exploitation_mode="SVOD"),
        ],
    )
    assert result == "APPLIED"
    assert len(grants_of(cur, ctx["contract_id"])) == 2


# ─────────────────────────────────────────────────────────────
# source_tmpid — D-32 (mindex_staging 비동기 파이프라인 연결)
# ─────────────────────────────────────────────────────────────
def test_save_records_source_tmpid_on_new_contract(cur, ctx, make_batch_row):
    tmpid = str(uuid.uuid4())
    result, out_contract, _out_history, _constraint, _report = save(
        cur, contract_id=None, ip_id=ctx["ip_id"],
        rights=[make_batch_row(territory="KR")],
        source_tmpid=tmpid,
    )
    assert result == "APPLIED"
    cur.execute("SELECT source_tmpid FROM contract WHERE id = %s", (out_contract,))
    assert cur.fetchone()[0] == tmpid


def test_save_records_source_tmpid_on_existing_contract(cur, ctx, make_batch_row):
    """개정판 확정도 그 확정 시도의 tmpid를 contract에 남긴다."""
    tmpid = str(uuid.uuid4())
    result, out_contract, _out_history, _constraint, _report = save(
        cur, contract_id=ctx["contract_id"], ip_id=ctx["ip_id"],
        rights=[make_batch_row(territory="KR")],
        source_tmpid=tmpid,
    )
    assert result == "APPLIED"
    cur.execute("SELECT source_tmpid FROM contract WHERE id = %s", (out_contract,))
    assert cur.fetchone()[0] == tmpid


def test_save_without_source_tmpid_leaves_column_null(cur, ctx, make_batch_row):
    """비동기 파이프라인을 안 거친 호출은 그냥 생략하면 된다."""
    result, out_contract, _out_history, _constraint, _report = save(
        cur, contract_id=None, ip_id=ctx["ip_id"],
        rights=[make_batch_row(territory="KR")],
    )
    assert result == "APPLIED"
    cur.execute("SELECT source_tmpid FROM contract WHERE id = %s", (out_contract,))
    assert cur.fetchone()[0] is None


def test_save_same_tmpid_twice_is_blocked_by_unique_constraint(cur, ctx, make_batch_row):
    """같은 tmpid로 두 번 확정하면 DB가 막는다 — 별도 DB라 이게 유일한 방어선이다."""
    tmpid = str(uuid.uuid4())
    save(
        cur, contract_id=None, ip_id=ctx["ip_id"],
        rights=[make_batch_row(territory="KR")],
        source_tmpid=tmpid,
    )

    cur.execute("INSERT INTO ip (title) VALUES ('다른 작품') RETURNING id")
    other_ip_id = cur.fetchone()[0]

    with pytest.raises(psycopg2.errors.UniqueViolation):
        save(
            cur, contract_id=None, ip_id=other_ip_id,
            rights=[make_batch_row(territory="JP")],
            source_tmpid=tmpid,
        )


def test_draft_contract_reserves_rights_without_becoming_confirmed(cur, ctx, make_batch_row):
    """contract는 draft로 남지만 active grant가 다른 계약의 등록을 선점한다."""
    result, contract_id, history_id, constraint, _report = save(
        cur,
        contract_id=None,
        ip_id=ctx["ip_id"],
        rights=[make_batch_row(territory="KR")],
        document_kind="draft",
    )
    assert result == "APPLIED"
    assert constraint is None

    cur.execute(
        "SELECT status, current_history_id FROM contract WHERE id = %s", (contract_id,)
    )
    assert cur.fetchone() == ("draft", history_id)
    assert grants_of(cur, contract_id)[0][1] == "active"

    cur.execute(
        "SELECT count(*) FROM confirmed_rights_grant WHERE contract_id = %s", (contract_id,)
    )
    assert cur.fetchone()[0] == 0

    cur.execute("INSERT INTO contract (counterparty) VALUES ('후속 상대') RETURNING id")
    other_contract_id = cur.fetchone()[0]
    conflict = save(
        cur,
        contract_id=other_contract_id,
        ip_id=ctx["ip_id"],
        rights=[make_batch_row(territory="KR")],
    )
    assert conflict[0] == "CONFLICTED"


def test_promoting_draft_exposes_existing_grants_as_confirmed(cur, ctx, make_batch_row):
    result, contract_id, _history_id, _constraint, _report = save(
        cur,
        contract_id=None,
        ip_id=ctx["ip_id"],
        rights=[make_batch_row(territory="KR")],
        document_kind="draft",
    )
    assert result == "APPLIED"

    result, *_ = save(
        cur,
        contract_id=contract_id,
        ip_id=ctx["ip_id"],
        rights=[make_batch_row(territory="KR")],
        document_kind="final",
    )
    assert result == "APPLIED"

    cur.execute("SELECT status FROM contract WHERE id = %s", (contract_id,))
    assert cur.fetchone()[0] == "signed"
    cur.execute(
        "SELECT count(*) FROM confirmed_rights_grant WHERE contract_id = %s", (contract_id,)
    )
    assert cur.fetchone()[0] == 1

    cur.execute(
        "SELECT version, document_kind, status FROM contract_history "
        "WHERE contract_id = %s ORDER BY version",
        (contract_id,),
    )
    assert cur.fetchall() == [(1, "draft", "applied"), (2, "final", "applied")]


@pytest.mark.parametrize("document_kind", ["draft", "final"])
def test_closing_contract_releases_reserved_rights(
    cur, ctx, make_batch_row, document_kind
):
    _result, contract_id, _history_id, _constraint, _report = save(
        cur,
        contract_id=None,
        ip_id=ctx["ip_id"],
        rights=[make_batch_row(territory="KR")],
        document_kind=document_kind,
    )

    cur.execute(
        "UPDATE contract SET status = 'cancelled' WHERE id = %s",
        (contract_id,),
    )
    cur.execute(
        "SELECT status, terminated_reason FROM rights_grant WHERE contract_id = %s",
        (contract_id,),
    )
    assert cur.fetchone() == ("terminated", "cancelled")

    cur.execute("INSERT INTO contract (counterparty) VALUES ('예약 승계 상대') RETURNING id")
    other_contract_id = cur.fetchone()[0]
    retry = save(
        cur,
        contract_id=other_contract_id,
        ip_id=ctx["ip_id"],
        rights=[make_batch_row(territory="KR")],
    )
    assert retry[0] == "APPLIED"


def test_cancelled_contract_is_terminal(conn, cur):
    cur.execute(
        "INSERT INTO contract (counterparty, status) VALUES ('종결 상대', 'cancelled') RETURNING id"
    )
    contract_id = cur.fetchone()[0]
    with pytest.raises(psycopg2.errors.RaiseException):
        cur.execute("UPDATE contract SET status = 'draft' WHERE id = %s", (contract_id,))
    conn.rollback()


# ─────────────────────────────────────────────────────────────
# save_rights_batch() — 실패(충돌) 경로
# ─────────────────────────────────────────────────────────────
def test_save_conflict_records_report_and_leaves_contract_untouched(cur, ctx, make_grant, make_batch_row):
    make_grant(territory="KR")  # ctx 소속 contract에 기존 독점권

    cur.execute("INSERT INTO contract (counterparty) VALUES ('신규 상대') RETURNING id")
    new_contract_id = cur.fetchone()[0]

    result, _out_contract, _out_history, constraint, report = save(
        cur, contract_id=new_contract_id, ip_id=ctx["ip_id"],
        rights=[make_batch_row(territory="KR")],
    )
    assert result == "CONFLICTED"
    assert constraint == "no_exclusive_overlap"
    assert len(report["conflicts"]) == 1

    # 충돌한 계약 자체는 draft 그대로 — current_history_id도 안 바뀐다
    cur.execute("SELECT status, current_history_id FROM contract WHERE id = %s", (new_contract_id,))
    assert cur.fetchone() == ("draft", None)

    # 그래도 이 시도는 conflicted 세대로 남는다 — "충돌 건은 처리 대상으로 커밋한다"
    hist = histories_of(cur, new_contract_id)
    assert len(hist) == 1
    assert hist[0][2] == "conflicted"

    # rights_grant에는 아무 행도 안 남는다
    assert grants_of(cur, new_contract_id) == []


def test_save_conflict_does_not_disturb_existing_grant(cur, ctx, make_grant, make_batch_row):
    grant_id = make_grant(territory="KR")
    cur.execute("INSERT INTO contract (counterparty) VALUES ('신규 상대') RETURNING id")
    new_contract_id = cur.fetchone()[0]

    save(cur, contract_id=new_contract_id, ip_id=ctx["ip_id"], rights=[make_batch_row(territory="KR")])

    cur.execute("SELECT status FROM rights_grant WHERE id = %s", (grant_id,))
    assert cur.fetchone()[0] == "active"


# ─────────────────────────────────────────────────────────────
# 배치 원자성 — attempt_rights_batch_insert() (D-30, §6 신규 영역)
# ─────────────────────────────────────────────────────────────
def test_batch_is_all_or_nothing_on_partial_conflict(cur, ctx, make_grant, make_batch_row):
    """배치 2건 중 1건만 충돌해도 전체가 롤백돼야 한다 — all-or-nothing."""
    make_grant(territory="KR", exploitation_mode="SVOD")  # 이것과만 충돌한다

    cur.execute("INSERT INTO contract (counterparty) VALUES ('신규 상대') RETURNING id")
    new_contract_id = cur.fetchone()[0]

    result, _out_contract, _out_history, _constraint, _report = save(
        cur, contract_id=new_contract_id, ip_id=ctx["ip_id"],
        rights=[
            make_batch_row(territory="JP", exploitation_mode="SVOD"),   # 충돌 없음
            make_batch_row(territory="KR", exploitation_mode="SVOD"),   # 충돌
        ],
    )
    assert result == "CONFLICTED"
    # 충돌 없던 JP 행도 같이 롤백돼 하나도 등록되지 않아야 한다
    assert grants_of(cur, new_contract_id) == []


# ─────────────────────────────────────────────────────────────
# 개정판 세대 전환 + lineage_id 승계 (D-30, §6 신규 영역)
# ─────────────────────────────────────────────────────────────
def test_new_generation_supersedes_previous_and_inherits_lineage(cur, ctx, make_batch_row):
    # ctx["contract_id"]는 픽스처가 이미 history version=1(placeholder)을
    # 만들어 뒀으므로(make_grant용), 버전 카운트가 깨끗한 새 계약을 쓴다.
    cur.execute("INSERT INTO contract (counterparty) VALUES ('개정판 상대') RETURNING id")
    contract_id = cur.fetchone()[0]

    r1 = save(cur, contract_id=contract_id, ip_id=ctx["ip_id"],
              rights=[make_batch_row(territory="KR", period="[2027-01-01,2028-01-01)")])
    assert r1[0] == "APPLIED"
    first_grant_id = grants_of(cur, contract_id)[0][0]

    r2 = save(cur, contract_id=contract_id, ip_id=ctx["ip_id"],
              rights=[make_batch_row(territory="KR", period="[2027-01-01,2029-01-01)")])
    assert r2[0] == "APPLIED"

    rows = grants_of(cur, contract_id)
    assert len(rows) == 2
    old_row = next(r for r in rows if r[0] == first_grant_id)
    new_row = next(r for r in rows if r[0] != first_grant_id)

    assert old_row[1] == "terminated"
    assert new_row[1] == "active"
    assert new_row[2] == old_row[2], "자연키가 일치하면 lineage_id를 승계한다"

    cur.execute("SELECT terminated_reason FROM rights_grant WHERE id = %s", (first_grant_id,))
    assert cur.fetchone()[0] == "superseded"

    hist = histories_of(cur, contract_id)
    assert [h[2] for h in hist] == ["applied", "applied"]


def test_new_generation_with_no_natural_key_match_starts_new_lineage(cur, ctx, make_batch_row):
    save(cur, contract_id=ctx["contract_id"], ip_id=ctx["ip_id"],
         rights=[make_batch_row(territory="KR", exploitation_mode="SVOD")])

    save(cur, contract_id=ctx["contract_id"], ip_id=ctx["ip_id"],
         rights=[make_batch_row(territory="JP", exploitation_mode="AVOD")])  # 다른 자연키

    rows = grants_of(cur, ctx["contract_id"])
    active = [r for r in rows if r[1] == "active"]
    assert len(active) == 1
    assert active[0][2] == active[0][0], "매칭 실패 시 자기 id로 새 lineage가 시작된다"


def test_ambiguous_natural_key_match_starts_new_lineage(cur, ctx, make_batch_row):
    """이전 세대에 같은 자연키 행이 2건(모호)이면 lineage를 승계하지 않는다.

    EXCLUDE는 exclusivity<>'non_exclusive'일 때만 걸리므로, 두 비독점 행은
    같은 자연키·겹치는 기간이어도 공존할 수 있다 — 모호 케이스를 이렇게 만든다.
    """
    save(cur, contract_id=ctx["contract_id"], ip_id=ctx["ip_id"],
         rights=[
             make_batch_row(territory="KR", period="[2027-01-01,2028-01-01)", exclusivity="non_exclusive"),
             make_batch_row(territory="KR", period="[2027-06-01,2029-01-01)", exclusivity="non_exclusive"),
         ])
    assert len(grants_of(cur, ctx["contract_id"])) == 2

    save(cur, contract_id=ctx["contract_id"], ip_id=ctx["ip_id"],
         rights=[make_batch_row(territory="KR", period="[2030-01-01,2031-01-01)", exclusivity="non_exclusive")])

    rows = grants_of(cur, ctx["contract_id"])
    active = [r for r in rows if r[1] == "active"]
    assert len(active) == 1
    assert active[0][2] == active[0][0], "모호하면 승계하지 않고 새 lineage로 시작한다"


# ─────────────────────────────────────────────────────────────
# WAIVER — terminate_rights_grant() 직접 호출 (D-30, §5)
# ─────────────────────────────────────────────────────────────
def test_waiver_then_resave_succeeds(cur, ctx, make_grant, make_batch_row):
    grant_id = make_grant(territory="KR")
    cur.execute("INSERT INTO contract (counterparty) VALUES ('신규 상대') RETURNING id")
    new_contract_id = cur.fetchone()[0]

    result, *_ = save(cur, contract_id=new_contract_id, ip_id=ctx["ip_id"],
                       rights=[make_batch_row(territory="KR")])
    assert result == "CONFLICTED"

    cur.execute("SELECT terminate_rights_grant(%s, 'waiver', %s)", (grant_id, "포기 합의서 접수"))
    cur.execute("SELECT status, terminated_reason FROM rights_grant WHERE id = %s", (grant_id,))
    assert cur.fetchone() == ("terminated", "waiver")

    result2, *_ = save(cur, contract_id=new_contract_id, ip_id=ctx["ip_id"],
                        rights=[make_batch_row(territory="KR")])
    assert result2 == "APPLIED"


def test_terminate_rejects_non_waiver_reason(conn, cur, make_grant):
    grant_id = make_grant()
    with pytest.raises(psycopg2.errors.RaiseException) as excinfo:
        cur.execute("SELECT terminate_rights_grant(%s, 'expired')", (grant_id,))
    assert "waiver 또는 cancelled" in str(excinfo.value)
    conn.rollback()


def test_terminate_rejects_already_terminated(conn, cur, make_grant):
    grant_id = make_grant()
    cur.execute("SELECT terminate_rights_grant(%s, 'cancelled')", (grant_id,))
    with pytest.raises(psycopg2.errors.RaiseException) as excinfo:
        cur.execute("SELECT terminate_rights_grant(%s, 'cancelled')", (grant_id,))
    assert "이미 종료됐거나" in str(excinfo.value)
    conn.rollback()


# ─────────────────────────────────────────────────────────────
# content_asset 자동 생성 (D-30, §1.2)
# ─────────────────────────────────────────────────────────────
def test_ip_insert_creates_default_content_asset(cur):
    cur.execute("INSERT INTO ip (title, kind) VALUES ('새 작품', '드라마') RETURNING id")
    ip_id = cur.fetchone()[0]
    cur.execute(
        "SELECT scope_type, asset_type, title FROM content_asset WHERE ip_id = %s", (ip_id,)
    )
    scope_type, asset_type, title = cur.fetchone()
    assert (scope_type, asset_type, title) == ("SERIES_ALL", "MAIN", "새 작품")


# ─────────────────────────────────────────────────────────────
# ip_alias UNIQUE (D-30, §1.1)
# ─────────────────────────────────────────────────────────────
def test_ip_alias_unique_constraint(conn, cur, ctx):
    cur.execute(
        "INSERT INTO ip_alias (ip_id, alias_text, lang) VALUES (%s, '겨울연가', 'ko')",
        (ctx["ip_id"],),
    )
    with pytest.raises(psycopg2.errors.UniqueViolation):
        cur.execute(
            "INSERT INTO ip_alias (ip_id, alias_text, lang) VALUES (%s, '겨울연가', 'ko')",
            (ctx["ip_id"],),
        )
    conn.rollback()


# ─────────────────────────────────────────────────────────────
# contract 서명 완료 검증 (D-31)
# ─────────────────────────────────────────────────────────────
def test_signing_rejects_applied_draft_history(conn, cur, ctx, make_batch_row):
    save(cur, contract_id=ctx["contract_id"], ip_id=ctx["ip_id"],
         rights=[make_batch_row(territory="KR")], document_kind="draft")
    with pytest.raises(psycopg2.errors.RaiseException) as excinfo:
        cur.execute("UPDATE contract SET status = 'signed' WHERE id = %s", (ctx["contract_id"],))
    assert "final 문서가 아니다" in str(excinfo.value)
    conn.rollback()


def test_signing_rejects_history_from_other_contract(conn, cur, ctx, make_batch_row):
    save(cur, contract_id=ctx["contract_id"], ip_id=ctx["ip_id"], rights=[make_batch_row(territory="KR")])
    cur.execute("SELECT current_history_id FROM contract WHERE id = %s", (ctx["contract_id"],))
    other_history_id = cur.fetchone()[0]

    cur.execute("INSERT INTO contract (counterparty, status) VALUES ('다른 계약', 'draft') RETURNING id")
    victim_id = cur.fetchone()[0]
    cur.execute("UPDATE contract SET current_history_id = %s WHERE id = %s", (other_history_id, victim_id))

    with pytest.raises(psycopg2.errors.RaiseException) as excinfo:
        cur.execute("UPDATE contract SET status = 'signed' WHERE id = %s", (victim_id,))
    assert "이 계약" in str(excinfo.value)
    conn.rollback()


def test_signing_rejects_conflicted_history(conn, cur, ctx, make_grant, make_batch_row):
    make_grant(territory="KR")
    cur.execute("INSERT INTO contract (counterparty) VALUES ('충돌 계약') RETURNING id")
    conflicted_contract_id = cur.fetchone()[0]
    save(cur, contract_id=conflicted_contract_id, ip_id=ctx["ip_id"], rights=[make_batch_row(territory="KR")])

    cur.execute(
        "SELECT id FROM contract_history WHERE contract_id = %s ORDER BY id DESC LIMIT 1",
        (conflicted_contract_id,),
    )
    conflicted_history_id = cur.fetchone()[0]
    cur.execute(
        "UPDATE contract SET current_history_id = %s WHERE id = %s",
        (conflicted_history_id, conflicted_contract_id),
    )
    with pytest.raises(psycopg2.errors.RaiseException) as excinfo:
        cur.execute("UPDATE contract SET status = 'signed' WHERE id = %s", (conflicted_contract_id,))
    assert "applied 상태가 아니다" in str(excinfo.value)
    conn.rollback()


# ─────────────────────────────────────────────────────────────
# reason_code 마스터의 무결성 (D-30, 축소)
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


def test_reason_code_no_longer_drives_workflow(cur):
    """D-30 — is_blocking/is_review_trigger 컬럼이 삭제됐다. 이제 순수 어휘다."""
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'reason_code'"
    )
    columns = {r[0] for r in cur.fetchall()}
    assert "is_blocking" not in columns
    assert "is_review_trigger" not in columns
    assert "is_decision_reason" in columns
