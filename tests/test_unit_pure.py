"""DB 없이 도는 순수 단위 테스트 (P2-DB 정렬 후)."""
from __future__ import annotations

from datetime import date

from app.services.territory import to_daterange_literal, end_inclusive_from_upper
from app.services.ip_norm import norm_key
from app.services.display import compute_display


def test_daterange_literal_is_half_open():
    assert to_daterange_literal(date(2027, 1, 1), date(2028, 12, 31)) == "[2027-01-01,2029-01-01)"


def test_end_inclusive_from_upper():
    assert end_inclusive_from_upper(date(2029, 1, 1)) == date(2028, 12, 31)
    assert end_inclusive_from_upper(None) is None


def test_norm_key_removes_space_and_punct():
    assert norm_key("  겨울의 신호! ") == norm_key("겨울의신호")
    assert norm_key("The Office (US)") == norm_key("theofficeus")


def test_display_states():
    today = date(2026, 8, 25)
    assert compute_display(date(2027, 1, 1), date(2028, 1, 1), today)[0] == "BEFORE_TERM"
    assert compute_display(date(2026, 1, 1), date(2027, 1, 1), today)[0] == "IN_TERM"
    assert compute_display(date(2026, 1, 1), date(2026, 9, 10), today)[0] == "EXPIRING"
    assert compute_display(date(2024, 1, 1), date(2026, 1, 1), today)[0] == "EXPIRED"
    assert compute_display(None, None, today) == (None, None)
