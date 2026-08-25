"""PIN 인증 스키마 (지시서 §4.7, 1번)."""
from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import CamelModel


class PinRequest(CamelModel):
    # P2-DB의 team은 PIN 저장 전용이며 단일사 온프레미스 경계다.
    # 외부 API에서 teamId를 받거나 응답으로 노출하지 않는다.
    pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")


class TokenResponse(CamelModel):
    session_token: str
    expires_at: datetime
    ttl_seconds: int
