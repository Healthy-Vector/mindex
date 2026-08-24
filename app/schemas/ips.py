"""IP 관리 스키마 (지시서 §6 12·13·14번)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.schemas.common import CamelModel


class AliasIn(CamelModel):
    alias_text: str
    lang: str
    alias_type: str  # OFFICIAL / ABBR / ROMANIZED / MISSPELL


class AliasOut(AliasIn):
    id: int


class IpCreate(CamelModel):
    title: str
    kind: str  # TV_OTT_SERIES / FILM / ANIMATION / MOBILE_APP / GAME_ENGINE / RELATED_ASSET
    aliases: list[AliasIn] = []


class IpPatch(CamelModel):
    title: Optional[str] = None
    kind: Optional[str] = None
    is_active: Optional[bool] = None
    aliases: Optional[list[AliasIn]] = None  # 지정되면 전체 교체(§6 14번)


class IpOut(CamelModel):
    id: int
    title: str
    kind: str
    is_active: bool
    aliases: list[AliasOut] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
