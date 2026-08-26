"""10번 GET /rights/{lineageId}/history — 권리 세대 이력 (P2-DB 정렬, 세션 필요).

lineage_id 오름차순. changedFields 는 직전 세대와 비교(territory, legal_right,
exploitation_mode, period.start, period.end, exclusivity 6개).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import require_session
from app.errors import NotFound
from app.schemas.rights import RightGeneration, RightsHistoryResponse
from app.services.territory import end_inclusive_from_upper

router = APIRouter()

_COMPARE = ["territory", "legal_right", "exploitation_mode", "period_start", "period_end", "exclusivity"]


@router.get("/rights/{lineage_id}/history", response_model=RightsHistoryResponse)
def rights_history(
    lineage_id: int,
    db: Session = Depends(get_db),
    _team: str = Depends(require_session),
) -> RightsHistoryResponse:
    rows = db.execute(
        text(
            "SELECT rg.id, rg.contract_id, rg.contract_history_id, ch.version, "
            "       rg.territory, rg.legal_right, rg.exploitation_mode, "
            "       lower(rg.period) lo, upper(rg.period) hi, rg.exclusivity, rg.status, "
            "       rg.created_at, rg.terminated_at, rg.terminated_reason "
            "FROM rights_grant rg "
            "JOIN contract_history ch ON ch.id=rg.contract_history_id "
            "WHERE rg.lineage_id=:l ORDER BY rg.created_at"
        ),
        {"l": lineage_id},
    ).mappings().all()
    if not rows:
        raise NotFound("해당 lineage 를 찾을 수 없습니다")

    gens: list[RightGeneration] = []
    prev = None
    for r in rows:
        cur = {
            "territory": r["territory"], "legal_right": r["legal_right"],
            "exploitation_mode": r["exploitation_mode"], "period_start": r["lo"],
            "period_end": end_inclusive_from_upper(r["hi"]), "exclusivity": r["exclusivity"],
        }
        changed = [] if prev is None else [k for k in _COMPARE if prev[k] != cur[k]]
        gens.append(
            RightGeneration(
                rights_grant_id=r["id"], contract_id=r["contract_id"],
                contract_history_id=r["contract_history_id"], version=r["version"],
                territory=cur["territory"], legal_right=cur["legal_right"],
                exploitation_mode=cur["exploitation_mode"], period_start=cur["period_start"],
                period_end=cur["period_end"], exclusivity=cur["exclusivity"], status=r["status"],
                created_at=r["created_at"], terminated_at=r["terminated_at"],
                terminated_reason=r["terminated_reason"], changed_fields=changed,
            )
        )
        prev = cur
    return RightsHistoryResponse(lineage_id=lineage_id, generations=gens)
