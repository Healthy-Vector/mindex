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


# --- 6번 확정 저장 (지시서 §5.6) ---
from uuid import UUID  # noqa: E402


class ChunkIn(CamelModel):
    clause_no: Optional[str] = None
    chunk_text: str
    lang: Optional[str] = None
    page: Optional[int] = None
    embedding: Optional[list[float]] = None


class ConfirmRequest(CamelModel):
    mode: str = Field(default="new")  # new / revision / final
    contract_id: Optional[int] = None
    source_tmpid: Optional[UUID] = None  # 확정 원본. 중복 확정 차단(source_tmpid UNIQUE)
    title: Optional[str] = None
    counterparty: Optional[str] = None
    contract_type: Optional[str] = None
    signed_date: Optional[date] = None
    lang: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    file_path: Optional[str] = None
    raw_text: Optional[str] = None
    rights: list[RightIn]
    chunks: list[ChunkIn] = []


class ConfirmResponse(CamelModel):
    contract_id: int
    contract_history_id: int
    contract_status: str
    history_status: str  # applied / conflicted
    has_conflict: bool
    rights_grant_ids: list[int] = []
    conflicts: list[ConflictItem] = []


class CancelRequest(CamelModel):
    reason: str = "cancelled"  # superseded / cancelled / expired / waiver


class CancelResponse(CamelModel):
    contract_id: int
    status: str
    terminated_rights: int
