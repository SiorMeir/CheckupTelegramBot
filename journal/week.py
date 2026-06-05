from __future__ import annotations

from datetime import date, timedelta
import re

_WEEK_LABEL_RE = re.compile(r"^(\d{4})-week-(\d{2})$")


def week_bounds(day: date) -> tuple[date, date]:
    delta = (day.weekday() - 6) % 7
    start_date = day - timedelta(days=delta)
    return start_date, start_date + timedelta(days=6)


def week_label(day: date) -> str:
    _, end_date = week_bounds(day)
    first_week_end = week_bounds(date(end_date.year, 1, 1))[1]
    week_number = ((end_date - first_week_end).days // 7) + 1
    return f"{end_date.year}-week-{week_number:02d}"


def week_bounds_from_label(label: str) -> tuple[date, date]:
    match = _WEEK_LABEL_RE.fullmatch(label)
    if not match:
        raise ValueError("Invalid week label")

    year = int(match.group(1))
    week_number = int(match.group(2))
    if week_number < 1:
        raise ValueError("Invalid week label")

    first_week_end = week_bounds(date(year, 1, 1))[1]
    end_date = first_week_end + timedelta(days=(week_number - 1) * 7)
    start_date = end_date - timedelta(days=6)

    if week_label(end_date) != label:
        raise ValueError("Invalid week label")

    return start_date, end_date
