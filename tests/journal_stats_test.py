from datetime import date

from journal.read import JournalReader
from journal.stats import compute_daily_averages, format_statistics_report
from journal.store import JournalStore


def _write_daily(root, entry_date: date, frontmatter: str, body: str = "## Daily Check-In\n"):
    daily_dir = root / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    path = daily_dir / f"{entry_date.isoformat()}.md"
    path.write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
    return path


def test_collect_daily_extends_lookback_across_missing_days(tmp_path):
    root = tmp_path / "journal"
    _write_daily(
        root,
        date(2026, 5, 25),
        "type: daily\nenergy: 7\nfocus: 5\nsatisfaction: 8",
    )
    _write_daily(
        root,
        date(2026, 5, 23),
        "type: daily\nenergy: 6\nfocus: 6\nsatisfaction: 7",
    )
    _write_daily(
        root,
        date(2026, 5, 20),
        "type: daily\nenergy: 5\nfocus: 7\nsatisfaction: 6",
    )

    reader = JournalReader(JournalStore(root))
    collection = reader.collect_daily(3, today=date(2026, 5, 25))

    assert collection.found == 3
    assert collection.date_min == date(2026, 5, 20)
    assert collection.date_max == date(2026, 5, 25)


def test_collect_daily_skips_malformed_files_and_ignores_non_daily(tmp_path):
    root = tmp_path / "journal"
    _write_daily(
        root,
        date(2026, 5, 25),
        "type: daily\nenergy: 7\nfocus: 5\nsatisfaction: 8",
    )
    _write_daily(
        root,
        date(2026, 5, 24),
        "type: weekly\nenergy: 6\nfocus: 6\nsatisfaction: 7",
    )
    _write_daily(
        root,
        date(2026, 5, 23),
        "type: daily\nenergy: nope\nfocus: 4\nsatisfaction: 5",
    )

    reader = JournalReader(JournalStore(root))
    collection = reader.collect_daily(3, today=date(2026, 5, 25))

    assert collection.found == 1
    assert collection.date_min == date(2026, 5, 25)
    assert collection.date_max == date(2026, 5, 25)


def test_collect_daily_returns_empty_for_missing_journal(tmp_path):
    reader = JournalReader(JournalStore(tmp_path / "journal"))

    collection = reader.collect_daily(5, today=date(2026, 5, 25))

    assert collection.found == 0
    assert collection.date_min is None
    assert collection.date_max is None


def test_compute_and_format_full_statistics_report(tmp_path):
    root = tmp_path / "journal"
    _write_daily(
        root,
        date(2026, 5, 24),
        "type: daily\nenergy: 7\nfocus: 5\nsatisfaction: 8",
    )
    _write_daily(
        root,
        date(2026, 5, 25),
        "type: daily\nenergy: 5\nfocus: 7\nsatisfaction: 6",
    )
    reader = JournalReader(JournalStore(root))
    collection = reader.collect_daily(2, today=date(2026, 5, 25))

    averages = compute_daily_averages(collection)
    report = format_statistics_report("2d", collection)

    assert averages is not None
    assert averages.energy == 6.0
    assert averages.focus == 6.0
    assert averages.satisfaction == 7.0
    assert "Statistics · 2d" in report
    assert "2 days · 2026-05-24 – 2026-05-25" in report
    assert "Energy 6.0 · Focus 6.0 · Satisfaction 7.0" in report


def test_format_partial_and_empty_statistics_report(tmp_path):
    root = tmp_path / "journal"
    _write_daily(
        root,
        date(2026, 5, 25),
        "type: daily\nenergy: 8\nfocus: 6\nsatisfaction: 7",
    )
    reader = JournalReader(JournalStore(root))

    partial_collection = reader.collect_daily(3, today=date(2026, 5, 25))
    partial_report = format_statistics_report("3d", partial_collection)
    empty_report = format_statistics_report(
        "4w",
        reader.collect_daily(28, today=date(2026, 5, 1)),
    )

    assert "Partial: 1 of 3 days · 2026-05-25 – 2026-05-25" in partial_report
    assert "Energy 8.0 · Focus 6.0 · Satisfaction 7.0" in partial_report
    assert empty_report == "No daily entries for 4w."
