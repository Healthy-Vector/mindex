"""7번 GET /contracts 목록 스키마 (지시서 §6 7번).

두 종류(contract/processing)가 한 목록에 created_at 역순으로 섞인다.
displayState / daysToExpiry 는 저장하지 않고 계산.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from app.schemas.common import CamelModel, Page


class ContractListItem(CamelModel):
    kind: str = "contract"
    id: int
    title: str
    counterparty: str
    contract_type: Optional[str] = None
    status: str
    has_conflict: bool = False
    display_state: Optional[str] = None
    days_to_expiry: Optional[int] = None
    service_title: Optional[str] = None  # 출처 미정(§11-2) → null
    signed_date: Optional[date] = None
    created_at: Optional[datetime] = None


class ProcessingListItem(CamelModel):
    kind: str = "processing"
    tmpid: str
    status: str  # QUEUED / RUNNING / FAILED (대문자 유지)
    stage: Optional[str] = None
    filename: Optional[str] = None
    reason: Optional[str] = None
    created_at: Optional[datetime] = None


ContractsPage = Page  # items 는 두 타입의 합집합(dict) 로 직렬화
