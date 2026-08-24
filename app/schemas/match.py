"""4번 GET /ips/match 응답 (지시서 §6 4번).

assets = 작품 내부 범위(content_asset), relations = 별도 IP(OST·리메이크 등, ip_relation).
한 응답에 함께 실어 드롭다운이 한 박자 늦게 채워지지 않게 한다.
"""
from __future__ import annotations

from typing import Optional

from app.schemas.common import CamelModel


class AssetRef(CamelModel):
    id: int
    scope_type: str
    season_no: Optional[int] = None
    episode_no: Optional[int] = None
    edition_code: Optional[str] = None
    title: Optional[str] = None


class RelationRef(CamelModel):
    relation_type: str
    ip_id: int
    title: str


class IpMatch(CamelModel):
    ip_id: int
    title: str
    kind: str
    matched_on: str  # title / alias
    assets: list[AssetRef] = []
    relations: list[RelationRef] = []


class MatchResponse(CamelModel):
    matches: list[IpMatch]
