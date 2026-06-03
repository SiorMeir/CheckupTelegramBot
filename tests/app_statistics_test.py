import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock

from telegram.constants import ParseMode

import app
from journal.read import DailyCollection, DailyEntry
from messages import TemplateId


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
    assert "<b>Statistics | 4w</b>" in reply
    assert "Partial: 2 of 28 days | 2026-05-24 - 2026-05-25" in reply
    assert update.message.reply_text.await_args.kwargs["parse_mode"] == ParseMode.HTML


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
    assert "<b>Statistics | 5d</b>" in reply
    assert "5 days | 2026-05-21 - 2026-05-25" in reply
    assert update.message.reply_text.await_args.kwargs["parse_mode"] == ParseMode.HTML


def test_statistics_command_rejects_invalid_args():
    update = _make_update()
    context = _make_context(["2", "weeks"])

    _run(app.statistics_command(update, context))

    assert (
        update.message.reply_text.await_args.args[0]
        == app.message_renderer.render(TemplateId.TEXT, {"text_key": "statistics_usage"}).text
    )
    assert update.message.reply_text.await_args.kwargs["parse_mode"] == ParseMode.HTML


def test_statistics_command_reports_no_data(monkeypatch):
    update = _make_update()
    context = _make_context(["2w"])
    reader = MagicMock()
    reader.collect_daily.return_value = DailyCollection(entries=[], target_days=14)
    monkeypatch.setattr(app, "journal_reader", reader)

    _run(app.statistics_command(update, context))

    assert update.message.reply_text.await_args.args[0] == "No daily entries for 2w."
    assert update.message.reply_text.await_args.kwargs["parse_mode"] == ParseMode.HTML
