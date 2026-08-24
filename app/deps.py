"""요청 의존성 — PIN 세션 검사 (지시서 §4.7).

require_session 을 붙이는 엔드포인트는 8, 9, 10, 11 네 개뿐이다.
1, 4, 5, 6, 7, 12~16 은 세션 없이 동작한다.
"""
from __future__ import annotations

from fastapi import Header
from typing import Optional

from app.errors import SessionExpired
from app.services.session_store import decode_token


def require_session(authorization: Optional[str] = Header(default=None)) -> str:
    """Authorization: Bearer <jwt> 를 검사하고 team_id(sub) 를 돌려준다."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise SessionExpired("세션이 필요합니다")
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_token(token)
    return payload["sub"]
