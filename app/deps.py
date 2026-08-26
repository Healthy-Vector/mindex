"""요청 의존성 — PIN 세션 검사 + sliding expiration (지시서 §4.7, 요청 반영).

require_session 을 붙이는 엔드포인트는 8, 9, 10, 11 네 개뿐이다.
1, 4, 5, 6, 7, 12~16 은 세션 없이 동작한다.

Sliding expiration:
- Bearer 인증이 필요한 기존 API 가 호출될 때, 이 의존성이 곧 인증 미들웨어로서
  세션 만료 시각을 '요청 시각 + TTL(15분)' 로 자동 연장한다.
- 별도 연장 API 는 없다.
- 과도한 재발급/DB 갱신을 막기 위해, 실제 갱신은 세션당 최대 1분에 한 번만 수행한다
  (토큰 iat 기준 스로틀). 갱신 시 새 토큰을 응답 헤더로 내려준다:
    X-Session-Token   : 새 Bearer 토큰(이후 이 값으로 교체)
    X-Session-Expires : 새 만료 시각(ISO8601)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import Header, Response

from app.core.config import get_settings
from app.errors import SessionExpired
from app.services.session_store import decode_token, issue_token


def require_session(
    response: Response,
    authorization: Optional[str] = Header(default=None),
) -> str:
    """Authorization: Bearer <jwt> 검사 후 team_id(sub) 반환.

    유효하면 sliding expiration 을 적용한다(1분 스로틀).
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise SessionExpired("세션이 필요합니다")
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_token(token)  # 만료·서명오류면 SESSION_EXPIRED

    # --- sliding expiration (세션당 1분 스로틀) ---
    s = get_settings()
    now = int(datetime.now(timezone.utc).timestamp())
    iat = int(payload.get("iat", 0))
    if now - iat >= s.session_refresh_throttle_seconds:
        new_token, exp = issue_token(payload["sub"])  # exp = now + TTL(15분)
        response.headers["X-Session-Token"] = new_token
        response.headers["X-Session-Expires"] = exp.astimezone(timezone.utc).isoformat()

    return payload["sub"]
