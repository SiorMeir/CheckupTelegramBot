import asyncio
from unittest.mock import AsyncMock, MagicMock
from datetime import date
import app
from journal.read import DailyCollection, DailyEntry


def _run(coro):
    asyncio.run(coro)


def _make_update() -> MagicMock:
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    return update


def _make_context(args: list[str]) -> MagicMock:
    context = MagicMock()
    context.args = args
    return context


def test_statistics_command_uses_default_period(monkeypatch):
    update = _make_update()
    context = _make_context([])
    collection = DailyCollection(
        entries=[
            DailyEntry(entry_date=date(2026, 5, 24), energy=7, focus=6, satisfaction=8),
            DailyEntry(entry_date=date(2026, 5, 25), energy=5, focus=4, satisfaction=6),
        ],
        target_days=28,
    )
    reader = MagicMock()
    reader.collect_daily.return_value = collection
    monkeypatch.setattr(app, "journal_reader", reader)

    _run(app.statistics_command(update, context))

    reader.collect_daily.assert_called_once_with(28)
    reply = update.message.reply_text.await_args.args[0]
    assert "Statistics · 4w" in reply
    assert "Partial: 2 of 28 days" in reply


def test_statistics_command_supports_explicit_period(monkeypatch):
    update = _make_update()
    context = _make_context(["5d"])
    collection = DailyCollection(
        entries=[
            DailyEntry(entry_date=date(2026, 5, 21), energy=5, focus=5, satisfaction=5),
            DailyEntry(entry_date=date(2026, 5, 22), energy=6, focus=6, satisfaction=6),
            DailyEntry(entry_date=date(2026, 5, 23), energy=7, focus=7, satisfaction=7),
            DailyEntry(entry_date=date(2026, 5, 24), energy=8, focus=8, satisfaction=8),
            DailyEntry(entry_date=date(2026, 5, 25), energy=9, focus=9, satisfaction=9),
        ],
        target_days=5,
    )
    reader = MagicMock()
    reader.collect_daily.return_value = collection
    monkeypatch.setattr(app, "journal_reader", reader)

    _run(app.statistics_command(update, context))

    reader.collect_daily.assert_called_once_with(5)
    reply = update.message.reply_text.await_args.args[0]
    assert "Statistics · 5d" in reply
    assert "5 days · 2026-05-21 – 2026-05-25" in reply


def test_statistics_command_rejects_invalid_args():
    update = _make_update()
    context = _make_context(["2", "weeks"])

    _run(app.statistics_command(update, context))

    assert update.message.reply_text.await_args.args[0] == app.STATISTICS_USAGE


def test_statistics_command_reports_no_data(monkeypatch):
    update = _make_update()
    context = _make_context(["2w"])
    reader = MagicMock()
    reader.collect_daily.return_value = DailyCollection(entries=[], target_days=14)
    monkeypatch.setattr(app, "journal_reader", reader)

    _run(app.statistics_command(update, context))

    assert update.message.reply_text.await_args.args[0] == "No daily entries for 2w."
