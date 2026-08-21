"""충돌 판정 2단(EXCLUDE + 트리거) 검증 — TER-001, SFR-007.

이게 통과하면 프로젝트의 기술적 핵심(DB가 결정론적으로 충돌을 판정한다)이
검증된 것이다. D-27로 판정축이 legal_right × exploitation_mode 두 개가 됐고
둘 다 계층을 가지므로, "같은 값끼리"뿐 아니라 "상위-하위 포함관계"까지
EXCLUDE가 잡아야 한다. D-30은 candidate 스테이징을 없애고 rights_grant에
직접 INSERT하는 구조로 바뀌었을 뿐, 이 판정 자체의 비교 조건은 그대로다.

실행 전 DB가 떠 있어야 한다.
"""

from __future__ import annotations

import psycopg2
import pytest


def constraint_of(excinfo):
    """어느 층(EXCLUDE / 트리거)이 잡았는지 — D-05의 XOR 분할 확인용."""
    return excinfo.value.diag.constraint_name


_FULL_EVIDENCE_JSON = (
    '{"legal_right":{"quote":"q"},"exploitation_mode":{"quote":"q"},'
    '"territory":{"quote":"q"},"period":{"quote":"q"},"exclusivity":{"quote":"q"}}'
)


# ─────────────────────────────────────────────────────────────
# 판정축 계층 — D-27의 핵심
# ─────────────────────────────────────────────────────────────
#
# 기존/신규 모두 동일 content_asset · territory(JP) · period(겹침) · exclusive 전제.
# 서로 다른 contract에서 만들어진 두 grant다(같은 contract이면 EXCLUDE의
# contract_id WITH <> 조건에 걸려 비교 대상이 아니다 — D-30, 배치 내부
# 자기충돌 방지). 달라지는 것은 두 판정축뿐이다.
@pytest.mark.parametrize(
    "existing, incoming, blocked, why",
    [
        # 완전 동일 — 가장 기본
        (("TRANSMISSION", "SVOD"), ("TRANSMISSION", "SVOD"), True,
         "동일 권리·동일 창구"),

        # 같은 법적 권리 아래 다른 이용형태 → 공존 가능해야 한다.
        (("TRANSMISSION", "SVOD"), ("TRANSMISSION", "TVOD"), False,
         "동일 전송권이라도 SVOD와 TVOD는 다른 창구"),

        # R3 — 법적 권리의 상위-하위 포함. JA-C05(自動公衆送信 vs 전송권).
        (("PUBLIC_TRANSMISSION", "SVOD"), ("TRANSMISSION", "SVOD"), True,
         "공중송신권이 전송권을 포함"),
        (("TRANSMISSION", "SVOD"), ("PUBLIC_TRANSMISSION", "SVOD"), True,
         "반대 방향도 동일하게 잡혀야 한다"),

        # R3 — 형제 관계는 겹치지 않는다
        (("BROADCAST", "TV_LINEAR"), ("TRANSMISSION", "SVOD"), False,
         "방송권과 전송권은 형제"),

        # R4 — 이용형태의 상위-하위 포함. "all on-demand streaming" vs AVOD.
        (("TRANSMISSION", "VOD"), ("TRANSMISSION", "AVOD"), True,
         "VOD 전반이 AVOD를 포함"),
        (("TRANSMISSION", "AVOD"), ("TRANSMISSION", "VOD"), True,
         "반대 방향도 동일"),

        # R4 — 형제 창구는 겹치지 않는다
        (("TRANSMISSION", "SVOD"), ("TRANSMISSION", "AVOD"), False,
         "SVOD와 AVOD는 형제"),

        # 두 축 모두 상위인 경우
        (("PUBLIC_TRANSMISSION", "VOD"), ("TRANSMISSION", "SVOD"), True,
         "양쪽 축 모두 상위가 하위를 포함"),

        # 한 축만 겹치면 충돌이 아니다 — 두 축은 AND 조건이다
        (("PUBLIC_TRANSMISSION", "VOD"), ("TRANSMISSION", "THEATRICAL"), False,
         "권리축은 겹치지만 이용형태축이 분리"),
        (("PUBLIC_TRANSMISSION", "SVOD"), ("PUBLIC_PERFORMANCE", "SVOD"), False,
         "이용형태축은 겹치지만 권리축이 분리"),
    ],
)
def test_hierarchy_overlap(conn, cur, ctx, make_grant, existing, incoming, blocked, why):
    cur.execute("INSERT INTO contract (counterparty) VALUES ('상대2') RETURNING id")
    other_contract_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO contract_history (contract_id, version, status, file_name, file_path, file_hash) "
        "VALUES (%s, 1, 'applied', 'x.pdf', 's3://x', 'sha:x')",
        (other_contract_id,),
    )

    make_grant(legal_right=existing[0], exploitation_mode=existing[1])

    if blocked:
        with pytest.raises(psycopg2.errors.ExclusionViolation) as excinfo:
            make_grant(legal_right=incoming[0], exploitation_mode=incoming[1],
                       contract_id=other_contract_id)
        assert constraint_of(excinfo) == "no_exclusive_overlap", why
        conn.rollback()
    else:
        make_grant(legal_right=incoming[0], exploitation_mode=incoming[1],
                   contract_id=other_contract_id)  # 통과해야 한다


# ─────────────────────────────────────────────────────────────
# 나머지 판정축 — 계층 도입으로 회귀하지 않았는지
# ─────────────────────────────────────────────────────────────
def _other_contract(cur):
    cur.execute("INSERT INTO contract (counterparty) VALUES ('상대2') RETURNING id")
    contract_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO contract_history (contract_id, version, status, file_name, file_path, file_hash) "
        "VALUES (%s, 1, 'applied', 'x.pdf', 's3://x', 'sha:x')",
        (contract_id,),
    )
    return contract_id


def test_different_territory_is_allowed(cur, make_grant):
    other = _other_contract(cur)
    make_grant(territory="JP")
    make_grant(territory="KR", contract_id=other)


def test_adjacent_period_is_allowed(cur, make_grant):
    """EN-B01 — 반열림 구간이라 12/31 종료와 1/1 시작은 겹치지 않는다."""
    other = _other_contract(cur)
    make_grant(period="[2026-01-01,2027-01-01)")
    make_grant(period="[2027-01-01,2028-01-01)", contract_id=other)


def test_one_day_overlap_is_blocked(conn, cur, make_grant):
    other = _other_contract(cur)
    make_grant(period="[2026-01-01,2027-01-02)")
    with pytest.raises(psycopg2.errors.ExclusionViolation):
        make_grant(period="[2027-01-01,2028-01-01)", contract_id=other)
    conn.rollback()


def test_both_non_exclusive_is_allowed(cur, make_grant):
    """비독점끼리는 겹쳐도 정상이다 — EXCLUDE의 WHERE절이 걸러낸다."""
    other = _other_contract(cur)
    make_grant(exclusivity="non_exclusive")
    make_grant(exclusivity="non_exclusive", contract_id=other)


def test_terminated_grant_does_not_block(cur, make_grant):
    """WAIVER가 기존 권리를 TERMINATED로 정리하면 자리가 비어야 한다."""
    other = _other_contract(cur)
    grant_id = make_grant()
    cur.execute(
        "UPDATE rights_grant SET status = 'terminated', terminated_at = now(), "
        "terminated_reason = 'waiver' WHERE id = %s",
        (grant_id,),
    )
    make_grant(contract_id=other)


def test_same_contract_rows_do_not_self_conflict(cur, make_grant):
    """D-30 — contract_id WITH <>이므로 같은 계약 안의 두 행은 EXCLUDE 대상이 아니다.

    배치 INSERT 안의 신규 행끼리 서로를 충돌로 잡는 것을 막기 위한 설계다.
    """
    make_grant(exclusivity="exclusive")
    make_grant(exclusivity="exclusive")  # 같은 contract_id(ctx 기본값) — 통과해야 한다


# ─────────────────────────────────────────────────────────────
# 2단 트리거 — 독점 ↔ 비독점 XOR (D-05)
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "existing_excl, incoming_excl",
    [("exclusive", "non_exclusive"), ("non_exclusive", "exclusive"), ("sole", "non_exclusive")],
)
def test_exclusivity_xor_caught_by_trigger(conn, cur, make_grant, existing_excl, incoming_excl):
    other = _other_contract(cur)
    make_grant(exclusivity=existing_excl)
    with pytest.raises(psycopg2.errors.ExclusionViolation) as excinfo:
        make_grant(exclusivity=incoming_excl, contract_id=other)
    # EXCLUDE가 아니라 트리거가 잡아야 한다 — 담당이 XOR로 배타 분할돼 있다
    assert constraint_of(excinfo) == "no_exclusivity_conflict"
    conn.rollback()


def test_exclusivity_xor_sees_hierarchy(conn, cur, make_grant):
    """트리거의 조인 조건도 EXCLUDE와 같은 span 비교여야 한다.

    한쪽만 고치면 두 층 사이에 판정되지 않는 틈이 생긴다.
    """
    other = _other_contract(cur)
    make_grant(legal_right="PUBLIC_TRANSMISSION", exploitation_mode="VOD",
               exclusivity="exclusive")
    with pytest.raises(psycopg2.errors.ExclusionViolation) as excinfo:
        make_grant(legal_right="TRANSMISSION", exploitation_mode="SVOD",
                   exclusivity="non_exclusive", contract_id=other)
    assert constraint_of(excinfo) == "no_exclusivity_conflict"
    conn.rollback()


# ─────────────────────────────────────────────────────────────
# 비정규화 span — P-4 방어
# ─────────────────────────────────────────────────────────────
def test_span_is_derived_not_trusted(cur, ctx):
    """앱이 span을 직접 넣어도 트리거가 코드 기준으로 덮어쓴다.

    이걸 허용하면 "코드는 SVOD인데 span은 THEATRICAL"인 행을 만들 수 있고,
    그러면 EXCLUDE가 정상 동작하면서 충돌을 조용히 놓친다.
    """
    cur.execute(
        """
        INSERT INTO rights_grant
          (contract_id, contract_history_id, content_asset_id,
           territory, legal_right, exploitation_mode,
           legal_right_span, exploitation_mode_span,
           period, exclusivity, evidence)
        VALUES (%s, %s, %s,
                'JP', 'TRANSMISSION', 'SVOD',
                '[999,1000)'::int4range, '[999,1000)'::int4range,
                '[2027-01-01,2028-01-01)'::daterange, 'exclusive', %s::jsonb)
        RETURNING legal_right_span, exploitation_mode_span
        """,
        (ctx["contract_id"], ctx["history_id"], ctx["content_asset_id"], _FULL_EVIDENCE_JSON),
    )
    legal_span, mode_span = cur.fetchone()
    assert (legal_span.lower, legal_span.upper) == (4, 6), "TRANSMISSION의 실제 span"
    assert (mode_span.lower, mode_span.upper) == (2, 4), "SVOD의 실제 span"


def test_taxonomy_coordinates_are_frozen_once_data_exists(conn, cur, make_grant):
    """rights_grant 데이터가 있으면 taxonomy 좌표를 바꿀 수 없다 (D-27).

    바꿀 수 있으면 이미 저장된 span이 낡은 좌표계를 가리키게 되고,
    EXCLUDE는 그걸 알아채지 못한 채 계속 '정상 동작'한다.
    """
    make_grant()
    with pytest.raises(psycopg2.errors.RaiseException) as excinfo:
        cur.execute("UPDATE legal_right SET lft = 100, rgt = 200 WHERE code = 'TRANSMISSION'")
    assert "재초기화" in str(excinfo.value)
    conn.rollback()


def test_unknown_axis_code_is_rejected(conn, cur, ctx):
    """정의되지 않은 판정축 코드는 막힌다.

    sync_rights_grant_spans()가 BEFORE INSERT에서 span을 채우려다 먼저
    걸린다 — legal_right FK 제약보다 앞서 더 명확한 메시지로 잡는다.
    """
    with pytest.raises(psycopg2.errors.RaiseException, match="정의되지 않은 코드"):
        cur.execute(
            """
            INSERT INTO rights_grant
              (contract_id, contract_history_id, content_asset_id,
               territory, legal_right, exploitation_mode, period, exclusivity, evidence)
            VALUES (%s, %s, %s, 'JP', 'NOT_A_RIGHT', 'SVOD',
                    '[2027-01-01,2028-01-01)'::daterange, 'exclusive', %s::jsonb)
            """,
            (ctx["contract_id"], ctx["history_id"], ctx["content_asset_id"], _FULL_EVIDENCE_JSON),
        )
    conn.rollback()


def test_contract_delete_cascades_to_grant_and_history(cur, ctx, make_grant):
    """D-30 — candidate 계층이 없어져 옛 diamond cascade 우려 자체가 사라졌다.

    rights_grant.contract_id · contract_history_id 둘 다 ON DELETE CASCADE라
    계약 삭제가 grant와 history를 함께 정리한다.
    """
    grant_id = make_grant()
    cur.execute("DELETE FROM contract WHERE id = %s", (ctx["contract_id"],))
    cur.execute("SELECT count(*) FROM rights_grant WHERE id = %s", (grant_id,))
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT count(*) FROM contract_history WHERE id = %s", (ctx["history_id"],))
    assert cur.fetchone()[0] == 0
