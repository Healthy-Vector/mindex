"""15번 POST /search 스키마 (P2-DB 정렬: 2축)."""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from app.schemas.common import CamelModel


class SearchFilters(CamelModel):
    legal_rights: Optional[list[str]] = None
    exploitation_modes: Optional[list[str]] = None
    territories: Optional[list[str]] = None
    exclusivity: Optional[str] = None
    period: Optional[dict[str, date]] = None


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
    score: Optional[float] = None


class SearchResponse(CamelModel):
    interpreted: dict[str, Any]
    results: list[SearchResult]
    total: int
    page: int
    size: int
    vector_ranked: bool = False
