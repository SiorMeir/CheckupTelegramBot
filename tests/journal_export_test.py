from datetime import date, datetime
from zipfile import ZipFile

from journal.export import build_journal_archive
from journal.read import JournalReader
from journal.store import ILS_TZ, JournalStore
from parser import DailyCheckIn, WeeklyReview

SAMPLE_DAILY_RAW = """## Daily Check-In

Energy: 7/10
Focus: 6/10
Satisfaction: 8/10
"""

SAMPLE_WEEKLY_RAW = """## Week 21 Review

Momentum:
- Stayed consistent
"""


def _save_daily(store: JournalStore, entry_date: date) -> None:
    store.save_daily(
        SAMPLE_DAILY_RAW,
        DailyCheckIn(energy=7, focus=6, satisfaction=8),
        when=datetime(entry_date.year, entry_date.month, entry_date.day, 20, 0, tzinfo=ILS_TZ),
    )


def _save_weekly(store: JournalStore, entry_date: date) -> None:
    store.save_weekly(
        SAMPLE_WEEKLY_RAW,
        WeeklyReview(momentum=["Stayed consistent"]),
        when=datetime(entry_date.year, entry_date.month, entry_date.day, 19, 0, tzinfo=ILS_TZ),
    )


def test_build_journal_archive_zips_all_markdown_files_with_journal_prefix(tmp_path):
    root = tmp_path / "journal"
    store = JournalStore(root)
    reader = JournalReader(store)

    _save_daily(store, date(2026, 5, 19))
    _save_weekly(store, date(2026, 5, 23))

    archive = build_journal_archive(store, reader.scan_journal(today=date(2026, 6, 1)))

    assert archive.status == "ready"
    assert archive.file_count == 2
    assert archive.archive_path is not None
    assert archive.archive_path.exists()

    with ZipFile(archive.archive_path) as zip_file:
        assert sorted(zip_file.namelist()) == [
            "journal/daily/2026-05-19.md",
            "journal/weekly/2026-week-21.md",
        ]

    archive.archive_path.unlink()


def test_build_journal_archive_persists_oversized_archives_under_exports(tmp_path):
    root = tmp_path / "journal"
    store = JournalStore(root)
    reader = JournalReader(store)

    _save_daily(store, date(2026, 5, 19))

    archive = build_journal_archive(
        store,
        reader.scan_journal(today=date(2026, 6, 1)),
        upload_limit=1,
    )

    assert archive.status == "too_large"
    assert archive.archive_path is not None
    assert archive.archive_path.exists()
    assert archive.archive_path.parent == root / "exports"
