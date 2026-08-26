"""IP 관리 스키마 (P2-DB 정렬: team_id 없음, activity enum)."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, Optional

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


class AssetPatch(CamelModel):
    """18번 자산 부분 수정. 보낸 필드만 반영하고, 명시적 null 은 값을 비운다.

    scope 정합성을 여기서 단독으로 검증하지 않는다 — 부분 수정이라 기존 행과
    합쳐야 판단할 수 있다. 예를 들어 scopeType 만 EPISODE → SERIES_ALL 로 바꾸면
    기존 seasonNo/episodeNo 가 남아 DB CHECK(content_asset_season_scope 등)에
    걸린다. merged_with() 로 병합한 뒤 AssetIn 의 규칙을 그대로 태운다.
    """

    scope_type: Optional[Literal["SERIES_ALL", "SEASON", "EPISODE", "EDITION"]] = None
    title: Optional[str] = None
    asset_type: Optional[str] = None
    season_no: Optional[int] = None
    episode_no: Optional[int] = None
    edition_code: Optional[str] = None

    def merged_with(self, current: Mapping[str, Any]) -> AssetIn:
        """기존 행(snake_case 매핑)에 이번 변경을 얹어 최종 상태를 만든다.

        정합성 위반이면 pydantic ValidationError 를 던진다 — 라우터가 이걸
        400 VALIDATION_FAILED 로 바꾼다(DB CHECK 위반이 500 으로 새면 안 된다).
        """
        merged: dict[str, Any] = {name: current.get(name) for name in AssetIn.model_fields}
        # exclude_unset — "안 보낸 필드"와 "null 로 보낸 필드"를 구분해야 한다.
        merged.update(self.model_dump(exclude_unset=True))
        return AssetIn.model_validate(merged)


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


class IpListItem(IpOut):
    """12번 목록 항목. q 검색 시에만 관련도 정보가 채워진다."""

    score: Optional[float] = None
    matched_on: Optional[Literal["title", "alias"]] = None
    matched_text: Optional[str] = None
