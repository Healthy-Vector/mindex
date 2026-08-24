"""자연어 질의 해석 (지시서 §6 15번 1단계).

지역·기간·권리유형·독점여부를 추출한다. 휴리스틱이며, filters(사용자 지정)가
있으면 그쪽이 우선한다(2단계). 값 목록은 참조 어휘에서 읽어 매칭한다.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

_YEAR = re.compile(r"(19|20)\d{2}")

_EXCL = [
    ("non_exclusive", ["비독점", "논익스", "non-exclusive", "nonexclusive", "non exclusive"]),
    ("sole", ["단독", "sole"]),
    ("exclusive", ["독점", "exclusive"]),
]


def interpret(db: Session, query: str) -> dict[str, Any]:
    q = query or ""
    low = q.lower()

    # 지역: 국가 코드 · 국가명(라벨) · 그룹명
    territories: list[str] = []
    for code, label in db.execute(
        text("SELECT code, label FROM master.country_label")
    ).all():
        if label and label.lower() in low:
            if code not in territories:
                territories.append(code)
    for token in re.findall(r"\b[A-Z]{2}\b", q):
        if db.execute(
            text("SELECT 1 FROM master.country WHERE code=:c"), {"c": token}
        ).first():
            if token not in territories:
                territories.append(token)
    groups: list[str] = []
    for (code,) in db.execute(text("SELECT code FROM master.territory_group")).all():
        if code.lower() in low:
            groups.append(code)

    # 권리유형: 코드 · 라벨
    rights_types: list[str] = []
    for code, label in db.execute(
        text("SELECT r.code, l.label FROM master.rights_type_ref r "
             "LEFT JOIN master.rights_type_label l ON l.code=r.code")
    ).all():
        if code.lower() in low or (label and label.lower() in low):
            if code not in rights_types:
                rights_types.append(code)

    # 독점여부 (더 구체적인 것부터)
    exclusivity: Optional[str] = None
    for val, kws in _EXCL:
        if any(k in low for k in kws):
            exclusivity = val
            break

    # 기간: 연도 2개 이상이면 [min년-01-01, max년-12-31]
    years = sorted({int(m.group(0)) for m in _YEAR.finditer(q)})
    period = None
    if years:
        start = date(years[0], 1, 1)
        end = date(years[-1], 12, 31)
        period = {"start": start, "end": end}

    return {
        "territories": territories,
        "territoryGroups": groups,
        "rightsTypes": rights_types,
        "exclusivity": exclusivity,
        "period": period,
    }
