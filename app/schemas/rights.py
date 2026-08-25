"""10번 GET /rights/{lineageId}/history 스키마 (P2-DB 정렬: 2축)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import Field

from app.schemas.common import CamelModel


class RightGeneration(CamelModel):
    rights_grant_id: int
    contract_id: int
    contract_history_id: int
    version: int
    territory: str
    legal_right: str
    exploitation_mode: str
    period_start: date
    period_end: Optional[date] = None
    exclusivity: str
    status: str
    created_at: Optional[datetime] = None
    terminated_at: Optional[datetime] = None
    terminated_reason: Optional[str] = None
    changed_fields: list[str] = Field(default_factory=list)


class RightsHistoryResponse(CamelModel):
    lineage_id: int
    generations: list[RightGeneration]
