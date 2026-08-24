"""8번 GET /contracts/{id} 상세 스키마 (지시서 §6 8번).

정상/충돌 계약의 응답 형태가 같다. authority 는 전 필드 null 고정(§11-1).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from app.schemas.common import CamelModel


class IpBrief(CamelModel):
    """계약에 걸린 IP 요약 (상단 표시용)."""

    ip_id: int
    title: str
    kind: Optional[str] = None


class RightRow(CamelModel):
    rights_grant_id: int
    lineage_id: Optional[int] = None
    content_asset_id: int
    # IP·작품 정보(화면 표시용) — content_asset → ip 조인 결과
    ip_id: Optional[int] = None
    ip_title: Optional[str] = None
    ip_kind: Optional[str] = None
    content_asset_title: Optional[str] = None
    scope_type: Optional[str] = None
    territory: str
    rights_type: str
    period_start: date
    period_end: Optional[date] = None  # 포함 개념
    exclusivity: str
    status: str
    conditions_raw: Optional[Any] = None
    confidence: Optional[float] = None
    evidence: Optional[Any] = None


class HistoryRow(CamelModel):
    id: int
    version: str
    status: str
    created_at: Optional[datetime] = None
    conflict_report: Optional[Any] = None


class Authority(CamelModel):
    # 스키마 미확정(§11-1). 전 필드 null 로 고정 반환.
    status: Optional[Any] = None
    grantee: Optional[Any] = None
    period: Optional[Any] = None
    note: Optional[Any] = None


class ContractDetail(CamelModel):
    id: int
    title: Optional[str] = None
    counterparty: Optional[str] = None
    contract_type: Optional[str] = None
    status: str
    signed_date: Optional[date] = None
    lang: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    has_conflict: bool = False
    conflict_report: Optional[Any] = None
    display_state: Optional[str] = None
    days_to_expiry: Optional[int] = None
    service_title: Optional[str] = None  # §11-2 → null
    grantor: Optional[str] = None        # §11-4 → team.name
    authority: Authority = Authority()   # §11-1 → 전 필드 null
    ips: list[IpBrief] = []              # 계약에 걸린 IP 목록(중복 제거)
    rights: list[RightRow] = []
    history: list[HistoryRow] = []
