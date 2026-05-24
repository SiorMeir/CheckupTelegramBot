import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from journal.store import ILS_TZ, JournalStore
from parser import DailyCheckIn, WeeklyReview

SAMPLE_DAILY_RAW = """## Daily Check-In

Energy: 7/10
Focus: 5/10
Satisfaction: 8/10
"""

SAMPLE_WEEKLY_RAW = """## Week 20 Review

Momentum:
- Shipped journal storage
"""


def _split_frontmatter(text: str) -> tuple[str, str]:
    assert text.startswith("---\n")
    rest = text[4:]
    end = rest.index("---\n")
    return rest[:end], rest[end + 4 :]


@pytest.fixture
def journal_root(tmp_path, monkeypatch):
    root = tmp_path / "journal"
    monkeypatch.setenv("JOURNAL_ROOT", str(root))
    return root


@pytest.fixture
def fixed_when():
    return datetime(2026, 5, 19, 21, 5, tzinfo=ILS_TZ)


@pytest.fixture
def daily_parsed():
    return DailyCheckIn(energy=7, focus=5, satisfaction=8)


@pytest.fixture
def weekly_parsed():
    return WeeklyReview(momentum=["Shipped journal storage"])


def test_creates_daily_file_in_expected_location(
    journal_root, fixed_when, daily_parsed
):
    store = JournalStore()
    path = store.save_daily(
        SAMPLE_DAILY_RAW, daily_parsed, when=fixed_when
    )

    assert path == journal_root / "daily" / "2026-05-19.md"
    assert path.is_file()


def test_writes_yaml_frontmatter_block_and_body_separator(
    journal_root, fixed_when, daily_parsed
):
    store = JournalStore()
    path = store.save_daily(
        SAMPLE_DAILY_RAW, daily_parsed, when=fixed_when
    )
    text = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(text)

    assert frontmatter
    assert body == SAMPLE_DAILY_RAW


def test_daily_frontmatter_contains_expected_keys(
    journal_root, fixed_when, daily_parsed
):
    store = JournalStore()
    path = store.save_daily(
        SAMPLE_DAILY_RAW,
        daily_parsed,
        when=fixed_when,
    )
    frontmatter, _ = _split_frontmatter(path.read_text(encoding="utf-8"))

    assert "type: daily" in frontmatter
    assert "date: 2026-05-19" in frontmatter
    assert "energy: 7" in frontmatter
    assert "focus: 5" in frontmatter
    assert "satisfaction: 8" in frontmatter
    assert "saved_at:" in frontmatter


def test_weekly_frontmatter_is_yaml_parseable(
    journal_root, fixed_when, weekly_parsed
):
    iso = fixed_when.isocalendar()
    week_label = f"{iso.year}-week-{iso.week:02d}"

    store = JournalStore()
    path = store.save_weekly(
        SAMPLE_WEEKLY_RAW, weekly_parsed, when=fixed_when
    )
    frontmatter, body = _split_frontmatter(path.read_text(encoding="utf-8"))

    assert "type: weekly" in frontmatter
    assert f"week: {week_label}" in frontmatter
    assert "[" not in frontmatter
    assert "'" not in frontmatter
    assert body == SAMPLE_WEEKLY_RAW


def test_creates_directories_if_missing(
    journal_root, fixed_when, daily_parsed
):
    journal_root.mkdir(parents=True, exist_ok=True)
    assert not (journal_root / "daily").exists()

    store = JournalStore()
    store.save_daily(SAMPLE_DAILY_RAW, daily_parsed, when=fixed_when)

    assert (journal_root / "daily").is_dir()


def test_write_is_atomic(journal_root, fixed_when, daily_parsed, monkeypatch):
    store = JournalStore()
    path = store.save_daily("first", daily_parsed, when=fixed_when)
    assert path.read_text(encoding="utf-8").endswith("first")

    original_replace = os.replace

    def fail_replace(src, dst):
        if Path(dst) == path:
            raise OSError("disk full")
        return original_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError):
        store.save_daily("second", daily_parsed, when=fixed_when)

    assert path.read_text(encoding="utf-8").endswith("first")


def test_weekly_file_uses_iso_week_filename(
    journal_root, fixed_when, weekly_parsed
):
    iso = fixed_when.isocalendar()
    expected_name = f"{iso.year}-week-{iso.week:02d}.md"

    store = JournalStore()
    path = store.save_weekly(
        SAMPLE_WEEKLY_RAW, weekly_parsed, when=fixed_when
    )

    assert path == journal_root / "weekly" / expected_name
