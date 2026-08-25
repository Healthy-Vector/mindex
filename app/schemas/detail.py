"""8번 GET /contracts/{id} 상세 스키마 (P2-DB 정렬, API 설계서 §8).

정상/충돌 응답 형태가 같다. 충돌은 rights_grant 행이 아니라 histories[]의
conflicted 세대 + conflictReport 로 나타난다. authority 는 전 필드 null(§11-1).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from app.schemas.common import CamelModel


class IpBrief(CamelModel):
    ip_id: int
    title: str
    kind: Optional[str] = None


class ContentAssetRef(CamelModel):
    content_asset_id: int
    ip_id: Optional[int] = None
    ip_title: Optional[str] = None
    ip_kind: Optional[str] = None
    scope_type: Optional[str] = None
    title: Optional[str] = None


class RightRow(CamelModel):
    rights_grant_id: int
    lineage_id: Optional[int] = None
    status: str
    content_asset: ContentAssetRef
    legal_right: str
    legal_right_label: Optional[str] = None
    exploitation_mode: str
    exploitation_mode_label: Optional[str] = None
    territory: str
    territory_label: Optional[str] = None
    period_start: date
    period_end: Optional[date] = None  # 포함 개념
    exclusivity: str
    evidence: Optional[Any] = None
    conditions_raw: Optional[Any] = None
    created_at: Optional[datetime] = None
    terminated_at: Optional[datetime] = None
    terminated_reason: Optional[str] = None


class HistoryRow(CamelModel):
    history_id: int
    version: int
    document_kind: str
    status: str          # applied / conflicted
    file_name: Optional[str] = None
    uploaded_at: Optional[datetime] = None
    is_current: bool = False
    conflict_report: Optional[Any] = None


class Authority(CamelModel):
    # 스키마 미확정(§11-1). 전 필드 null.
    sublicensable: Optional[Any] = None
    allowed_party_types: Optional[Any] = None
    target_recipient_type: Optional[Any] = None


class ContractDetail(CamelModel):
    id: int
    title: Optional[str] = None       # contract.title 컬럼이 없어 최신 세대 fileName 으로 대체(§11)
    counterparty: Optional[str] = None
    status: str
    signed_date: Optional[date] = None
    lang: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    current_version: Optional[Any] = None
    has_conflict: bool = False
    conflict_report: Optional[Any] = None
    display_state: Optional[str] = None
    days_to_expiry: Optional[int] = None
    service_title: Optional[str] = None  # §11-2 → null
    grantor: Optional[str] = None        # 자기 팀(team.name). team_id 미전파라 단일팀 기준
    grantee: Optional[str] = None        # 미확정 → null
    authority: Authority = Authority()
    ips: list[IpBrief] = []
    rights: list[RightRow] = []
    histories: list[HistoryRow] = []
