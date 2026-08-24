"""1번 POST /auth/pin — PIN 세션 (지시서 §4.7).

- pin_hash 는 bcrypt. 평문 비교 금지.
- 토큰은 JWT(HS256, 15분). 갱신은 1분 스로틀.
- 실패 횟수 제한은 MVP 범위 밖.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.errors import InvalidPin, SessionExpired
from app.schemas.auth import PinRequest, RefreshRequest, TokenResponse
from app.services.session_store import issue_token, maybe_refresh, verify_pin
from app.services.team_context import resolve_team_id

router = APIRouter()


@router.post("/auth/pin", response_model=TokenResponse)
def auth_pin(body: PinRequest, db: Session = Depends(get_db)) -> TokenResponse:
    team_id = resolve_team_id(db, body.team_id)
    row = db.execute(
        text("SELECT pin_hash FROM master.team WHERE id=:t"), {"t": team_id}
    ).first()
    if row is None or not verify_pin(body.pin, row[0]):
        raise InvalidPin("PIN 이 올바르지 않습니다")
    token, exp = issue_token(team_id)
    return TokenResponse(token=token, expires_at=exp, team_id=team_id)


@router.post("/auth/refresh", response_model=TokenResponse)
def auth_refresh(body: RefreshRequest) -> TokenResponse:
    """1분 스로틀 재발급(§4.7·§9.4 지원). 스로틀 이내면 기존 토큰을 그대로 돌려준다."""
    refreshed = maybe_refresh(body.token)
    if refreshed is None:
        from app.services.session_store import decode_token
        from datetime import datetime, timezone

        payload = decode_token(body.token)
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        return TokenResponse(token=body.token, expires_at=exp, team_id=payload["sub"])
    token, exp = refreshed
    from app.services.session_store import decode_token

    return TokenResponse(token=token, expires_at=exp, team_id=decode_token(token)["sub"])
