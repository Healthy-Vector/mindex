"""8번 GET /contracts/{id} 상세 스키마 (지시서 §6 8번 · API 설계서 §8).

정상/충돌 계약의 응답 형태가 같다. authority 는 전 필드 null 고정(§11-1).
rights[].contentAsset 는 설계서 형태의 객체 { contentAssetId, ipId, ipTitle, scopeType, title }.
(ipTitle 은 화면에서 IP명을 별도 호출 없이 표시하기 위한 확장)
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from app.schemas.common import CamelModel


class ContentAssetRef(CamelModel):
    """권리 대상 — 설계서 §8 rights[].contentAsset."""

    content_asset_id: int
    ip_id: Optional[int] = None
    ip_title: Optional[str] = None   # 화면 IP명 표시용(설계서 확장)
    ip_kind: Optional[str] = None
    scope_type: Optional[str] = None
    title: Optional[str] = None      # 작품(content_asset) 제목


class RightRow(CamelModel):
    rights_grant_id: int
    lineage_id: Optional[int] = None
    content_asset: ContentAssetRef
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
    rights: list[RightRow] = []
    history: list[HistoryRow] = []
