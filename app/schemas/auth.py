"""PIN 인증 스키마 (지시서 §4.7, 1번)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.schemas.common import CamelModel


class PinRequest(CamelModel):
    team_id: Optional[str] = None  # 미지정 시 MVP 단일 팀
    pin: str


class TokenResponse(CamelModel):
    token: str
    expires_at: datetime
    team_id: str


class RefreshRequest(CamelModel):
    token: str
