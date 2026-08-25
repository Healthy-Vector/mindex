"""자연어 질의 해석 (P2-DB 정렬, §6 15번 1단계).

2축(legal_right · exploitation_mode) + 지역 + 기간 + 독점여부를 추출한다.
filters(사용자 지정)가 있으면 그쪽이 우선(2단계).
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

_YEAR = re.compile(r"(?:19|20)\d{2}")
_EXCL = [
    ("non_exclusive", ["비독점", "non-exclusive", "nonexclusive", "non exclusive"]),
    ("sole", ["단독", "sole"]),
    ("exclusive", ["독점", "exclusive"]),
]


def _match_taxonomy(db: Session, table: str, low: str) -> list[str]:
    hits: list[str] = []
    for code, name in db.execute(text(f"SELECT code, name_ko FROM {table}")):
        if code.lower() in low or (name and name.lower() in low):
            if code not in hits:
                hits.append(code)
    return hits


def interpret(db: Session, query: str) -> dict[str, Any]:
    q = query or ""
    low = q.lower()

    legal_rights = _match_taxonomy(db, "legal_right", low)
    exploitation_modes = _match_taxonomy(db, "exploitation_mode", low)

    territories: list[str] = []
    for code, label in db.execute(text("SELECT country_code, label FROM country_label")):
        if label and label.lower() in low and code not in territories:
            territories.append(code)
    for token in re.findall(r"\b[A-Z]{2}\b", q):
        if db.execute(text("SELECT 1 FROM country WHERE code=:c"), {"c": token}).first():
            if token not in territories:
                territories.append(token)
    groups: list[str] = []
    for (code,) in db.execute(text("SELECT code FROM territory_group")):
        if code.lower() in low:
            groups.append(code)

    exclusivity = None
    for val, kws in _EXCL:
        if any(k in low for k in kws):
            exclusivity = val
            break

    years = sorted({int(m.group(0)) for m in _YEAR.finditer(q)})
    period = None
    if years:
        period = {"start": date(years[0], 1, 1), "end": date(years[-1], 12, 31)}

    return {
        "legalRights": legal_rights,
        "exploitationModes": exploitation_modes,
        "territories": territories,
        "territoryGroups": groups,
        "exclusivity": exclusivity,
        "period": period,
    }
