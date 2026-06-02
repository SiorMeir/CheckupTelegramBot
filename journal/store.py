from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from parser import DailyCheckIn, WeeklyReview

DAILY_DIR = "daily"
WEEKLY_DIR = "weekly"
ILS_TZ = ZoneInfo("Asia/Jerusalem")


class JournalStore:
    def __init__(self, root: str | Path | None = None) -> None:
        env_root = os.environ.get("JOURNAL_ROOT", "journal")
        self.root = Path(root if root is not None else env_root)

    def _now(self, when: datetime | None) -> datetime:
        if when is None:
            return datetime.now(ILS_TZ)
        if when.tzinfo is None:
            return when.replace(tzinfo=ILS_TZ)
        return when

    def _daily_filename(self, when: datetime) -> str:
        return f"{when.strftime('%Y-%m-%d')}.md"

    def _weekly_bounds(self, day: date) -> tuple[date, date]:
        # Sunday-Saturday week.
        delta = (day.weekday() - 6) % 7
        start_date = day - timedelta(days=delta)
        return start_date, start_date + timedelta(days=6)

    def _weekly_label(self, day: date) -> str:
        start_date, end_date = self._weekly_bounds(day)
        first_week_end = self._weekly_bounds(date(end_date.year, 1, 1))[1]
        week_number = ((end_date - first_week_end).days // 7) + 1
        return f"{end_date.year}-week-{week_number:02d}"

    def _weekly_filename(self, when: datetime) -> str:
        return f"{self._weekly_label(when.date())}.md"

    def _format_frontmatter(self, lines: list[str]) -> str:
        return "---\n" + "\n".join(lines) + "\n---\n"

    def _daily_frontmatter(self, when: datetime, parsed: DailyCheckIn) -> str:
        lines = [
            "type: daily",
            f"date: {when.strftime('%Y-%m-%d')}",
            f"energy: {parsed.energy}",
            f"focus: {parsed.focus}",
            f"satisfaction: {parsed.satisfaction}",
            f"saved_at: {when.isoformat()}",
        ]
        return self._format_frontmatter(lines)

    def _weekly_frontmatter(self, when: datetime) -> str:
        week_start, week_end = self._weekly_bounds(when.date())
        lines = [
            "type: weekly",
            f"date: {when.strftime('%Y-%m-%d')}",
            f"week: {self._weekly_label(when.date())}",
            f"week_start: {week_start.isoformat()}",
            f"week_end: {week_end.isoformat()}",
            f"saved_at: {when.isoformat()}",
        ]
        return self._format_frontmatter(lines)

    def _write_atomic(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)

    def save_daily(
        self,
        raw: str,
        parsed: DailyCheckIn,
        *,
        when: datetime | None = None,
    ) -> Path:
        when = self._now(when)
        path = self.root / DAILY_DIR / self._daily_filename(when)
        content = self._daily_frontmatter(when, parsed) + raw
        self._write_atomic(path, content)
        return path

    def save_weekly(
        self,
        raw: str,
        parsed: WeeklyReview,
        *,
        when: datetime | None = None,
    ) -> Path:
        when = self._now(when)
        path = self.root / WEEKLY_DIR / self._weekly_filename(when)
        content = self._weekly_frontmatter(when) + raw
        self._write_atomic(path, content)
        return path
