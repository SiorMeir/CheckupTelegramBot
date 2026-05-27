from __future__ import annotations

from dataclasses import dataclass
import re

MAX_TARGET_DAYS = 730
DEFAULT_PERIOD_TOKEN = "4w"
_PERIOD_RE = re.compile(r"^([1-9]\d*)([dwm])$")


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
