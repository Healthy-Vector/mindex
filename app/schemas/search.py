"""15번 POST /search 스키마 (지시서 §6 15번)."""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from app.schemas.common import CamelModel


class SearchFilters(CamelModel):
    territories: Optional[list[str]] = None
    rights_types: Optional[list[str]] = None
    exclusivity: Optional[str] = None
    period: Optional[dict[str, date]] = None  # {start, end(포함)}


class SearchRequest(CamelModel):
    query: str = ""
    filters: Optional[SearchFilters] = None
    page: int = 1
    size: Optional[int] = None


class SearchResult(CamelModel):
    contract_id: int
    title: Optional[str] = None
    counterparty: Optional[str] = None
    status: Optional[str] = None
    score: Optional[float] = None  # 코사인 유사도(벡터 랭킹 시)


class SearchResponse(CamelModel):
    interpreted: dict[str, Any]  # "시스템이 이렇게 이해했다" — 그대로 실어 보냄
    results: list[SearchResult]
    total: int
    page: int
    size: int
    vector_ranked: bool = False
