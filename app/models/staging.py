"""staging 스키마 ORM (지시서 §3.3).

P1 이 소유. P4 는 읽기만 하고, 6번 확정 저장에서 pdf_blob 을 DELETE(CASCADE)할 때만 쓴다.
extract_job.status 는 대문자(QUEUED/RUNNING/DONE/FAILED) — 소문자로 바꾸지 않는다(§3.4).
"""
from __future__ import annotations

from sqlalchemy import (
    CHAR,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.models.base import Base

SCHEMA = "staging"


class PdfBlob(Base):
    __tablename__ = "pdf_blob"
    __table_args__ = {"schema": SCHEMA}
    tmpid = Column(UUID(as_uuid=True), primary_key=True)
    data = Column(LargeBinary, nullable=False)
    filename = Column(Text)
    byte_size = Column(Integer)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ExtractJob(Base):
    __tablename__ = "extract_job"
    __table_args__ = (
        Index("ix_job_queue", "status", "created_at"),
        {"schema": SCHEMA},
    )
    tmpid = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.pdf_blob.tmpid", ondelete="CASCADE"),
        primary_key=True,
    )
    status = Column(Text, nullable=False)  # QUEUED / RUNNING / DONE / FAILED (대문자)
    stage = Column(Text)
    lease_until = Column(DateTime(timezone=True))
    attempts = Column(Integer, nullable=False, server_default="0")
    reason = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ExtractResult(Base):
    __tablename__ = "extract_result"
    __table_args__ = {"schema": SCHEMA}
    tmpid = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.pdf_blob.tmpid", ondelete="CASCADE"),
        primary_key=True,
    )
    payload = Column(JSONB, nullable=False)
    confidence = Column(Numeric(4, 3))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
