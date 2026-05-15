from datetime import date, datetime

from app.config import settings


def calculate_day_number(target_date: date | datetime) -> int | None:
    """Return the 1-based diet day number for a date, or None before the start date."""
    if isinstance(target_date, datetime):
        target_date = target_date.date()

    day_number = (target_date - settings.diet_start_date).days + 1
    return day_number if day_number >= 1 else None
