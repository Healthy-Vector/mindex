"""10번 GET /rights/{lineageId}/history 스키마 (지시서 §6 10번)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from app.schemas.common import CamelModel


class RightGeneration(CamelModel):
    rights_grant_id: int
    contract_id: int
    territory: str
    rights_type: str
    period_start: date
    period_end: Optional[date] = None  # 포함 개념
    exclusivity: str
    status: str
    created_at: Optional[datetime] = None
    terminated_at: Optional[datetime] = None
    terminated_reason: Optional[str] = None
    changed_fields: list[str] = []  # 직전 세대와 비교(서버 계산)


class RightsHistoryResponse(CamelModel):
    lineage_id: int
    generations: list[RightGeneration]
