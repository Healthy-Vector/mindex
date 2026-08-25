"""7번 GET /contracts 목록 스키마 (P2-DB 정렬).

contract + staging(processing) 이 created_at 역순으로 섞인다.
title 은 contract.title 컬럼이 없어 최신 세대 fileName 으로 대체(§11).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from app.schemas.common import CamelModel


class ContractListItem(CamelModel):
    kind: str = "contract"
    id: int
    title: Optional[str] = None
    grantor: str
    grantee: str
    status: str
    has_conflict: bool = False
    display_state: Optional[str] = None
    days_to_expiry: Optional[int] = None
    service_title: Optional[str] = None
    signed_date: Optional[date] = None
    created_at: Optional[datetime] = None


class ProcessingListItem(CamelModel):
    kind: str = "processing"
    tmpid: str
    status: str  # QUEUED / RUNNING / FAILED
    stage: Optional[str] = None
    filename: Optional[str] = None
    reason: Optional[str] = None
    created_at: Optional[datetime] = None
