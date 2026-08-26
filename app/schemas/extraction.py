"""PDF extraction upload and polling response schemas."""
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from app.schemas.common import CamelModel


class ExtractionAccepted(CamelModel):
    tmpid: UUID
    status: Literal["QUEUED"]
    filename: str
    byte_size: int


class ExtractionJobOut(CamelModel):
    tmpid: UUID
    status: Literal["QUEUED", "RUNNING", "DONE", "FAILED"]
    filename: str | None = None
    stage: Literal["OCR", "LLM"] | None = None
    queue_position: int | None = None
    reason: str | None = None
    # D-37 — 업로드 시점 맥락. 화면 상태 없이 tmpId만으로 들어와도 복원할 수 있다.
    mode: Literal["draft", "final"] | None = None
    contract_id: int | None = None
    ip_id: int | None = None
    result: dict[str, Any] | None = None
