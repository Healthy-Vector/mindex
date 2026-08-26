"""지역 그룹 전개 + 기간 [) 변환 (지시서 §3.2 §5.1).

기간 변환은 반드시 이 한 곳에만 둔다:
- 저장: 화면의 종료일(포함) end → daterange(start, end+1일, '[)')
- 응답: upper(daterange) → upper-1일 (다시 포함 개념으로)
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session


def to_daterange_literal(start: date, end_inclusive: date) -> str:
    """[start, end+1) 형태의 daterange 리터럴 문자열. SQL 에서 ::daterange 로 캐스팅."""
    upper = end_inclusive + timedelta(days=1)
    return f"[{start.isoformat()},{upper.isoformat()})"


def end_inclusive_from_upper(upper: date | None) -> date | None:
    """daterange 의 상한(배타) → 화면 표시용 종료일(포함)."""
    if upper is None:
        return None
    return upper - timedelta(days=1)


def expand_territories(db: Session, codes: Iterable[str]) -> list[str]:
    """국가/그룹 코드가 섞인 목록을 국가 코드로 펼치고 중복 제거(순서 보존).

    - territory_group_member 에 행이 있으면 그룹으로 보고 전개
    - 그 외에는 국가 코드로 간주
    """
    result: list[str] = []
    seen: set[str] = set()
    for raw in codes:
        code = (raw or "").strip().upper()
        if not code:
            continue
        rows = db.execute(
            text(
                "SELECT country_code FROM territory_group_member "
                "WHERE group_code = :g ORDER BY country_code"
            ),
            {"g": code},
        ).all()
        if rows:  # 그룹
            for (cc,) in rows:
                if cc not in seen:
                    seen.add(cc)
                    result.append(cc)
        else:  # 국가
            if code not in seen:
                seen.add(code)
                result.append(code)
    return result
