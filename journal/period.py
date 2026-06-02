from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re

from journal.store import ILS_TZ

MAX_TARGET_DAYS = 730
DEFAULT_PERIOD_TOKEN = "4w"
_PERIOD_RE = re.compile(r"^([1-9]\d*)([dwm])$")
DEFAULT_REVIEW_TOKEN = "4w"
_REVIEW_PERIOD_RE = re.compile(r"^([1-9]\d*)w$")


@dataclass(frozen=True)
class PeriodSpec:
    raw_token: str
    target_days: int

    @property
    def label(self) -> str:
        return self.raw_token


def parse_period(token: str | None) -> PeriodSpec:
    raw = DEFAULT_PERIOD_TOKEN if token is None else token.strip().lower()

    if not raw:
        raise ValueError("Missing period")

    match = _PERIOD_RE.fullmatch(raw)
    if not match:
        raise ValueError("Invalid period")

    amount = int(match.group(1))
    unit = match.group(2)

    multiplier = {
        "d": 1,
        "w": 7,
        "m": 30,
    }[unit]
    target_days = amount * multiplier

    if target_days > MAX_TARGET_DAYS:
        raise ValueError("Period too large")

    return PeriodSpec(raw_token=raw, target_days=target_days)


@dataclass(frozen=True)
class ReviewPeriodSpec:
    raw_token: str
    target_days: int
    start_date: date
    end_date: date

    @property
    def label(self) -> str:
        return self.raw_token

    @property
    def expected_daily_days(self) -> int:
        return self.target_days


def _today(today: date | datetime | None) -> date:
    if today is None:
        return datetime.now(ILS_TZ).date()
    if isinstance(today, datetime):
        if today.tzinfo is None:
            return today.replace(tzinfo=ILS_TZ).date()
        return today.astimezone(ILS_TZ).date()
    return today


def parse_review_period(
    token: str | None,
    *,
    today: date | datetime | None = None,
) -> ReviewPeriodSpec:
    raw = DEFAULT_REVIEW_TOKEN if token is None else token.strip().lower()
    if not raw:
        raise ValueError("Missing review period")

    match = _REVIEW_PERIOD_RE.fullmatch(raw)
    if not match:
        raise ValueError("Invalid review period")

    weeks = int(match.group(1))
    target_days = weeks * 7
    end_date = _today(today)
    start_date = end_date - timedelta(days=target_days - 1)

    return ReviewPeriodSpec(
        raw_token=raw,
        target_days=target_days,
        start_date=start_date,
        end_date=end_date,
    )
