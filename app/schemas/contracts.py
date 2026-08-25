"""계약 검증/확정/종료 스키마 (P2-DB 정렬).

요청은 P2 DB 함수(validate_rights_batch / save_rights_batch) 인자에 맞춘다.
권리는 2축: legal_right(법적 권리) × exploitation_mode(사업적 이용형태).
evidence 는 필드별 근거({quote} 필수) — DB CHECK(is_valid_evidence)가 강제한다.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional
from uuid import UUID

from pydantic import Field

from app.schemas.common import CamelModel


class Period(CamelModel):
    start: date
    end: date  # 포함 개념(그날까지 유효). 저장 시 [) 로 변환


class RightIn(CamelModel):
    content_asset_id: Optional[int] = None  # 생략 시 DB 가 IP 기본 asset 사용
    legal_right: str          # legal_right.code (예: TRANSMISSION, BROADCAST, ...)
    exploitation_mode: str    # exploitation_mode.code (예: SVOD, THEATRICAL, ...)
    territories: list[str]    # 국가 코드 또는 그룹 코드(APAC 등 → 국가로 전개)
    period: Period
    exclusivity: str          # exclusive / sole / non_exclusive
    evidence: dict[str, Any]  # 키: legal_right/exploitation_mode/territory/period/exclusivity, 각 {quote}
    conditions_raw: Optional[dict[str, Any]] = None


class ChunkIn(CamelModel):
    clause_no: Optional[str] = None
    chunk_text: str
    lang: Optional[str] = None
    page: Optional[int] = None
    embedding: Optional[list[float]] = None


class VerifyRequest(CamelModel):
    contract_id: Optional[int] = None   # 개정판이면 기존 계약 id, 신규면 None
    counterparty: str
    ip_id: Optional[int] = None         # 신규 작품이면 None
    file_name: str
    file_path: str
    file_hash: str
    mime_type: Optional[str] = None
    raw_text: Optional[str] = None
    document_kind: str = Field(default="draft")  # draft / final
    rights: list[RightIn]


class ConfirmRequest(VerifyRequest):
    document_kind: str = Field(default="final")
    chunks: list[ChunkIn] = []
    source_tmpid: Optional[UUID] = None  # staging.extract_job.tmpid. 이중 확정 차단


class VerifyResponse(CamelModel):
    batch_result: str          # APPLIED / CONFLICTED
    has_conflict: bool
    constraint_name: Optional[str] = None
    conflict_report: Optional[Any] = None  # P2 형태 그대로


class ConfirmResponse(CamelModel):
    batch_result: str
    contract_id: int
    contract_history_id: int
    has_conflict: bool
    constraint_name: Optional[str] = None
    conflict_report: Optional[Any] = None


class CancelResponse(CamelModel):
    contract_id: int
    status: str
    terminated_rights: int
