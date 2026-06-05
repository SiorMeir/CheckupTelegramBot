from datetime import date, datetime

from journal.read import JournalReader
from journal.store import ILS_TZ, JournalStore
from parser import DailyCheckIn, WeeklyReview

SAMPLE_DAILY_RAW = """## Daily Check-In

Energy: 7/10
Focus: 6/10
Satisfaction: 8/10

What did I actually do today?
- Shipped something
"""

SAMPLE_WEEKLY_RAW = """## Week 21 Review

Momentum:
- Stayed consistent
"""


def _save_daily(store: JournalStore, entry_date: date) -> None:
    store.save_daily(
        SAMPLE_DAILY_RAW,
        DailyCheckIn(energy=7, focus=6, satisfaction=8, did_today=["Shipped something"]),
        when=datetime(entry_date.year, entry_date.month, entry_date.day, 20, 0, tzinfo=ILS_TZ),
    )


def _save_weekly(store: JournalStore, entry_date: date) -> None:
    store.save_weekly(
        SAMPLE_WEEKLY_RAW,
        WeeklyReview(momentum=["Stayed consistent"]),
        when=datetime(entry_date.year, entry_date.month, entry_date.day, 19, 0, tzinfo=ILS_TZ),
    )


def test_scan_journal_counts_only_valid_entries_and_tracks_oldest(tmp_path):
    root = tmp_path / "journal"
    store = JournalStore(root)
    reader = JournalReader(store)

    _save_daily(store, date(2026, 5, 19))
    _save_weekly(store, date(2026, 5, 23))

    (root / "daily").mkdir(parents=True, exist_ok=True)
    (root / "daily" / "bad-name.md").write_text(SAMPLE_DAILY_RAW, encoding="utf-8")
    (root / "weekly" / "2026-week-22.md").write_text(
        "---\n"
        "type: weekly\n"
        "date: 2026-05-30\n"
        "week: 2026-week-22\n"
        "---\n"
        "not a weekly review\n",
        encoding="utf-8",
    )

    scan = reader.scan_journal(today=date(2026, 6, 1))

    assert len(scan.records) == 4
    assert len(scan.valid_daily_records) == 1
    assert len(scan.valid_weekly_records) == 1
    assert scan.valid_daily_dates == [date(2026, 5, 19)]
    assert scan.valid_weekly_weeks == ["2026-week-21"]
    assert scan.oldest_valid_entry_date == date(2026, 5, 19)


def test_collect_log_report_verbose_groups_missing_days_and_missing_weekly_reviews(tmp_path):
    root = tmp_path / "journal"
    store = JournalStore(root)
    reader = JournalReader(store)

    for entry_date in [
        date(2026, 5, 19),
        date(2026, 5, 20),
        date(2026, 5, 22),
        date(2026, 5, 24),
        date(2026, 5, 25),
        date(2026, 5, 26),
        date(2026, 5, 28),
        date(2026, 5, 29),
        date(2026, 5, 31),
        date(2026, 6, 1),
    ]:
        _save_daily(store, entry_date)

    _save_weekly(store, date(2026, 5, 23))

    report = reader.collect_log_report(today=date(2026, 6, 1), verbose=True)

    assert report.daily_count == 10
    assert report.weekly_count == 1
    assert report.oldest_entry_date == date(2026, 5, 19)
    assert [gap.week_label for gap in report.weekly_gaps] == ["2026-week-21", "2026-week-22"]
    assert report.weekly_gaps[0].missing_daily_dates == [date(2026, 5, 21), date(2026, 5, 23)]
    assert report.weekly_gaps[0].missing_weekly_review is False
    assert report.weekly_gaps[1].missing_daily_dates == [date(2026, 5, 27), date(2026, 5, 30)]
    assert report.weekly_gaps[1].missing_weekly_review is True


def test_collect_log_report_supports_legacy_weekly_frontmatter(tmp_path):
    root = tmp_path / "journal"
    weekly_dir = root / "weekly"
    weekly_dir.mkdir(parents=True)
    (weekly_dir / "2026-week-21.md").write_text(
        "---\n"
        "type: weekly\n"
        "date: 2026-05-23\n"
        "week: 2026-week-21\n"
        "---\n"
        + SAMPLE_WEEKLY_RAW,
        encoding="utf-8",
    )

    reader = JournalReader(JournalStore(root))
    scan = reader.scan_journal(today=date(2026, 6, 1))

    assert scan.valid_weekly_weeks == ["2026-week-21"]
    weekly_record = scan.valid_weekly_records[0]
    assert weekly_record.week_start == date(2026, 5, 17)
    assert weekly_record.week_end == date(2026, 5, 23)
