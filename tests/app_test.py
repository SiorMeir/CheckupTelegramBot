import asyncio
from datetime import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import (
    DAILY_PROMPT,
    ILS_TZ,
    WEEKLY_PROMPT,
    post_init,
    scheduled_checkup_prompt,
)


def _run(coro):
    asyncio.run(coro)


@pytest.fixture
def clear_checkup_chat_id(monkeypatch):
    monkeypatch.delenv("CHECKUP_CHAT_ID", raising=False)


@pytest.fixture
def checkup_chat_id_env(monkeypatch):
    monkeypatch.setenv("CHECKUP_CHAT_ID", "424242")


def test_post_init_no_chat_id_skips_jobs(clear_checkup_chat_id):
    app = MagicMock()
    app.bot_data = {}
    jq = MagicMock()
    app.job_queue = jq

    _run(post_init(app))

    jq.run_daily.assert_not_called()


def test_post_init_no_job_queue_warns(checkup_chat_id_env):
    app = MagicMock()
    app.bot_data = {}
    app.job_queue = None

    _run(post_init(app))

    assert app.bot_data.get("checkup_chat_id") == 424242


def test_post_init_registers_daily_and_weekly(checkup_chat_id_env):
    app = MagicMock()
    app.bot_data = {}
    jq = MagicMock()
    app.job_queue = jq

    _run(post_init(app))

    assert app.bot_data["checkup_chat_id"] == 424242
    assert jq.run_daily.call_count == 2

    daily_kw = jq.run_daily.call_args_list[0].kwargs
    assert daily_kw["time"] == time(21, 0, tzinfo=ILS_TZ)
    assert daily_kw["data"] == "daily"
    assert daily_kw["name"] == "daily_checkup_prompt"

    weekly_kw = jq.run_daily.call_args_list[1].kwargs
    assert weekly_kw["time"] == time(19, 0, tzinfo=ILS_TZ)
    assert weekly_kw["days"] == (6,)
    assert weekly_kw["data"] == "weekly"
    assert weekly_kw["name"] == "weekly_checkup_prompt"



def test_scheduled_prompt_daily():
    async def _body():
        context = MagicMock()
        context.bot_data = {"checkup_chat_id": 12345}
        context.job = MagicMock()
        context.job.data = "daily"
        context.bot.send_message = AsyncMock()
        await scheduled_checkup_prompt(context)
        context.bot.send_message.assert_awaited_once_with(
            chat_id=12345,
            text=DAILY_PROMPT,
        )

    _run(_body())


def test_scheduled_prompt_weekly():
    async def _body():
        context = MagicMock()
        context.bot_data = {"checkup_chat_id": 99}
        context.job = MagicMock()
        context.job.data = "weekly"
        context.bot.send_message = AsyncMock()
        await scheduled_checkup_prompt(context)
        context.bot.send_message.assert_awaited_once_with(
            chat_id=99,
            text=WEEKLY_PROMPT,
        )

    _run(_body())
