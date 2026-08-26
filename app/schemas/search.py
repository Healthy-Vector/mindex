"""15번 POST /search 스키마 (P2-DB 정렬: 2축)."""
from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from pydantic import Field, model_validator

from app.schemas.common import CamelModel


class SearchPeriod(CamelModel):
    start: date
    end: date

    @model_validator(mode="after")
    def end_not_before_start(self) -> "SearchPeriod":
        if self.end < self.start:
            raise ValueError("period.end는 period.start보다 빠를 수 없습니다")
        return self


class SearchFilters(CamelModel):
    legal_rights: Optional[list[str]] = None
    exploitation_modes: Optional[list[str]] = None
    territories: Optional[list[str]] = None
    exclusivity: Optional[Literal["exclusive", "sole", "non_exclusive"]] = None
    period: Optional[SearchPeriod] = None


class SearchRequest(CamelModel):
    query: str = ""
    filters: Optional[SearchFilters] = None
    page: int = Field(default=1, ge=1)
    size: Optional[int] = Field(default=None, ge=1, le=100)


class SearchResult(CamelModel):
    contract_id: int
    title: Optional[str] = None
    grantor: str
    grantee: str
    status: Optional[str] = None
    score: Optional[float] = None


class SearchResponse(CamelModel):
    interpreted: dict[str, Any]
    results: list[SearchResult]
    total: int
    page: int
    size: int
    vector_ranked: bool = False
