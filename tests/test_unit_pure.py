"""DB 없이 도는 순수 단위 테스트 — 로직 정확성 회귀 방지.

지시서 §3.2([) 변환), §5.4(severity), §6 7번(displayState), §6 13번(정규화 키).
"""
from __future__ import annotations

from datetime import date

from app.services.conflict import severity, _period_from_literal
from app.services.territory import to_daterange_literal, end_inclusive_from_upper
from app.services.ip_norm import norm_key
from app.services.display import compute_display


def test_severity_pairs():
    assert severity("exclusive", "exclusive") == "EXCLUSIVE_VS_EXCLUSIVE"
    assert severity("sole", "sole") == "SOLE_VS_SOLE"
    assert severity("exclusive", "sole") == "EXCLUSIVE_VS_SOLE"
    assert severity("sole", "exclusive") == "EXCLUSIVE_VS_SOLE"


def test_daterange_literal_is_half_open():
    # 화면 종료일(포함) 2028-01-01 → [ , 2028-01-02) 로 하루 더해 배타 상한
    assert to_daterange_literal(date(2024, 1, 1), date(2028, 1, 1)) == "[2024-01-01,2028-01-02)"


def test_end_inclusive_roundtrip():
    lit = to_daterange_literal(date(2024, 1, 1), date(2028, 6, 30))
    p = _period_from_literal(lit)
    assert p["start"] == date(2024, 1, 1)
    assert p["end"] == date(2028, 6, 30)  # 다시 포함 개념으로 복원


def test_end_inclusive_from_upper():
    assert end_inclusive_from_upper(date(2028, 1, 2)) == date(2028, 1, 1)
    assert end_inclusive_from_upper(None) is None


def test_norm_key_removes_space_and_punct():
    assert norm_key("  사랑의 온도! ") == norm_key("사랑의온도")
    assert norm_key("The Office (US)") == norm_key("theofficeus")


def test_display_states():
    today = date(2026, 8, 24)
    # 시작 전
    st, _ = compute_display(date(2027, 1, 1), date(2028, 1, 1), today)
    assert st == "BEFORE_TERM"
    # 기간 내, 종료까지 30일 초과
    st, days = compute_display(date(2026, 1, 1), date(2027, 1, 1), today)
    assert st == "IN_TERM"
    # 기간 내, 종료 임박(30일 이하)
    st, _ = compute_display(date(2026, 1, 1), date(2026, 9, 10), today)
    assert st == "EXPIRING"
    # 만료
    st, _ = compute_display(date(2024, 1, 1), date(2026, 1, 1), today)
    assert st == "EXPIRED"
    # active 권리 없음
    st, days = compute_display(None, None, today)
    assert st is None and days is None
