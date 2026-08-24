"""10번 GET /rights/{lineageId}/history — 권리 세대 이력 (지시서 §6 10번, 세션 필요 §4.7).

lineage_id 로 묶인 행을 created_at 오름차순. changedFields 는 서버가 직전 세대와
비교해 계산(territory, rights_type, period.start, period.end, exclusivity 다섯 개).
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

_COMPARE = ["territory", "rights_type", "period_start", "period_end", "exclusivity"]


@router.get("/rights/{lineage_id}/history", response_model=RightsHistoryResponse)
def rights_history(
    lineage_id: int,
    db: Session = Depends(get_db),
    _team: str = Depends(require_session),
) -> RightsHistoryResponse:
    rows = db.execute(
        text(
            "SELECT id, contract_id, territory, rights_type, "
            "       lower(period) AS lo, upper(period) AS hi, exclusivity, status, "
            "       created_at, terminated_at, terminated_reason "
            "FROM master.rights_grant WHERE lineage_id=:l ORDER BY created_at"
        ),
        {"l": lineage_id},
    ).mappings().all()
    if not rows:
        raise NotFound("해당 lineage 를 찾을 수 없습니다")

    gens: list[RightGeneration] = []
    prev: dict | None = None
    for r in rows:
        cur = {
            "territory": r["territory"],
            "rights_type": r["rights_type"],
            "period_start": r["lo"],
            "period_end": end_inclusive_from_upper(r["hi"]),
            "exclusivity": r["exclusivity"],
        }
        changed = (
            [] if prev is None else [k for k in _COMPARE if prev[k] != cur[k]]
        )
        gens.append(
            RightGeneration(
                rights_grant_id=r["id"], contract_id=r["contract_id"],
                territory=cur["territory"], rights_type=cur["rights_type"],
                period_start=cur["period_start"], period_end=cur["period_end"],
                exclusivity=cur["exclusivity"], status=r["status"],
                created_at=r["created_at"], terminated_at=r["terminated_at"],
                terminated_reason=r["terminated_reason"], changed_fields=changed,
            )
        )
        prev = cur

    return RightsHistoryResponse(lineage_id=lineage_id, generations=gens)
