"""IP 관리 스키마 (P2-DB 정렬: team_id 없음, activity enum)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.schemas.common import CamelModel


class AliasIn(CamelModel):
    alias_text: str
    lang: Optional[str] = None
    alias_type: str = "title"  # title / OFFICIAL / ABBR / ROMANIZED / MISSPELL 등


class AliasOut(AliasIn):
    id: int


class IpCreate(CamelModel):
    title: str
    kind: Optional[str] = None  # '드라마' · '영화'
    aliases: list[AliasIn] = []


class IpPatch(CamelModel):
    title: Optional[str] = None
    kind: Optional[str] = None
    activity: Optional[str] = None  # 'active' | 'deactive'
    aliases: Optional[list[AliasIn]] = None  # 지정되면 전체 교체


class IpOut(CamelModel):
    id: int
    title: str
    kind: Optional[str] = None
    activity: str
    aliases: list[AliasOut] = []
    created_at: Optional[datetime] = None
