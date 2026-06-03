from __future__ import annotations

from dataclasses import dataclass

from journal.read import DailyCollection


@dataclass(frozen=True)
class DailyAverages:
    energy: float
    focus: float
    satisfaction: float


def compute_daily_averages(collection: DailyCollection) -> DailyAverages | None:
    if not collection.entries:
        return None

    count = len(collection.entries)
    energy = sum(entry.energy for entry in collection.entries) / count
    focus = sum(entry.focus for entry in collection.entries) / count
    satisfaction = sum(entry.satisfaction for entry in collection.entries) / count
    return DailyAverages(
        energy=energy,
        focus=focus,
        satisfaction=satisfaction,
    )
