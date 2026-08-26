"""만료 상태 계산 (지시서 §6 7번) — 저장하지 않고 계산한다.

기준 period 는 계약의 active 권리 중 최소 시작 ~ 최대 종료(upper, 배타).

경계는 프론트 `frontend/src/lib/contractStatus.js` 와 같아야 한다 — 잔여일이
90일 이상이면 기간 중, 미만이면 만료 임박이고 임박 단계는 30/60/90 이다.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional


EXPIRING_WITHIN_DAYS = 90          # 이 미만으로 남으면 EXPIRING
EXPIRING_TIERS = (30, 60, 90)      # 잔여일이 걸리는 첫 단계가 그 건의 tier


def compute_display(
    min_lower: Optional[date],
    max_upper: Optional[date],
    today: Optional[date] = None,
    *,
    contract_status: Optional[str] = None,
) -> tuple[Optional[str], Optional[int], Optional[int]]:
    """(displayState, daysToExpiry, expiringTier) 를 돌려준다.

    - PRE_CONTRACT   계약 전(contract.status='draft'). 기간과 무관하게 우선한다.
                     서명일(signed_date)은 상태 판정에 쓰지 않는다 — 업무 상태
                     컬럼 하나만 보는 편이 화면과 API 의 기준이 어긋나지 않는다.
    - BEFORE_TERM    유효기간 전. daysToExpiry 는 시작일까지 남은 일수(양수).
    - IN_TERM        기간 중(잔여 90일 이상).
    - EXPIRING       만료 임박(잔여 90일 미만). tier 는 30/60/90.
    - EXPIRED        기간 만료. daysToExpiry 는 종료일 이후 경과 일수(음수).
    """
    today = today or date.today()
    if contract_status == "draft":
        return "PRE_CONTRACT", None, None
    if min_lower is None or max_upper is None:
        return None, None, None

    # period 는 daterange 의 [) 라 upper 는 배타 — 표시용 종료일은 하루 앞이다.
    end_inclusive = max_upper - timedelta(days=1)
    if today < min_lower:
        return "BEFORE_TERM", (min_lower - today).days, None

    days_to_expiry = (end_inclusive - today).days
    if today > end_inclusive:
        return "EXPIRED", days_to_expiry, None
    if days_to_expiry >= EXPIRING_WITHIN_DAYS:
        return "IN_TERM", days_to_expiry, None

    tier = next(t for t in EXPIRING_TIERS if days_to_expiry <= t)
    return "EXPIRING", days_to_expiry, tier
