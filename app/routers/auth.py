"""1번 POST /auth/pin — PIN 세션 (P2-DB 정렬: public.team).

세션 연장은 별도 API 없이 app/deps.require_session 의 sliding expiration 으로 처리.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.config import get_settings
from app.errors import InvalidPin
from app.schemas.auth import PinRequest, TokenResponse
from app.services.session_store import issue_token, verify_pin
from app.services.team_context import resolve_team_id

router = APIRouter()


@router.post("/auth/pin", response_model=TokenResponse)
def auth_pin(body: PinRequest, db: Session = Depends(get_db)) -> TokenResponse:
    team_id = resolve_team_id(db)
    row = db.execute(text("SELECT pin_hash FROM team WHERE id=:t"), {"t": team_id}).first()
    if row is None or not verify_pin(body.pin, row[0]):
        raise InvalidPin("PIN 이 올바르지 않습니다")
    token, exp = issue_token(team_id)
    return TokenResponse(
        session_token=token,
        expires_at=exp,
        ttl_seconds=get_settings().session_ttl_minutes * 60,
    )
