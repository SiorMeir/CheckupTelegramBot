from datetime import date, datetime

from journal.period import parse_review_period
from journal.read import JournalReader
from journal.store import ILS_TZ, JournalStore
from parser import DailyCheckIn, WeeklyReview

SAMPLE_DAILY_RAW = """## Daily Check-In

Energy: 7/10
Focus: 6/10
Satisfaction: 8/10

What did I actually do today?
- Shipped something

What felt meaningful?
- Progress

What drained me?
- Interruptions

What should tomorrow focus on?
- Keep going
"""

SAMPLE_WEEKLY_RAW = """## Week 21 Review

Momentum:
- Stayed consistent

Friction:
- Lost time to context switching

Avoidance:
- Avoided a hard task

Meaningful:
- Kept journaling

Fake productivity:
- Tweaked details

Next Week Focus:
- Protect focus
"""


def _save_daily(store: JournalStore, entry_date: date) -> None:
    store.save_daily(
        SAMPLE_DAILY_RAW,
        DailyCheckIn(
            energy=7,
            focus=6,
            satisfaction=8,
            did_today=["Shipped something"],
            meaningful=["Progress"],
            drained=["Interruptions"],
            tomorrow_focus=["Keep going"],
        ),
        when=datetime(entry_date.year, entry_date.month, entry_date.day, 20, 0, tzinfo=ILS_TZ),
    )


def _save_weekly(store: JournalStore, entry_date: date) -> None:
    store.save_weekly(
        SAMPLE_WEEKLY_RAW,
        WeeklyReview(
            momentum=["Stayed consistent"],
            friction=["Lost time to context switching"],
            avoidance=["Avoided a hard task"],
            meaningful=["Kept journaling"],
            fake_productivity=["Tweaked details"],
            next_week_focus=["Protect focus"],
        ),
        when=datetime(entry_date.year, entry_date.month, entry_date.day, 19, 0, tzinfo=ILS_TZ),
    )


def test_collect_review_uses_partial_data(tmp_path):
    root = tmp_path / "journal"
    store = JournalStore(root)
    reader = JournalReader(store)

    for entry_date in [
        date(2026, 5, 18),
        date(2026, 5, 19),
        date(2026, 5, 20),
        date(2026, 5, 21),
        date(2026, 5, 22),
        date(2026, 5, 23),
        date(2026, 5, 24),
        date(2026, 5, 25),
        date(2026, 5, 26),
        date(2026, 5, 28),
        date(2026, 5, 30),
        date(2026, 5, 31),
        date(2026, 6, 1),
    ]:
        _save_daily(store, entry_date)

    _save_weekly(store, date(2026, 5, 18))
    _save_weekly(store, date(2026, 5, 31))

    period = parse_review_period("2w", today=date(2026, 6, 1))
    collection = reader.collect_review(period)

    assert collection.coverage.expected_daily_days == 14
    assert collection.coverage.found_daily_count == 12
    assert collection.coverage.found_weekly_count == 1
    assert collection.coverage.missing_day_estimate == 2
    assert collection.daily_entries[0].entry_date == date(2026, 5, 19)
    assert collection.daily_entries[-1].entry_date == date(2026, 6, 1)
    assert collection.weekly_entries[0].saved_date == date(2026, 5, 31)
    assert collection.daily_averages.energy == 7


def test_collect_review_supports_legacy_weekly_frontmatter(tmp_path):
    root = tmp_path / "journal"
    weekly_dir = root / "weekly"
    weekly_dir.mkdir(parents=True)
    (weekly_dir / "2026-week-21.md").write_text(
        "---\n"
        "type: weekly\n"
        "date: 2026-05-23\n"
        "week: 2026-week-21\n"
        "saved_at: 2026-05-23T19:00:00+03:00\n"
        "---\n"
        + SAMPLE_WEEKLY_RAW,
        encoding="utf-8",
    )

    reader = JournalReader(JournalStore(root))
    period = parse_review_period("2w", today=date(2026, 6, 1))
    collection = reader.collect_review(period)

    assert len(collection.weekly_entries) == 1
    assert collection.weekly_entries[0].saved_date == date(2026, 5, 23)
