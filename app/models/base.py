"""SQLAlchemy 선언적 Base (지시서 §2, 스키마당 파일 분리)."""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
