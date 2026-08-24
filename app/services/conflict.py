"""검증·확정의 공용 로직 — 이 프로젝트의 심장 (지시서 §5).

5번(verify)과 6번(confirm)은 이 모듈의 같은 함수를 호출하고 커밋 여부만 다르다.
판정은 오직 EXCLUDE 제약이 한다 — 애플리케이션 코드로 겹침을 계산하지 않는다(§10-1).
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.services.territory import (
    end_inclusive_from_upper,
    expand_territories,
    to_daterange_literal,
)

try:  # psycopg2 / psycopg 어느 쪽이든 ExclusionViolation 을 잡는다
    from psycopg2 import errors as _pgerr
    ExclusionViolation = _pgerr.ExclusionViolation
except Exception:  # noqa: BLE001
    try:
        from psycopg import errors as _pgerr3
        ExclusionViolation = _pgerr3.ExclusionViolation
    except Exception:  # noqa: BLE001
        ExclusionViolation = None


_INSERT_SQL = text(
    """
    INSERT INTO master.rights_grant
      (team_id, contract_id, contract_history_id, content_asset_id, territory,
       rights_type, period, exclusivity, status, lineage_id,
       conditions_raw, confidence, evidence)
    VALUES
      (:team_id, :contract_id, :contract_history_id, :content_asset_id, :territory,
       :rights_type, CAST(:period AS daterange), :exclusivity, :status, :lineage_id,
       CAST(:conditions_raw AS jsonb), :confidence, CAST(:evidence AS jsonb))
    RETURNING id
    """
)

# 되돌린 뒤 같은 조건으로 상대를 다시 조회한다(§5.4). EXCLUDE 메시지는 파싱하지 않는다.
_FIND_SQL = text(
    """
    SELECT rg.id                              AS rights_grant_id,
           rg.contract_id                     AS contract_id,
           rg.exclusivity                     AS exclusivity,
           lower(rg.period)                   AS lo,
           upper(rg.period)                   AS hi,
           rg.evidence                        AS evidence,
           c.title                            AS contract_title,
           c.counterparty                     AS counterparty,
           lower(rg.period * CAST(:period AS daterange)) AS ov_lo,
           upper(rg.period * CAST(:period AS daterange)) AS ov_hi
    FROM   master.rights_grant rg
    JOIN   master.contract     c ON c.id = rg.contract_id
    WHERE  rg.status = 'active'
      AND  rg.exclusivity <> 'non_exclusive'
      AND  rg.content_asset_id = :content_asset_id
      AND  rg.territory        = :territory
      AND  rg.rights_type      = :rights_type
      AND  rg.period          && CAST(:period AS daterange)
      AND  rg.contract_id     <> :contract_id
    ORDER BY rg.created_at
    """
)


def severity(this_excl: str, other_excl: str) -> str:
    """두 행의 exclusivity 조합 → severity 코드 (지시서 §5.4)."""
    pair = {this_excl, other_excl}
    if pair == {"exclusive"}:
        return "EXCLUSIVE_VS_EXCLUSIVE"
    if pair == {"sole"}:
        return "SOLE_VS_SOLE"
    if pair == {"exclusive", "sole"}:
        return "EXCLUSIVE_VS_SOLE"
    # non_exclusive 는 충돌 대상이 아니지만 방어적으로
    return "EXCLUSIVE_VS_SOLE"


def build_rows(
    db: Session,
    rights: list,
    contract_id: int,
    history_id: int,
    team_id: str,
) -> list[dict[str, Any]]:
    """rights 1건 × territories N개 → rights_grant N행 (지시서 §5.1 §5.2).

    [) 변환은 territory.to_daterange_literal 한 곳에서만.
    """
    rows: list[dict[str, Any]] = []
    for r in rights:
        for cc in expand_territories(db, r.territories):
            rows.append(
                dict(
                    team_id=team_id,
                    contract_id=contract_id,
                    contract_history_id=history_id,
                    content_asset_id=r.content_asset_id,
                    territory=cc,
                    rights_type=r.rights_type,
                    period=to_daterange_literal(r.period.start, r.period.end),
                    exclusivity=r.exclusivity,
                    status="active",
                    lineage_id=None,
                    conditions_raw=(
                        json.dumps(r.conditions_raw, ensure_ascii=False)
                        if r.conditions_raw is not None
                        else None
                    ),
                    confidence=r.confidence,
                    evidence=(
                        json.dumps(r.evidence, ensure_ascii=False)
                        if r.evidence is not None
                        else None
                    ),
                )
            )
    return rows


def try_insert(db: Session, rows: list[dict[str, Any]]) -> tuple[bool, list[int]]:
    """EXCLUDE 통과하면 (True, new_ids) — 행은 그대로 남음.
    걸리면 (False, []) — SAVEPOINT 까지 되돌림. 커밋하지 않는다(§5.3).
    """
    sp = db.begin_nested()  # = SAVEPOINT
    try:
        new_ids: list[int] = []
        for r in rows:
            res = db.execute(_INSERT_SQL, r)
            new_ids.append(int(res.scalar_one()))
        db.flush()  # 여기서 EXCLUDE 가 터진다
    except IntegrityError as ex:
        if ExclusionViolation is None or not isinstance(ex.orig, ExclusionViolation):
            raise  # 다른 무결성 오류(FK 오타 등)는 그대로 올린다(§5.3-2)
        sp.rollback()
        return False, []
    return True, new_ids


def find_conflicts(db: Session, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """되돌린 뒤 같은 조건으로 상대를 조회해 충돌 내역을 만든다(§5.4)."""
    conflicts: list[dict[str, Any]] = []
    for r in rows:
        found = db.execute(
            _FIND_SQL,
            {
                "period": r["period"],
                "content_asset_id": r["content_asset_id"],
                "territory": r["territory"],
                "rights_type": r["rights_type"],
                "contract_id": r["contract_id"],
            },
        ).mappings().all()
        for f in found:
            ov_lo: Optional[date] = f["ov_lo"]
            ov_hi: Optional[date] = f["ov_hi"]
            days = (ov_hi - ov_lo).days if (ov_lo and ov_hi) else 0
            conflicts.append(
                {
                    "severity": severity(r["exclusivity"], f["exclusivity"]),
                    "this": {
                        "content_asset_id": r["content_asset_id"],
                        "territory": r["territory"],
                        "rights_type": r["rights_type"],
                        "period": _period_from_literal(r["period"]),
                        "exclusivity": r["exclusivity"],
                    },
                    "existing": {
                        "rights_grant_id": f["rights_grant_id"],
                        "contract_id": f["contract_id"],
                        "contract_title": f["contract_title"],
                        "counterparty": f["counterparty"],
                        "period": {
                            "start": f["lo"],
                            "end": end_inclusive_from_upper(f["hi"]),
                        },
                        "exclusivity": f["exclusivity"],
                        "evidence": f["evidence"],
                    },
                    "overlap": {
                        "start": ov_lo,
                        "end": end_inclusive_from_upper(ov_hi),
                        "days": days,
                    },
                }
            )
    return conflicts


def _period_from_literal(lit: str) -> dict[str, Any]:
    """'[start,upper)' 리터럴 → {start, end(포함)} 응답용."""
    from datetime import date as _d

    body = lit.strip()[1:-1]  # 대괄호 제거
    start_s, upper_s = body.split(",")
    start = _d.fromisoformat(start_s)
    upper = _d.fromisoformat(upper_s)
    return {"start": start, "end": end_inclusive_from_upper(upper)}


def verify_contract(db: Session, req, team_id: str) -> dict[str, Any]:
    """5번 검증 — 통과했든 걸렸든 무조건 ROLLBACK. 커밋하지 않는다(§5.5).

    mode=new 는 contract 행이 없으므로, 롤백될 바깥 트랜잭션 안에서
    임시 contract/history 를 INSERT 해 FK 를 만족시킨 뒤 전부 되돌린다.
    시퀀스 값은 되돌아가지 않으며 id 구멍은 정상(§5.5).
    """
    try:
        if req.mode in ("revision", "final") and req.contract_id:
            contract_id = req.contract_id
        else:
            contract_id = int(
                db.execute(
                    text(
                        "INSERT INTO master.contract(team_id,title,counterparty,status) "
                        "VALUES (:t,:title,:cp,'draft') RETURNING id"
                    ),
                    {
                        "t": team_id,
                        "title": req.title or "(검증용 임시)",
                        "cp": req.counterparty or "(미상)",
                    },
                ).scalar_one()
            )
        history_id = int(
            db.execute(
                text(
                    "INSERT INTO master.contract_history"
                    "(team_id,contract_id,version,status) "
                    "VALUES (:t,:c,'verify','applied') RETURNING id"
                ),
                {"t": team_id, "c": contract_id},
            ).scalar_one()
        )
        rows = build_rows(db, req.rights, contract_id, history_id, team_id)
        ok, _ids = try_insert(db, rows)
        conflicts = [] if ok else find_conflicts(db, rows)
        return {
            "has_conflict": not ok,
            "checked_rows": len(rows),
            "conflicts": conflicts,
        }
    finally:
        db.rollback()  # 통과·충돌 무관 항상 되돌림(§5.5)
