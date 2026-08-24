"""계약 검증/확정 스키마 (지시서 §5 5·6번)."""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from pydantic import Field

from app.schemas.common import CamelModel


class Period(CamelModel):
    start: date
    end: date  # 포함 개념(그날까지 유효). 저장 시 [) 로 변환(§3.2)


class RightIn(CamelModel):
    content_asset_id: int
    rights_type: str
    territories: list[str]  # 국가 코드 또는 그룹 코드(APAC 등)
    period: Period
    exclusivity: str  # exclusive / sole / non_exclusive
    conditions_raw: Optional[dict[str, Any]] = None
    evidence: Optional[dict[str, Any]] = None
    confidence: Optional[float] = None


class VerifyRequest(CamelModel):
    mode: str = Field(default="new")  # new / revision / final
    contract_id: Optional[int] = None
    title: Optional[str] = None
    counterparty: Optional[str] = None
    rights: list[RightIn]


class OverlapOut(CamelModel):
    start: Optional[date] = None
    end: Optional[date] = None  # 포함 개념
    days: int


class ExistingGrantOut(CamelModel):
    rights_grant_id: int
    contract_id: int
    contract_title: Optional[str] = None
    counterparty: Optional[str] = None
    period: Period
    exclusivity: str
    evidence: Optional[Any] = None


class ThisSideOut(CamelModel):
    content_asset_id: int
    territory: str
    rights_type: str
    period: Period
    exclusivity: str


class ConflictItem(CamelModel):
    severity: str
    this: ThisSideOut
    existing: ExistingGrantOut
    overlap: OverlapOut


class VerifyResponse(CamelModel):
    has_conflict: bool
    checked_rows: int
    conflicts: list[ConflictItem] = []
