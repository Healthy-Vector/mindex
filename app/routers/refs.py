"""16번 GET /refs — 참조 어휘 (지시서 §6 16번).

types 로 필요한 것만 고른다. territoryGroup 에는 countries[] 를 반드시 포함.
응답은 캐시 가능(Cache-Control: max-age=3600).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.refs import CodeLabel, ConflictCodeRef, RefsResponse, TerritoryGroupRef

router = APIRouter()

_ALL = {"country", "territoryGroup", "rightsType", "conflictCode"}


@router.get("/refs", response_model=RefsResponse, response_model_exclude_none=True)
def get_refs(
    response: Response,
    types: Optional[str] = Query(default=None, description="쉼표구분: country,territoryGroup,rightsType,conflictCode"),
    lang: str = Query(default="ko"),
    db: Session = Depends(get_db),
) -> RefsResponse:
    wanted = _ALL if not types else {t.strip() for t in types.split(",") if t.strip()}
    response.headers["Cache-Control"] = "max-age=3600"
    out = RefsResponse()

    if "country" in wanted:
        rows = db.execute(
            text(
                "SELECT c.code, l.label FROM master.country c "
                "LEFT JOIN master.country_label l ON l.code=c.code AND l.lang=:lang "
                "ORDER BY c.code"
            ),
            {"lang": lang},
        ).all()
        out.countries = [CodeLabel(code=r[0], label=r[1]) for r in rows]

    if "territoryGroup" in wanted:
        groups = db.execute(
            text(
                "SELECT g.code, l.label FROM master.territory_group g "
                "LEFT JOIN master.territory_group_label l ON l.code=g.code AND l.lang=:lang "
                "ORDER BY g.code"
            ),
            {"lang": lang},
        ).all()
        tg: list[TerritoryGroupRef] = []
        for code, label in groups:
            ccs = db.execute(
                text(
                    "SELECT country_code FROM master.territory_group_country "
                    "WHERE group_code=:g ORDER BY country_code"
                ),
                {"g": code},
            ).all()
            tg.append(TerritoryGroupRef(code=code, label=label, countries=[c[0] for c in ccs]))
        out.territory_groups = tg

    if "rightsType" in wanted:
        rows = db.execute(
            text(
                "SELECT r.code, l.label FROM master.rights_type_ref r "
                "LEFT JOIN master.rights_type_label l ON l.code=r.code AND l.lang=:lang "
                "ORDER BY r.code"
            ),
            {"lang": lang},
        ).all()
        out.rights_types = [CodeLabel(code=r[0], label=r[1]) for r in rows]

    if "conflictCode" in wanted:
        rows = db.execute(
            text(
                "SELECT c.code, c.severity, t.template FROM master.conflict_code c "
                "LEFT JOIN master.conflict_code_template t ON t.code=c.code AND t.lang=:lang "
                "ORDER BY c.code"
            ),
            {"lang": lang},
        ).all()
        out.conflict_codes = [
            ConflictCodeRef(code=r[0], severity=r[1], template=r[2]) for r in rows
        ]

    return out
