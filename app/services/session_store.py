"""PIN 세션 (지시서 §4.7).

- pin_hash 는 bcrypt. 평문 비교 금지.
- 세션 토큰은 서명된 JWT(HS256, 만료 15분). MVP 는 JWT — 공유 스토리지 불필요.
- 갱신은 1분에 한 번으로 스로틀.
- 실패 횟수 제한은 MVP 범위 밖 (넣지 않는다).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt

from app.core.config import get_settings
from app.errors import SessionExpired


def verify_pin(pin: str, pin_hash: str) -> bool:
    try:
        return bcrypt.checkpw(pin.encode("utf-8"), pin_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def hash_pin(pin: str) -> str:
    return bcrypt.hashpw(pin.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def issue_token(team_id: str) -> tuple[str, datetime]:
    """team_id 로 JWT 발급. (token, expiresAt) 반환."""
    s = get_settings()
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=s.session_ttl_minutes)
    payload = {"sub": str(team_id), "iat": int(now.timestamp()), "exp": int(exp.timestamp())}
    token = jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_alg)
    return token, exp


def decode_token(token: str) -> dict:
    """유효하면 payload, 만료·서명오류면 SESSION_EXPIRED."""
    s = get_settings()
    try:
        return jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_alg])
    except jwt.ExpiredSignatureError as ex:
        raise SessionExpired("세션이 만료되었습니다") from ex
    except jwt.InvalidTokenError as ex:
        raise SessionExpired("세션이 유효하지 않습니다") from ex
