from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import logging
from pathlib import Path

import yaml

from journal.store import DAILY_DIR, ILS_TZ, JournalStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DailyEntry:
    entry_date: date
    energy: float
    focus: float
    satisfaction: float


@dataclass(frozen=True)
class DailyCollection:
    entries: list[DailyEntry]
    target_days: int

    @property
    def found(self) -> int:
        return len(self.entries)

    @property
    def date_min(self) -> date | None:
        if not self.entries:
            return None
        return min(entry.entry_date for entry in self.entries)

    @property
    def date_max(self) -> date | None:
        if not self.entries:
            return None
        return max(entry.entry_date for entry in self.entries)


class JournalReader:
    def __init__(self, store: JournalStore | None = None) -> None:
        self.store = store if store is not None else JournalStore()

    def _daily_dir(self) -> Path:
        return self.store.root / DAILY_DIR

    def _today(self, today: date | datetime | None) -> date:
        if today is None:
            return datetime.now(ILS_TZ).date()
        if isinstance(today, datetime):
            if today.tzinfo is None:
                return today.replace(tzinfo=ILS_TZ).date()
            return today.astimezone(ILS_TZ).date()
        return today

    def _frontmatter_block(self, text: str) -> str:
        if not text.startswith("---\n"):
            raise ValueError("Missing opening frontmatter delimiter")

        rest = text[4:]
        end = rest.find("---\n")
        if end < 0:
            raise ValueError("Missing closing frontmatter delimiter")

        return rest[:end]

    def _parse_daily_file(self, path: Path, expected_date: date) -> DailyEntry:
        try:
            text = path.read_text(encoding="utf-8")
            frontmatter = self._frontmatter_block(text)
            data = yaml.safe_load(frontmatter)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            raise ValueError(str(exc)) from exc

        if not isinstance(data, dict):
            raise ValueError("Frontmatter is not a mapping")

        if data.get("type") != "daily":
            raise ValueError("Frontmatter type is not daily")

        try:
            energy = float(data["energy"])
            focus = float(data["focus"])
            satisfaction = float(data["satisfaction"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Missing or invalid score in frontmatter") from exc

        return DailyEntry(
            entry_date=expected_date,
            energy=energy,
            focus=focus,
            satisfaction=satisfaction,
        )

    def _available_daily_dates(self, daily_dir: Path) -> list[date]:
        dates: list[date] = []
        for path in daily_dir.glob("*.md"):
            try:
                dates.append(date.fromisoformat(path.stem))
            except ValueError:
                logger.warning("Skipping daily file with invalid filename: %s", path)
        return sorted(dates)

    def collect_daily(
        self,
        target_days: int,
        *,
        today: date | datetime | None = None,
    ) -> DailyCollection:
        daily_dir = self._daily_dir()
        if not daily_dir.exists():
            return DailyCollection(entries=[], target_days=target_days)

        available_dates = self._available_daily_dates(daily_dir)
        if not available_dates:
            return DailyCollection(entries=[], target_days=target_days)

        current = self._today(today)
        earliest = available_dates[0]
        entries: list[DailyEntry] = []

        while current >= earliest and len(entries) < target_days:
            path = daily_dir / f"{current.isoformat()}.md"
            if path.is_file():
                try:
                    entries.append(self._parse_daily_file(path, current))
                except ValueError as exc:
                    logger.warning("Skipping invalid daily journal file %s: %s", path, exc)
            current -= timedelta(days=1)

        entries.sort(key=lambda entry: entry.entry_date)
        return DailyCollection(entries=entries, target_days=target_days)
