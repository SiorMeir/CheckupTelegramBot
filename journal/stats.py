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


def format_statistics_report(period_label: str, collection: DailyCollection) -> str:
    averages = compute_daily_averages(collection)
    if averages is None:
        return f"No daily entries for {period_label}."

    assert collection.date_min is not None
    assert collection.date_max is not None

    if collection.found < collection.target_days:
        summary = (
            f"Partial: {collection.found} of {collection.target_days} days"
            f" · {collection.date_min.isoformat()} – {collection.date_max.isoformat()}"
        )
    else:
        summary = (
            f"{collection.found} days"
            f" · {collection.date_min.isoformat()} – {collection.date_max.isoformat()}"
        )

    scores = (
        f"Energy {averages.energy:.1f}"
        f" · Focus {averages.focus:.1f}"
        f" · Satisfaction {averages.satisfaction:.1f}"
    )
    return f"Statistics · {period_label}\n\n{summary}\n{scores}"
