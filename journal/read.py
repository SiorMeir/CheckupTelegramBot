from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import logging
from pathlib import Path
import time as perf_clock
from typing import Literal

import yaml

from journal.period import ReviewPeriodSpec
from journal.store import DAILY_DIR, ILS_TZ, JournalStore, WEEKLY_DIR
from journal.week import week_bounds, week_bounds_from_label, week_label
from observability import (
    log_event,
    measure_duration_seconds,
    observe_journal_invalid_file,
    observe_journal_operation,
)
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


@dataclass(frozen=True)
class JournalFileRecord:
    kind: Literal["daily", "weekly"]
    path: Path
    is_valid: bool
    entry_date: date | None = None
    saved_date: date | None = None
    week_label: str | None = None
    week_start: date | None = None
    week_end: date | None = None
    error: str | None = None


@dataclass(frozen=True)
class JournalScan:
    records: list[JournalFileRecord]
    today: date

    @property
    def valid_records(self) -> list[JournalFileRecord]:
        return [record for record in self.records if record.is_valid]

    @property
    def valid_daily_records(self) -> list[JournalFileRecord]:
        return [
            record
            for record in self.valid_records
            if record.kind == "daily" and record.entry_date is not None
        ]

    @property
    def valid_weekly_records(self) -> list[JournalFileRecord]:
        return [
            record
            for record in self.valid_records
            if record.kind == "weekly" and record.saved_date is not None
        ]

    @property
    def valid_daily_dates(self) -> list[date]:
        return sorted(record.entry_date for record in self.valid_daily_records if record.entry_date)

    @property
    def valid_weekly_weeks(self) -> list[str]:
        labels = {
            record.week_label
            for record in self.valid_weekly_records
            if record.week_label is not None
        }
        return sorted(labels)

    @property
    def oldest_valid_entry_date(self) -> date | None:
        dates = [
            value
            for record in self.valid_records
            for value in (record.entry_date, record.saved_date)
            if value is not None
        ]
        if not dates:
            return None
        return min(dates)

    @property
    def coverage_start(self) -> date | None:
        return self.oldest_valid_entry_date


@dataclass(frozen=True)
class JournalMissingWeek:
    week_label: str
    week_start: date
    week_end: date
    missing_daily_dates: list[date]
    missing_weekly_review: bool


@dataclass(frozen=True)
class JournalLogReport:
    scan: JournalScan
    daily_count: int
    weekly_count: int
    oldest_entry_date: date | None
    weekly_gaps: list[JournalMissingWeek]
    verbose: bool

    @property
    def has_missing_entries(self) -> bool:
        return any(
            gap.missing_daily_dates or gap.missing_weekly_review for gap in self.weekly_gaps
        )


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

    def _classify_invalid_reason(self, error: str) -> str:
        if "filename" in error.lower():
            return "invalid_filename"
        if "type is not" in error:
            return "type_mismatch"
        if "date is invalid" in error or "date is missing" in error:
            return "date_error"
        if (
            "frontmatter" in error.lower()
            or "opening frontmatter delimiter" in error.lower()
            or "closing frontmatter delimiter" in error.lower()
        ):
            return "frontmatter"
        return "parse_error"

    def _record_invalid_file(self, kind: str, path: Path, error: str) -> None:
        reason = self._classify_invalid_reason(error)
        observe_journal_invalid_file(kind, reason)
        log_event(
            logger,
            logging.WARNING,
            "journal_file_skipped",
            kind=kind,
            path=str(path),
            reason=reason,
        )

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

    def _parse_frontmatter_date(self, value: object, *, field_name: str) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if not isinstance(value, str):
            raise ValueError(f"{field_name} is missing")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field_name} is invalid") from exc

    def _parse_optional_frontmatter_date(self, value: object) -> date | None:
        if value is None:
            return None
        return self._parse_frontmatter_date(value, field_name="Frontmatter date")

    def _safe_optional_frontmatter_date(self, value: object) -> date | None:
        try:
            return self._parse_optional_frontmatter_date(value)
        except ValueError:
            return None

    def _parse_weekly_saved_date(self, data: dict) -> date:
        try:
            return self._parse_frontmatter_date(data.get("date"), field_name="Weekly frontmatter date")
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    def _extract_week_metadata(
        self,
        data: dict,
        *,
        fallback_label: str | None,
    ) -> tuple[str | None, date | None, date | None]:
        label = data.get("week") if isinstance(data.get("week"), str) else fallback_label
        week_start = self._safe_optional_frontmatter_date(data.get("week_start"))
        week_end = self._safe_optional_frontmatter_date(data.get("week_end"))

        if week_start is not None and week_end is not None:
            if label is None:
                label = week_label(week_end)
            return label, week_start, week_end

        if label is not None:
            try:
                derived_start, derived_end = week_bounds_from_label(label)
            except ValueError:
                return label, week_start, week_end
            return label, derived_start, derived_end

        return None, week_start, week_end

    def _parse_weekly_review_file(self, path: Path) -> ReviewWeeklyEntry:
        data, body = self._read_markdown_file(path)

        if data.get("type") != "weekly":
            raise ValueError("Frontmatter type is not weekly")

        parsed = CheckupParser.parse(body)
        if not isinstance(parsed, WeeklyReview):
            raise ValueError("Journal body did not parse as a weekly review")

        saved_date = self._parse_weekly_saved_date(data)
        week_label_value, _, _ = self._extract_week_metadata(data, fallback_label=path.stem)
        week_label_text = week_label_value if isinstance(week_label_value, str) else ""

        return ReviewWeeklyEntry(
            week=week_label_text,
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
                self._record_invalid_file("daily", path, "Invalid daily filename")
        return sorted(dates)

    def _iter_review_dates(self, start_date: date, end_date: date):
        current = start_date
        while current <= end_date:
            yield current
            current += timedelta(days=1)

    def _scan_daily_file(self, path: Path) -> JournalFileRecord:
        try:
            entry_date = date.fromisoformat(path.stem)
        except ValueError:
            return JournalFileRecord(
                kind="daily",
                path=path,
                is_valid=False,
                error="Invalid daily filename",
            )

        try:
            self._parse_daily_review_file(path, entry_date)
        except ValueError as exc:
            return JournalFileRecord(
                kind="daily",
                path=path,
                is_valid=False,
                entry_date=entry_date,
                error=str(exc),
            )

        return JournalFileRecord(
            kind="daily",
            path=path,
            is_valid=True,
            entry_date=entry_date,
        )

    def _scan_weekly_file(self, path: Path) -> JournalFileRecord:
        fallback_label = path.stem
        try:
            data, body = self._read_markdown_file(path)
        except ValueError as exc:
            week_start = None
            week_end = None
            try:
                week_start, week_end = week_bounds_from_label(fallback_label)
            except ValueError:
                pass
            return JournalFileRecord(
                kind="weekly",
                path=path,
                is_valid=False,
                week_label=fallback_label,
                week_start=week_start,
                week_end=week_end,
                error=str(exc),
            )

        week_label_value, week_start, week_end = self._extract_week_metadata(
            data,
            fallback_label=fallback_label,
        )

        try:
            if data.get("type") != "weekly":
                raise ValueError("Frontmatter type is not weekly")
            parsed = CheckupParser.parse(body)
            if not isinstance(parsed, WeeklyReview):
                raise ValueError("Journal body did not parse as a weekly review")
            saved_date = self._parse_weekly_saved_date(data)
        except ValueError as exc:
            return JournalFileRecord(
                kind="weekly",
                path=path,
                is_valid=False,
                saved_date=self._safe_optional_frontmatter_date(data.get("date")),
                week_label=week_label_value,
                week_start=week_start,
                week_end=week_end,
                error=str(exc),
            )

        return JournalFileRecord(
            kind="weekly",
            path=path,
            is_valid=True,
            saved_date=saved_date,
            week_label=week_label_value,
            week_start=week_start,
            week_end=week_end,
        )

    def scan_journal(
        self,
        *,
        today: date | datetime | None = None,
    ) -> JournalScan:
        started_at = perf_clock.perf_counter()
        records: list[JournalFileRecord] = []

        try:
            daily_dir = self._daily_dir()
            if daily_dir.exists():
                for path in sorted(daily_dir.glob("*.md")):
                    record = self._scan_daily_file(path)
                    if not record.is_valid and record.error is not None:
                        self._record_invalid_file("daily", path, record.error)
                    records.append(record)

            weekly_dir = self._weekly_dir()
            if weekly_dir.exists():
                for path in sorted(weekly_dir.glob("*.md")):
                    record = self._scan_weekly_file(path)
                    if not record.is_valid and record.error is not None:
                        self._record_invalid_file("weekly", path, record.error)
                    records.append(record)

            scan = JournalScan(records=records, today=self._today(today))
        except Exception:
            observe_journal_operation(
                "scan_journal",
                "error",
                measure_duration_seconds(started_at),
            )
            raise

        duration_seconds = measure_duration_seconds(started_at)
        observe_journal_operation("scan_journal", "success", duration_seconds)
        log_event(
            logger,
            logging.INFO,
            "journal_scan_complete",
            record_count=len(scan.records),
            valid_daily_count=len(scan.valid_daily_records),
            valid_weekly_count=len(scan.valid_weekly_records),
            duration_ms=round(duration_seconds * 1000, 3),
        )
        return scan

    def collect_log_report(
        self,
        *,
        today: date | datetime | None = None,
        verbose: bool = False,
    ) -> JournalLogReport:
        started_at = perf_clock.perf_counter()
        try:
            scan = self.scan_journal(today=today)
            daily_count = len(scan.valid_daily_records)
            weekly_count = len(scan.valid_weekly_records)
            oldest_entry_date = scan.oldest_valid_entry_date

            if not verbose or oldest_entry_date is None:
                report = JournalLogReport(
                    scan=scan,
                    daily_count=daily_count,
                    weekly_count=weekly_count,
                    oldest_entry_date=oldest_entry_date,
                    weekly_gaps=[],
                    verbose=verbose,
                )
            else:
                valid_daily_dates = set(scan.valid_daily_dates)
                valid_weekly_labels = set(scan.valid_weekly_weeks)
                weekly_gaps: list[JournalMissingWeek] = []

                current_week_start, _ = week_bounds(scan.today)
                current_start, _ = week_bounds(oldest_entry_date)

                while current_start <= scan.today:
                    current_end = current_start + timedelta(days=6)
                    current_label = week_label(current_end)
                    range_start = max(current_start, oldest_entry_date)
                    range_end = min(current_end, scan.today)

                    missing_daily_dates: list[date] = []
                    current_day = range_start
                    while current_day <= range_end:
                        if current_day not in valid_daily_dates:
                            missing_daily_dates.append(current_day)
                        current_day += timedelta(days=1)

                    missing_weekly_review = (
                        current_end < current_week_start
                        and current_label not in valid_weekly_labels
                    )

                    if missing_daily_dates or missing_weekly_review:
                        weekly_gaps.append(
                            JournalMissingWeek(
                                week_label=current_label,
                                week_start=current_start,
                                week_end=current_end,
                                missing_daily_dates=missing_daily_dates,
                                missing_weekly_review=missing_weekly_review,
                            )
                        )

                    current_start += timedelta(days=7)

                report = JournalLogReport(
                    scan=scan,
                    daily_count=daily_count,
                    weekly_count=weekly_count,
                    oldest_entry_date=oldest_entry_date,
                    weekly_gaps=weekly_gaps,
                    verbose=True,
                )
        except Exception:
            observe_journal_operation(
                "collect_log_report",
                "error",
                measure_duration_seconds(started_at),
            )
            raise

        observe_journal_operation(
            "collect_log_report",
            "success",
            measure_duration_seconds(started_at),
        )
        return report

    def collect_daily(
        self,
        target_days: int,
        *,
        today: date | datetime | None = None,
    ) -> DailyCollection:
        started_at = perf_clock.perf_counter()
        try:
            daily_dir = self._daily_dir()
            if not daily_dir.exists():
                collection = DailyCollection(entries=[], target_days=target_days)
            else:
                available_dates = self._available_daily_dates(daily_dir)
                if not available_dates:
                    collection = DailyCollection(entries=[], target_days=target_days)
                else:
                    current = self._today(today)
                    earliest = available_dates[0]
                    entries: list[DailyEntry] = []

                    while current >= earliest and len(entries) < target_days:
                        path = daily_dir / f"{current.isoformat()}.md"
                        if path.is_file():
                            try:
                                entries.append(self._parse_daily_file(path, current))
                            except ValueError as exc:
                                self._record_invalid_file("daily", path, str(exc))
                        current -= timedelta(days=1)

                    entries.sort(key=lambda entry: entry.entry_date)
                    collection = DailyCollection(entries=entries, target_days=target_days)
        except Exception:
            observe_journal_operation(
                "collect_daily",
                "error",
                measure_duration_seconds(started_at),
            )
            raise

        observe_journal_operation(
            "collect_daily",
            "success",
            measure_duration_seconds(started_at),
        )
        return collection

    def collect_review(self, period: ReviewPeriodSpec) -> ReviewCollection:
        started_at = perf_clock.perf_counter()
        try:
            daily_entries: list[ReviewDailyEntry] = []
            for current in self._iter_review_dates(period.start_date, period.end_date):
                path = self._daily_dir() / f"{current.isoformat()}.md"
                if not path.is_file():
                    continue
                try:
                    daily_entries.append(self._parse_daily_review_file(path, current))
                except ValueError as exc:
                    self._record_invalid_file("daily", path, str(exc))

            weekly_entries: list[ReviewWeeklyEntry] = []
            weekly_dir = self._weekly_dir()
            if weekly_dir.exists():
                for path in weekly_dir.glob("*.md"):
                    try:
                        entry = self._parse_weekly_review_file(path)
                    except ValueError as exc:
                        self._record_invalid_file("weekly", path, str(exc))
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

            collection = ReviewCollection(
                period=period,
                daily_entries=daily_entries,
                weekly_entries=weekly_entries,
                coverage=coverage,
                daily_averages=averages,
            )
        except Exception:
            observe_journal_operation(
                "collect_review",
                "error",
                measure_duration_seconds(started_at),
            )
            raise

        duration_seconds = measure_duration_seconds(started_at)
        observe_journal_operation("collect_review", "success", duration_seconds)
        log_event(
            logger,
            logging.INFO,
            "review_collection_complete",
            period=period.label,
            daily_found=collection.coverage.found_daily_count,
            weekly_found=collection.coverage.found_weekly_count,
            missing_day_estimate=collection.coverage.missing_day_estimate,
            duration_ms=round(duration_seconds * 1000, 3),
        )
        return collection
