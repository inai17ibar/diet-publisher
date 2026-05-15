from datetime import date, datetime

from app.services.day_counter import calculate_day_number


def test_calculate_day_number_matches_reference_date():
    assert calculate_day_number(date(2026, 5, 14)) == 329


def test_calculate_day_number_accepts_datetime():
    assert calculate_day_number(datetime(2026, 5, 15, 12, 0, 0)) == 330


def test_calculate_day_number_before_start_date_returns_none():
    assert calculate_day_number(date(2025, 6, 19)) is None
