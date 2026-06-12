import asyncio
from datetime import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.constants import ParseMode

import app
from messages import TemplateId


def _run(coro):
    asyncio.run(coro)


def _make_update(text: str = "") -> MagicMock:
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def _make_context(*, args: list[str] | None = None) -> MagicMock:
    context = MagicMock()
    context.args = [] if args is None else args
    context.user_data = {}
    return context


def _make_application(*, job_queue: MagicMock | None) -> MagicMock:
    application = MagicMock()
    application.bot_data = {}
    application.bot.set_my_commands = AsyncMock()
    application.job_queue = job_queue
    return application


@pytest.fixture
def clear_checkup_chat_id(monkeypatch):
    monkeypatch.delenv("CHECKUP_CHAT_ID", raising=False)


@pytest.fixture
def checkup_chat_id_env(monkeypatch):
    monkeypatch.setenv("CHECKUP_CHAT_ID", "424242")


def test_post_init_no_chat_id_skips_jobs(clear_checkup_chat_id):
    jq = MagicMock()
    application = _make_application(job_queue=jq)

    _run(app.post_init(application))

    application.bot.set_my_commands.assert_awaited_once_with(app.BOT_COMMANDS)
    jq.run_daily.assert_not_called()


def test_post_init_no_job_queue_warns(checkup_chat_id_env):
    application = _make_application(job_queue=None)

    _run(app.post_init(application))

    application.bot.set_my_commands.assert_awaited_once_with(app.BOT_COMMANDS)
    assert application.bot_data.get("checkup_chat_id") == 424242


def test_post_init_registers_daily_and_weekly(checkup_chat_id_env):
    jq = MagicMock()
    application = _make_application(job_queue=jq)

    _run(app.post_init(application))

    application.bot.set_my_commands.assert_awaited_once_with(app.BOT_COMMANDS)
    assert application.bot_data["checkup_chat_id"] == 424242
    assert jq.run_daily.call_count == 2

    daily_kw = jq.run_daily.call_args_list[0].kwargs
    assert daily_kw["time"] == time(21, 0, tzinfo=app.ILS_TZ)
    assert daily_kw["data"] == "daily"
    assert daily_kw["name"] == "daily_checkup_prompt"

    weekly_kw = jq.run_daily.call_args_list[1].kwargs
    assert weekly_kw["time"] == time(19, 0, tzinfo=app.ILS_TZ)
    assert weekly_kw["days"] == (6,)
    assert weekly_kw["data"] == "weekly"
    assert weekly_kw["name"] == "weekly_checkup_prompt"


def test_post_init_command_registration_failure_does_not_skip_reminders(checkup_chat_id_env):
    jq = MagicMock()
    application = _make_application(job_queue=jq)
    application.bot.set_my_commands.side_effect = RuntimeError("telegram unavailable")

    _run(app.post_init(application))

    application.bot.set_my_commands.assert_awaited_once_with(app.BOT_COMMANDS)
    assert application.bot_data["checkup_chat_id"] == 424242
    assert jq.run_daily.call_count == 2


def test_help_command_replies_with_compact_command_list():
    update = _make_update()
    context = _make_context(args=["ignored"])

    _run(app.help_command(update, context))

    update.message.reply_text.assert_awaited_once_with(
        app.message_renderer.render(TemplateId.TEXT, {"text_key": "help"}).text,
        parse_mode=ParseMode.HTML,
    )


def test_template_command_without_args_replies_with_usage():
    update = _make_update()
    context = _make_context()

    _run(app.template_command(update, context))

    update.message.reply_text.assert_awaited_once_with(
        app.message_renderer.render(TemplateId.TEXT, {"text_key": "template_usage"}).text,
        parse_mode=ParseMode.HTML,
    )
    assert context.user_data == {}


def test_template_command_replies_with_daily_template():
    update = _make_update()
    context = _make_context(args=["daily"])

    _run(app.template_command(update, context))

    reply = update.message.reply_text.await_args.args[0]
    assert "<b>Daily check-in template</b>" in reply
    assert "## Daily Check-In" in reply
    assert update.message.reply_text.await_args.kwargs["parse_mode"] == ParseMode.HTML
    assert context.user_data == {}


def test_template_command_replies_with_weekly_template():
    update = _make_update()
    context = _make_context(args=["weekly"])

    _run(app.template_command(update, context))

    reply = update.message.reply_text.await_args.args[0]
    assert "<b>Weekly review template</b>" in reply
    assert "## Weekly Review" in reply
    assert update.message.reply_text.await_args.kwargs["parse_mode"] == ParseMode.HTML
    assert context.user_data == {}


def test_template_command_invalid_args_replies_with_usage():
    update = _make_update()
    context = _make_context(args=["monthly"])

    _run(app.template_command(update, context))

    update.message.reply_text.assert_awaited_once_with(
        app.message_renderer.render(TemplateId.TEXT, {"text_key": "template_usage"}).text,
        parse_mode=ParseMode.HTML,
    )
    assert context.user_data == {}


def test_scheduled_prompt_daily():
    async def _body():
        context = MagicMock()
        context.bot_data = {"checkup_chat_id": 12345}
        context.job = MagicMock()
        context.job.data = "daily"
        context.bot.send_message = AsyncMock()
        await app.scheduled_checkup_prompt(context)
        context.bot.send_message.assert_awaited_once_with(
            chat_id=12345,
            text=app.message_renderer.render(
                TemplateId.TEXT, {"text_key": "daily_prompt"}
            ).text,
            parse_mode=ParseMode.HTML,
        )

    _run(_body())


def test_scheduled_prompt_weekly():
    async def _body():
        context = MagicMock()
        context.bot_data = {"checkup_chat_id": 99}
        context.job = MagicMock()
        context.job.data = "weekly"
        context.bot.send_message = AsyncMock()
        await app.scheduled_checkup_prompt(context)
        context.bot.send_message.assert_awaited_once_with(
            chat_id=99,
            text=app.message_renderer.render(
                TemplateId.TEXT, {"text_key": "weekly_prompt"}
            ).text,
            parse_mode=ParseMode.HTML,
        )

    _run(_body())
