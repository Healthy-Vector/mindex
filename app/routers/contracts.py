"""계약 라우터 — 5·6·7·8·9·11번 (지시서 §5 §6).

충돌은 에러가 아니다(§4.3): 5번은 200, 6번은 201 로 주고 본문에 내역을 담는다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.contracts import VerifyRequest, VerifyResponse
from app.services import conflict as conflict_svc
from app.services.team_context import resolve_team_id

router = APIRouter()


@router.post("/contracts/verify", response_model=VerifyResponse)
def verify_contract(body: VerifyRequest, db: Session = Depends(get_db)) -> VerifyResponse:
    """5번 — 충돌검사. DB 에 행을 남기지 않는다(항상 롤백). 충돌도 200(§4.3 §5.5)."""
    team_id = resolve_team_id(db)
    result = conflict_svc.verify_contract(db, body, team_id)
    return VerifyResponse.model_validate(result)
