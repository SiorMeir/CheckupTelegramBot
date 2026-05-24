import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

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
    assert "Parsed daily check-in" in update.message.reply_text.await_args.args[0]


def test_daily_store_failure_does_not_crash_handler(monkeypatch):
    store = MagicMock()
    store.save_daily.side_effect = OSError("disk full")
    monkeypatch.setattr(app, "journal_store", store)

    update = _make_update(DAILY_MARKDOWN)
    context = _make_context()

    _run(app.handle_daily_checkin_text(update, context))

    reply = update.message.reply_text.await_args.args[0]
    assert "Parsed daily check-in" in reply
    assert "could not save to journal" in reply


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
    assert "Parsed weekly review" in update.message.reply_text.await_args.args[0]


def test_weekly_store_failure_does_not_crash_handler(monkeypatch):
    store = MagicMock()
    store.save_weekly.side_effect = OSError("disk full")
    monkeypatch.setattr(app, "journal_store", store)

    update = _make_update(WEEKLY_MARKDOWN)
    context = _make_context()

    _run(app.handle_weekly_review_text(update, context))

    reply = update.message.reply_text.await_args.args[0]
    assert "Parsed weekly review" in reply
    assert "could not save to journal" in reply
