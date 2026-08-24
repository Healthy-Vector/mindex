"""16번 GET /refs 응답 스키마 (지시서 §6 16번)."""
from __future__ import annotations

from typing import Optional

from app.schemas.common import CamelModel


class CodeLabel(CamelModel):
    code: str
    label: Optional[str] = None


class TerritoryGroupRef(CamelModel):
    code: str
    label: Optional[str] = None
    countries: list[str]  # 반드시 포함 (§6 16번): APAC 선택 시 즉시 국가 단위 전개


class ConflictCodeRef(CamelModel):
    code: str
    severity: str
    template: Optional[str] = None


class RefsResponse(CamelModel):
    countries: Optional[list[CodeLabel]] = None
    territory_groups: Optional[list[TerritoryGroupRef]] = None
    rights_types: Optional[list[CodeLabel]] = None
    conflict_codes: Optional[list[ConflictCodeRef]] = None
