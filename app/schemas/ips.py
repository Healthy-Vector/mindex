"""IP 관리 스키마 (P2-DB 정렬: team_id 없음, activity enum)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import Field, model_validator

from app.schemas.common import CamelModel


class AliasIn(CamelModel):
    text: str
    lang: Optional[str] = None
    alias_type: str = "title"  # title / OFFICIAL / ABBR / ROMANIZED / MISSPELL 등


class AliasOut(AliasIn):
    id: int


class AssetIn(CamelModel):
    scope_type: Literal["SERIES_ALL", "SEASON", "EPISODE", "EDITION"] = "SERIES_ALL"
    title: Optional[str] = None
    asset_type: str = "MAIN"
    season_no: Optional[int] = None
    episode_no: Optional[int] = None
    edition_code: Optional[str] = None

    @model_validator(mode="after")
    def scope_fields_match(self) -> "AssetIn":
        if self.season_no is not None and self.scope_type not in {"SEASON", "EPISODE"}:
            raise ValueError("seasonNo는 SEASON 또는 EPISODE 자산에만 사용할 수 있습니다")
        if self.episode_no is not None and self.scope_type != "EPISODE":
            raise ValueError("episodeNo는 EPISODE 자산에만 사용할 수 있습니다")
        if self.edition_code is not None and self.scope_type != "EDITION":
            raise ValueError("editionCode는 EDITION 자산에만 사용할 수 있습니다")
        return self


class AssetOut(AssetIn):
    content_asset_id: int


class IpCreate(CamelModel):
    title: str
    kind: Optional[str] = None  # '드라마' · '영화'
    aliases: list[AliasIn] = Field(default_factory=list)
    # 생략하면 P2 트리거가 SERIES_ALL 한 행을 만든다. 지정하면 전체 초기 목록이다.
    assets: Optional[list[AssetIn]] = Field(default=None, min_length=1)


class IpPatch(CamelModel):
    title: Optional[str] = None
    kind: Optional[str] = None
    activity: Optional[Literal["active", "deactive"]] = None
    aliases: Optional[list[AliasIn]] = None  # 지정되면 전체 교체


class IpOut(CamelModel):
    ip_id: int
    title: str
    kind: Optional[str] = None
    activity: str
    aliases: list[AliasOut] = Field(default_factory=list)
    assets: list[AssetOut] = Field(default_factory=list)
    contract_count: int = 0
    created_at: Optional[datetime] = None
