from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import logging
from pathlib import Path

import yaml

from journal.period import ReviewPeriodSpec
from journal.store import DAILY_DIR, ILS_TZ, JournalStore, WEEKLY_DIR
from parser import CheckupParser, DailyCheckIn, WeeklyReview

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


@dataclass(frozen=True)
class ReviewDailyEntry:
    entry_date: date
    energy: int
    focus: int
    satisfaction: int
    did_today: list[str]
    meaningful: list[str]
    drained: list[str]
    tomorrow_focus: list[str]


@dataclass(frozen=True)
class ReviewWeeklyEntry:
    week: str
    saved_date: date
    momentum: list[str]
    friction: list[str]
    avoidance: list[str]
    meaningful: list[str]
    fake_productivity: list[str]
    next_week_focus: list[str]


@dataclass(frozen=True)
class ReviewCoverage:
    expected_daily_days: int
    found_daily_count: int
    found_weekly_count: int
    missing_day_estimate: int


@dataclass(frozen=True)
class DailyAveragesSummary:
    energy: float | None
    focus: float | None
    satisfaction: float | None


@dataclass(frozen=True)
class ReviewCollection:
    period: ReviewPeriodSpec
    daily_entries: list[ReviewDailyEntry]
    weekly_entries: list[ReviewWeeklyEntry]
    coverage: ReviewCoverage
    daily_averages: DailyAveragesSummary


class JournalReader:
    def __init__(self, store: JournalStore | None = None) -> None:
        self.store = store if store is not None else JournalStore()

    def _daily_dir(self) -> Path:
        return self.store.root / DAILY_DIR

    def _weekly_dir(self) -> Path:
        return self.store.root / WEEKLY_DIR

    def _today(self, today: date | datetime | None) -> date:
        if today is None:
            return datetime.now(ILS_TZ).date()
        if isinstance(today, datetime):
            if today.tzinfo is None:
                return today.replace(tzinfo=ILS_TZ).date()
            return today.astimezone(ILS_TZ).date()
        return today

    def _frontmatter_and_body(self, text: str) -> tuple[str, str]:
        if not text.startswith("---\n"):
            raise ValueError("Missing opening frontmatter delimiter")

        rest = text[4:]
        end = rest.find("---\n")
        if end < 0:
            raise ValueError("Missing closing frontmatter delimiter")

        return rest[:end], rest[end + 4 :]

    def _read_markdown_file(self, path: Path) -> tuple[dict, str]:
        try:
            text = path.read_text(encoding="utf-8")
            frontmatter, body = self._frontmatter_and_body(text)
            data = yaml.safe_load(frontmatter)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            raise ValueError(str(exc)) from exc

        if not isinstance(data, dict):
            raise ValueError("Frontmatter is not a mapping")

        return data, body

    def _parse_daily_file(self, path: Path, expected_date: date) -> DailyEntry:
        data, _ = self._read_markdown_file(path)

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

    def _parse_daily_review_file(
        self,
        path: Path,
        expected_date: date,
    ) -> ReviewDailyEntry:
        data, body = self._read_markdown_file(path)

        if data.get("type") != "daily":
            raise ValueError("Frontmatter type is not daily")

        parsed = CheckupParser.parse(body)
        if not isinstance(parsed, DailyCheckIn):
            raise ValueError("Journal body did not parse as a daily check-in")

        return ReviewDailyEntry(
            entry_date=expected_date,
            energy=parsed.energy,
            focus=parsed.focus,
            satisfaction=parsed.satisfaction,
            did_today=parsed.did_today,
            meaningful=parsed.meaningful,
            drained=parsed.drained,
            tomorrow_focus=parsed.tomorrow_focus,
        )

    def _parse_weekly_saved_date(self, data: dict) -> date:
        raw = data.get("date")
        if isinstance(raw, date):
            return raw
        if not isinstance(raw, str):
            raise ValueError("Weekly frontmatter is missing date")
        try:
            return date.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError("Weekly frontmatter date is invalid") from exc

    def _parse_weekly_review_file(self, path: Path) -> ReviewWeeklyEntry:
        data, body = self._read_markdown_file(path)

        if data.get("type") != "weekly":
            raise ValueError("Frontmatter type is not weekly")

        parsed = CheckupParser.parse(body)
        if not isinstance(parsed, WeeklyReview):
            raise ValueError("Journal body did not parse as a weekly review")

        saved_date = self._parse_weekly_saved_date(data)
        week_label = data.get("week") if isinstance(data.get("week"), str) else ""

        return ReviewWeeklyEntry(
            week=week_label,
            saved_date=saved_date,
            momentum=parsed.momentum,
            friction=parsed.friction,
            avoidance=parsed.avoidance,
            meaningful=parsed.meaningful,
            fake_productivity=parsed.fake_productivity,
            next_week_focus=parsed.next_week_focus,
        )

    def _available_daily_dates(self, daily_dir: Path) -> list[date]:
        dates: list[date] = []
        for path in daily_dir.glob("*.md"):
            try:
                dates.append(date.fromisoformat(path.stem))
            except ValueError:
                logger.warning("Skipping daily file with invalid filename: %s", path)
        return sorted(dates)

    def _iter_review_dates(self, start_date: date, end_date: date):
        current = start_date
        while current <= end_date:
            yield current
            current += timedelta(days=1)

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

    def collect_review(self, period: ReviewPeriodSpec) -> ReviewCollection:
        daily_entries: list[ReviewDailyEntry] = []
        for current in self._iter_review_dates(period.start_date, period.end_date):
            path = self._daily_dir() / f"{current.isoformat()}.md"
            if not path.is_file():
                continue
            try:
                daily_entries.append(self._parse_daily_review_file(path, current))
            except ValueError as exc:
                logger.warning("Skipping invalid daily journal file %s: %s", path, exc)

        weekly_entries: list[ReviewWeeklyEntry] = []
        weekly_dir = self._weekly_dir()
        if weekly_dir.exists():
            for path in weekly_dir.glob("*.md"):
                try:
                    entry = self._parse_weekly_review_file(path)
                except ValueError as exc:
                    logger.warning("Skipping invalid weekly journal file %s: %s", path, exc)
                    continue
                if period.start_date <= entry.saved_date <= period.end_date:
                    weekly_entries.append(entry)

        daily_entries.sort(key=lambda entry: entry.entry_date)
        weekly_entries.sort(key=lambda entry: entry.saved_date)

        if daily_entries:
            energy = sum(entry.energy for entry in daily_entries) / len(daily_entries)
            focus = sum(entry.focus for entry in daily_entries) / len(daily_entries)
            satisfaction = (
                sum(entry.satisfaction for entry in daily_entries) / len(daily_entries)
            )
            averages = DailyAveragesSummary(
                energy=energy,
                focus=focus,
                satisfaction=satisfaction,
            )
        else:
            averages = DailyAveragesSummary(
                energy=None,
                focus=None,
                satisfaction=None,
            )

        coverage = ReviewCoverage(
            expected_daily_days=period.expected_daily_days,
            found_daily_count=len(daily_entries),
            found_weekly_count=len(weekly_entries),
            missing_day_estimate=period.expected_daily_days - len(daily_entries),
        )

        return ReviewCollection(
            period=period,
            daily_entries=daily_entries,
            weekly_entries=weekly_entries,
            coverage=coverage,
            daily_averages=averages,
        )
