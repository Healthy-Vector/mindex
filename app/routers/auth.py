"""1번 POST /auth/pin — PIN 세션 (지시서 §4.7).

- pin_hash 는 bcrypt. 평문 비교 금지.
- 토큰은 JWT(HS256, 15분).
- 세션 연장은 별도 API 없이 인증 의존성(app/deps.require_session)의
  sliding expiration 으로 처리한다(요청 반영). 여기엔 로그인만 둔다.
- 실패 횟수 제한은 MVP 범위 밖.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.errors import InvalidPin
from app.schemas.auth import PinRequest, TokenResponse
from app.services.session_store import issue_token, verify_pin
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
