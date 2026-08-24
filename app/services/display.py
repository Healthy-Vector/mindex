"""만료 상태 계산 (지시서 §6 7번) — 저장하지 않고 계산한다.

기준 period 는 계약의 active 권리 중 최소 시작 ~ 최대 종료(upper, 배타).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional


def compute_display(
    min_lower: Optional[date], max_upper: Optional[date], today: Optional[date] = None
) -> tuple[Optional[str], Optional[int]]:
    today = today or date.today()
    if min_lower is None or max_upper is None:
        return None, None
    end_inclusive = max_upper - timedelta(days=1)
    if today < min_lower:
        state = "BEFORE_TERM"
    elif today >= max_upper:
        state = "EXPIRED"
    else:
        days_left = (max_upper - today).days
        state = "EXPIRING" if days_left <= 30 else "IN_TERM"
    days_to_expiry = (end_inclusive - today).days
    return state, days_to_expiry
