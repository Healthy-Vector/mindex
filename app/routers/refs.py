"""16번 GET /refs — 참조 어휘 (P2-DB 정렬).

2축 판정: legal_right(법적 권리) · exploitation_mode(사업적 이용형태) 를 함께 내려준다.
territoryGroup 에는 countries[] 포함. 응답 캐시 가능(max-age=3600).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.refs import (
    CountryRef,
    ReasonCodeRef,
    RefsResponse,
    TaxonomyNode,
    TerritoryGroupRef,
)

router = APIRouter()

_ALL = {"legalRight", "exploitationMode", "country", "territoryGroup", "reasonCode"}


@router.get("/refs", response_model=RefsResponse, response_model_exclude_none=True)
def get_refs(
    response: Response,
    types: Optional[str] = Query(default=None),
    lang: str = Query(default="ko"),
    db: Session = Depends(get_db),
) -> RefsResponse:
    wanted = _ALL if not types else {t.strip() for t in types.split(",") if t.strip()}
    response.headers["Cache-Control"] = "max-age=3600"
    out = RefsResponse()

    if "legalRight" in wanted:
        rows = db.execute(
            text("SELECT code, parent_code, name_ko, note FROM legal_right ORDER BY lft")
        ).mappings().all()
        out.legal_rights = [TaxonomyNode(**r) for r in rows]

    if "exploitationMode" in wanted:
        rows = db.execute(
            text("SELECT code, parent_code, name_ko, note FROM exploitation_mode ORDER BY lft")
        ).mappings().all()
        out.exploitation_modes = [TaxonomyNode(**r) for r in rows]

    if "country" in wanted:
        rows = db.execute(
            text(
                "SELECT c.code, l.label, c.in_scope FROM country c "
                "LEFT JOIN country_label l ON l.country_code=c.code AND l.lang=:lang "
                "ORDER BY c.code"
            ),
            {"lang": lang},
        ).mappings().all()
        out.countries = [CountryRef(code=r["code"], label=r["label"], in_scope=r["in_scope"]) for r in rows]

    if "territoryGroup" in wanted:
        groups = db.execute(
            text(
                "SELECT g.code, l.label FROM territory_group g "
                "LEFT JOIN territory_group_label l ON l.group_code=g.code AND l.lang=:lang "
                "ORDER BY g.code"
            ),
            {"lang": lang},
        ).mappings().all()
        tg = []
        for g in groups:
            ccs = db.execute(
                text("SELECT country_code FROM territory_group_member WHERE group_code=:g ORDER BY country_code"),
                {"g": g["code"]},
            ).scalars().all()
            tg.append(TerritoryGroupRef(code=g["code"], label=g["label"], countries=list(ccs)))
        out.territory_groups = tg

    if "reasonCode" in wanted:
        rows = db.execute(
            text(
                "SELECT code, category, result_type, severity, name_ko, template_ko, template_en "
                "FROM reason_code WHERE active ORDER BY severity DESC, code"
            )
        ).mappings().all()
        out.reason_codes = [ReasonCodeRef(**r) for r in rows]

    return out
