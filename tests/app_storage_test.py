import asyncio
from unittest.mock import AsyncMock, MagicMock

from telegram.constants import ParseMode

import app
from parser import DailyCheckIn, WeeklyReview

DAILY_MARKDOWN = """
## Daily Check-In

Energy: 7/10
Focus: 5/10
Satisfaction: 8/10
"""

WEEKLY_MARKDOWN = """
## Week 2 Review

Momentum:
- Daily coding sessions worked well
"""


def _run(coro):
    asyncio.run(coro)


def _make_update(text: str) -> MagicMock:
    update = MagicMock()
    update.message.text = text.strip()
    update.message.reply_text = AsyncMock()
    return update


def _make_context() -> MagicMock:
    context = MagicMock()
    context.user_data = {}
    return context


def test_daily_handler_calls_store_on_valid_daily(monkeypatch):
    store = MagicMock()
    store.save_daily.return_value = MagicMock()
    monkeypatch.setattr(app, "journal_store", store)

    update = _make_update(DAILY_MARKDOWN)
    context = _make_context()

    _run(app.handle_daily_checkin_text(update, context))

    store.save_daily.assert_called_once()
    args, kwargs = store.save_daily.call_args
    assert args[0] == update.message.text
    assert isinstance(args[1], DailyCheckIn)
    assert kwargs == {}
    update.message.reply_text.assert_awaited_once()
    reply = update.message.reply_text.await_args.args[0]
    assert "Detected as daily." in reply
    assert "<b>Parsed daily check-in</b>" in reply
    assert "<i>(none)</i>" in reply
    assert update.message.reply_text.await_args.kwargs["parse_mode"] == ParseMode.HTML


def test_daily_store_failure_does_not_crash_handler(monkeypatch):
    store = MagicMock()
    store.save_daily.side_effect = OSError("disk full")
    monkeypatch.setattr(app, "journal_store", store)

    update = _make_update(DAILY_MARKDOWN)
    context = _make_context()

    _run(app.handle_daily_checkin_text(update, context))

    reply = update.message.reply_text.await_args.args[0]
    assert "Detected as daily." in reply
    assert "<b>Parsed daily check-in</b>" in reply
    assert "could not save to journal" in reply
    assert update.message.reply_text.await_args.kwargs["parse_mode"] == ParseMode.HTML


def test_weekly_handler_calls_store_on_valid_weekly(monkeypatch):
    store = MagicMock()
    store.save_weekly.return_value = MagicMock()
    monkeypatch.setattr(app, "journal_store", store)

    update = _make_update(WEEKLY_MARKDOWN)
    context = _make_context()

    _run(app.handle_weekly_review_text(update, context))

    store.save_weekly.assert_called_once()
    args, kwargs = store.save_weekly.call_args
    assert args[0] == update.message.text
    assert isinstance(args[1], WeeklyReview)
    assert kwargs == {}
    update.message.reply_text.assert_awaited_once()
    reply = update.message.reply_text.await_args.args[0]
    assert "Detected as weekly." in reply
    assert "<b>Parsed weekly review</b>" in reply
    assert "<ul>" in reply
    assert update.message.reply_text.await_args.kwargs["parse_mode"] == ParseMode.HTML


def test_weekly_store_failure_does_not_crash_handler(monkeypatch):
    store = MagicMock()
    store.save_weekly.side_effect = OSError("disk full")
    monkeypatch.setattr(app, "journal_store", store)

    update = _make_update(WEEKLY_MARKDOWN)
    context = _make_context()

    _run(app.handle_weekly_review_text(update, context))

    reply = update.message.reply_text.await_args.args[0]
    assert "Detected as weekly." in reply
    assert "<b>Parsed weekly review</b>" in reply
    assert "could not save to journal" in reply
    assert update.message.reply_text.await_args.kwargs["parse_mode"] == ParseMode.HTML


def test_text_message_auto_detects_and_saves_daily(monkeypatch):
    store = MagicMock()
    store.save_daily.return_value = MagicMock()
    monkeypatch.setattr(app, "journal_store", store)

    update = _make_update(DAILY_MARKDOWN)
    context = _make_context()

    _run(app.text_message(update, context))

    store.save_daily.assert_called_once()
    store.save_weekly.assert_not_called()
    reply = update.message.reply_text.await_args.args[0]
    assert "Detected as daily." in reply
    assert update.message.reply_text.await_args.kwargs["parse_mode"] == ParseMode.HTML


def test_text_message_auto_detects_and_saves_weekly(monkeypatch):
    store = MagicMock()
    store.save_weekly.return_value = MagicMock()
    monkeypatch.setattr(app, "journal_store", store)

    update = _make_update(WEEKLY_MARKDOWN)
    context = _make_context()

    _run(app.text_message(update, context))

    store.save_weekly.assert_called_once()
    store.save_daily.assert_not_called()
    reply = update.message.reply_text.await_args.args[0]
    assert "Detected as weekly." in reply
    assert update.message.reply_text.await_args.kwargs["parse_mode"] == ParseMode.HTML


def test_text_message_unknown_payload_is_rejected(monkeypatch):
    store = MagicMock()
    monkeypatch.setattr(app, "journal_store", store)

    update = _make_update("hello world")
    context = _make_context()

    _run(app.text_message(update, context))

    store.save_daily.assert_not_called()
    store.save_weekly.assert_not_called()
    reply = update.message.reply_text.await_args.args[0]
    assert "couldn't recognize" in reply
    assert "/daily or /weekly" in reply
    assert update.message.reply_text.await_args.kwargs["parse_mode"] == ParseMode.HTML


def test_daily_override_rejects_weekly_payload(monkeypatch):
    store = MagicMock()
    monkeypatch.setattr(app, "journal_store", store)

    update = _make_update(WEEKLY_MARKDOWN)
    context = _make_context()
    context.user_data[app.AWAITING_DAILY] = True

    _run(app.text_message(update, context))

    store.save_daily.assert_not_called()
    store.save_weekly.assert_not_called()
    reply = update.message.reply_text.await_args.args[0]
    assert "looks like a weekly review" in reply
    assert context.user_data[app.AWAITING_DAILY] is True
    assert update.message.reply_text.await_args.kwargs["parse_mode"] == ParseMode.HTML


def test_weekly_override_rejects_daily_payload(monkeypatch):
    store = MagicMock()
    monkeypatch.setattr(app, "journal_store", store)

    update = _make_update(DAILY_MARKDOWN)
    context = _make_context()
    context.user_data[app.AWAITING_WEEKLY] = True

    _run(app.text_message(update, context))

    store.save_daily.assert_not_called()
    store.save_weekly.assert_not_called()
    reply = update.message.reply_text.await_args.args[0]
    assert "looks like a daily check-in" in reply
    assert context.user_data[app.AWAITING_WEEKLY] is True
    assert update.message.reply_text.await_args.kwargs["parse_mode"] == ParseMode.HTML
