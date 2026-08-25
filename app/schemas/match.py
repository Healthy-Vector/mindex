"""4번 GET /ips/match 응답 (P2-DB 정렬).

assets = content_asset(작품 내부 범위). relations = 별도 IP(OST·리메이크 등).
P2-DB 에는 ip_relation 테이블이 아직 없어 relations 는 빈 배열이다(§11-0: OST 는
별도 IP + ip_relation 로 확정 예정, 미구현).
"""
from __future__ import annotations

from typing import Optional

from app.schemas.common import CamelModel


class AssetRef(CamelModel):
    content_asset_id: int
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
    kind: Optional[str] = None
    matched_on: str  # title / alias
    assets: list[AssetRef] = []
    relations: list[RelationRef] = []  # ip_relation 미구현 → 항상 []


class MatchResponse(CamelModel):
    matches: list[IpMatch]
