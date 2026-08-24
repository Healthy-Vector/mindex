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


# ─────────────────────────────────────────────────────────────
# 6번 확정 저장 (지시서 §5.6) — 전체가 한 트랜잭션. 순서를 바꾸지 않는다.
# ─────────────────────────────────────────────────────────────
from datetime import date as _date  # noqa: E402

from app.errors import AlreadyConfirmed, NotFound  # noqa: E402


def _json_default(o):
    if isinstance(o, _date):
        return o.isoformat()
    return str(o)


def _next_version(db: Session, contract_id: int, mode: str) -> str:
    if mode == "final":
        return "final"
    n = db.execute(
        text(
            "SELECT count(*) FROM master.contract_history "
            "WHERE contract_id=:c AND version <> 'final'"
        ),
        {"c": contract_id},
    ).scalar_one()
    return f"v{int(n) + 1}"


def _vector_literal(emb) -> Optional[str]:
    if not emb:
        return None
    return "[" + ",".join(str(float(x)) for x in emb) + "]"


def confirm_contract(db: Session, req, team_id: str) -> dict[str, Any]:
    """6번 — 확정 저장. 성공이든 충돌이든 항상 COMMIT(§5.6)."""
    tmpid = str(req.source_tmpid) if req.source_tmpid else None

    # 1. 중복 확정 차단
    if tmpid:
        dup = db.execute(
            text(
                "SELECT id, current_history_id FROM master.contract "
                "WHERE source_tmpid = :t"
            ),
            {"t": tmpid},
        ).mappings().first()
        if dup:
            db.rollback()
            raise AlreadyConfirmed(
                "이미 확정된 계약입니다",
                details={"contractId": dup["id"], "contractHistoryId": dup["current_history_id"]},
            )

    # 2. contract / history / chunk (되돌리지 않는 구간)
    if req.mode in ("revision", "final") and req.contract_id:
        contract_id = req.contract_id
        row = db.execute(
            text("SELECT status FROM master.contract WHERE id=:c"), {"c": contract_id}
        ).first()
        if row is None:
            db.rollback()
            raise NotFound("대상 계약을 찾을 수 없습니다")
        base_status = row[0]
    else:
        contract_id = int(
            db.execute(
                text(
                    "INSERT INTO master.contract"
                    "(team_id,title,contract_type,counterparty,signed_date,lang,amount,currency,"
                    " source_tmpid,status) "
                    "VALUES (:t,:title,:ctype,:cp,:sd,:lang,:amt,:cur,:tmp,'draft') RETURNING id"
                ),
                {
                    "t": team_id, "title": req.title or "(제목 미상)",
                    "ctype": req.contract_type, "cp": req.counterparty or "(미상)",
                    "sd": req.signed_date, "lang": req.lang, "amt": req.amount,
                    "cur": req.currency, "tmp": tmpid,
                },
            ).scalar_one()
        )
        base_status = "draft"

    version = _next_version(db, contract_id, req.mode)
    history_id = int(
        db.execute(
            text(
                "INSERT INTO master.contract_history"
                "(team_id,contract_id,version,status,file_path,raw_text,title,counterparty,"
                " signed_date,lang,amount,currency,parsed_at) "
                "VALUES (:t,:c,:v,'applied',:fp,:rt,:title,:cp,:sd,:lang,:amt,:cur,now()) "
                "RETURNING id"
            ),
            {
                "t": team_id, "c": contract_id, "v": version,
                "fp": req.file_path, "rt": req.raw_text, "title": req.title,
                "cp": req.counterparty, "sd": req.signed_date, "lang": req.lang,
                "amt": req.amount, "cur": req.currency,
            },
        ).scalar_one()
    )

    for ch in req.chunks:
        db.execute(
            text(
                "INSERT INTO master.contract_chunk"
                "(team_id,contract_history_id,clause_no,chunk_text,lang,page,embedding) "
                "VALUES (:t,:h,:cl,:ct,:lang,:pg,"
                + ("CAST(:emb AS vector)" if ch.embedding else ":emb")
                + ")"
            ),
            {
                "t": team_id, "h": history_id, "cl": ch.clause_no, "ct": ch.chunk_text,
                "lang": ch.lang, "pg": ch.page, "emb": _vector_literal(ch.embedding),
            },
        )

    # 3. SAVEPOINT — 이전 세대 terminated + 이번 rows 일괄 INSERT
    rows = build_rows(db, req.rights, contract_id, history_id, team_id)
    sp = db.begin_nested()
    conflicted = False
    new_ids: list[int] = []
    try:
        db.execute(
            text(
                "UPDATE master.rights_grant "
                "SET status='terminated', terminated_reason='superseded', terminated_at=now() "
                "WHERE contract_id=:c AND status='active'"
            ),
            {"c": contract_id},
        )
        for r in rows:
            new_ids.append(int(db.execute(_INSERT_SQL, r).scalar_one()))
        db.flush()  # EXCLUDE 판정
    except IntegrityError as ex:
        if ExclusionViolation is None or not isinstance(ex.orig, ExclusionViolation):
            raise
        sp.rollback()  # terminate + active insert 전부 되돌림
        conflicted = True

    conflicts: list[dict[str, Any]] = []

    if not conflicted:
        # 4-통과: lineage_id 채우기(이전 세대 승계 or 자기 id)
        for r, nid in zip(rows, new_ids):
            prev = db.execute(
                text(
                    "SELECT lineage_id FROM master.rights_grant "
                    "WHERE content_asset_id=:ca AND territory=:t AND rights_type=:rt "
                    "  AND status='terminated' AND lineage_id IS NOT NULL AND id<>:nid "
                    "ORDER BY terminated_at DESC NULLS LAST, created_at DESC LIMIT 1"
                ),
                {"ca": r["content_asset_id"], "t": r["territory"], "rt": r["rights_type"], "nid": nid},
            ).scalar()
            lin = int(prev) if prev is not None else nid
            db.execute(
                text("UPDATE master.rights_grant SET lineage_id=:l WHERE id=:nid"),
                {"l": lin, "nid": nid},
            )

        contract_status = "signed" if req.mode == "final" else base_status
        db.execute(
            text(
                "UPDATE master.contract SET current_history_id=:h, status=:st, "
                "title=COALESCE(:title,title), amount=COALESCE(:amt,amount), "
                "currency=COALESCE(:cur,currency), updated_at=now() WHERE id=:c"
            ),
            {
                "h": history_id, "st": contract_status, "title": req.title,
                "amt": req.amount, "cur": req.currency, "c": contract_id,
            },
        )
        history_status = "applied"
    else:
        # 4-위반: 상대 조회 + conflicted 재INSERT + history conflicted
        conflicts = find_conflicts(db, rows)
        new_ids = []
        for r in rows:
            cr = dict(r)
            cr["status"] = "conflicted"
            cr["lineage_id"] = None
            new_ids.append(int(db.execute(_INSERT_SQL, cr).scalar_one()))
        db.execute(
            text(
                "UPDATE master.contract_history "
                "SET status='conflicted', conflict_report=CAST(:rep AS jsonb) WHERE id=:h"
            ),
            {"rep": json.dumps(conflicts, ensure_ascii=False, default=_json_default), "h": history_id},
        )
        # contract.current_history_id 는 갱신하지 않는다. status 유지(final 도 draft 유지)
        contract_status = base_status
        history_status = "conflicted"

    # 5. staging 정리 — pdf_blob 한 줄이면 CASCADE 로 나머지 둘도 사라진다(§3.3)
    if tmpid:
        db.execute(
            text("DELETE FROM staging.pdf_blob WHERE tmpid=:t"), {"t": tmpid}
        )

    # 6. COMMIT — 성공이든 충돌이든 항상
    db.commit()

    return {
        "contract_id": contract_id,
        "contract_history_id": history_id,
        "contract_status": contract_status,
        "history_status": history_status,
        "has_conflict": conflicted,
        "rights_grant_ids": new_ids,
        "conflicts": conflicts,
    }
