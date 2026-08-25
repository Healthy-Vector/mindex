"""16번 GET /refs 응답 (P2-DB 정렬). 2축 taxonomy + 지역 + 사유코드."""
from __future__ import annotations

from typing import Optional

from app.schemas.common import CamelModel


class TaxonomyNode(CamelModel):
    code: str
    parent_code: Optional[str] = None
    name_ko: Optional[str] = None
    note: Optional[str] = None


class CountryRef(CamelModel):
    code: str
    label: Optional[str] = None
    in_scope: bool = False


class TerritoryGroupRef(CamelModel):
    code: str
    label: Optional[str] = None
    countries: list[str]


class ReasonCodeRef(CamelModel):
    code: str
    category: Optional[str] = None
    result_type: Optional[str] = None
    severity: Optional[int] = None
    name_ko: Optional[str] = None
    template_ko: Optional[str] = None
    template_en: Optional[str] = None


class RefsResponse(CamelModel):
    legal_rights: Optional[list[TaxonomyNode]] = None
    exploitation_modes: Optional[list[TaxonomyNode]] = None
    countries: Optional[list[CountryRef]] = None
    territory_groups: Optional[list[TerritoryGroupRef]] = None
    reason_codes: Optional[list[ReasonCodeRef]] = None
