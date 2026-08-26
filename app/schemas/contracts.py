"""계약 검증/확정/종료 스키마 (P2-DB 정렬).

요청은 P2 DB 함수(validate_rights_batch / save_rights_batch) 인자에 맞춘다.
권리는 2축: legal_right(법적 권리) × exploitation_mode(사업적 이용형태).
evidence 는 필드별 근거({quote} 필수) — DB CHECK(is_valid_evidence)가 강제한다.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.common import CamelModel


class Period(CamelModel):
    start: date
    end: date  # 포함 개념(그날까지 유효). 저장 시 [) 로 변환

    @model_validator(mode="after")
    def end_not_before_start(self) -> "Period":
        if self.end < self.start:
            raise ValueError("period.end는 period.start보다 빠를 수 없습니다")
        return self


class RightIn(CamelModel):
    content_asset_id: Optional[int] = None  # 생략 시 DB 가 IP 기본 asset 사용
    legal_right: str          # legal_right.code (예: TRANSMISSION, BROADCAST, ...)
    exploitation_mode: str    # exploitation_mode.code (예: SVOD, THEATRICAL, ...)
    territories: list[str] = Field(min_length=1)  # 국가 또는 그룹 코드(APAC 등)
    period: Period
    exclusivity: Literal["exclusive", "sole", "non_exclusive"]
    evidence: dict[str, Any]  # 키: legal_right/exploitation_mode/territory/period/exclusivity, 각 {quote}
    conditions_raw: Optional[dict[str, Any]] = None


class VerifyRequest(CamelModel):
    """5번 검증 요청. 두 경로를 받는다 (D-34).

    - **staging 경로**: `tmpId` + `patch`(화면 DTO shape의 JSON merge
      patch). 서버가 수정본을 staging에 반영하고 그 값으로 판정한다.
      `rights`·`fileName`·`filePath`·`fileHash`는 서버가 채우므로 보내지 않는다.
    - **직접 경로**: 예전대로 전체 body. 수기 등록·테스트용이다.

    `filePath`는 staging 경로에서 **무시된다.** 저장 경로는 서버가 정한다 —
    예전에 클라이언트가 준 경로를 그대로 열어주던 임의 파일 읽기를 막는다(D-34).
    """

    contract_id: Optional[int] = None   # 개정판이면 기존 계약 id, 신규면 None
    # staging 경로에서는 생략할 수 있다 — 추출 payload의 parties에서 서버가
    # 뽑는다(D-36). 보내면 그 값이 우선한다. 직접 경로에서는 여전히 필수다.
    grantor: Optional[str] = None
    grantee: Optional[str] = None
    ip_id: Optional[int] = None         # 신규 작품이면 None
    # API 이름은 `tmpId` — 화면과 `GET /extract/{tmpid}`가 쓰는 이름에 맞춘다.
    # 파이썬·DB 쪽은 `source_tmpid`(contract.source_tmpid,
    # save_rights_batch(p_source_tmpid))를 그대로 유지한다.
    source_tmpid: Optional[UUID] = Field(default=None, alias="tmpId")
    patch: Optional[dict[str, Any]] = None  # tmpId 경로의 부분수정(RFC 7386)
    file_name: Optional[str] = None
    file_path: Optional[str] = None
    file_hash: Optional[str] = None
    mime_type: Optional[str] = None
    raw_text: Optional[str] = None
    # 생략하면 extract_job.mode를 쓴다(D-37). staging 경로가 아니면 draft.
    document_kind: Optional[Literal["draft", "final"]] = None
    rights: Optional[list[RightIn]] = None

    @model_validator(mode="after")
    def direct_path_needs_full_body(self) -> "VerifyRequest":
        if self.source_tmpid is not None:
            return self
        if self.patch is not None:
            raise ValueError("patch는 tmpId와 함께만 사용할 수 있습니다")
        missing = [
            name
            for name, value in (
                ("grantor", self.grantor),
                ("grantee", self.grantee),
                ("fileName", self.file_name),
                ("filePath", self.file_path),
                ("fileHash", self.file_hash),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                "tmpId 없이 호출하려면 " + ", ".join(missing) + "이(가) 필요합니다"
            )
        if not self.rights:
            raise ValueError("rights는 한 건 이상이어야 합니다")
        return self


class ConfirmRequest(VerifyRequest):
    # 생략하면 extract_job.mode를 쓴다(D-37). staging 경로가 아니면 final.
    document_kind: Optional[Literal["draft", "final"]] = None


class VerifyResponse(CamelModel):
    batch_result: str          # APPLIED / CONFLICTED
    has_conflict: bool
    constraint_name: Optional[str] = None
    conflict_report: Optional[Any] = None  # P2 내용 유지, API 키는 camelCase


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
    terminated_at: datetime
