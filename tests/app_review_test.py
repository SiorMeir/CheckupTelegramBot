import asyncio
import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock

from telegram.constants import MessageLimit, ParseMode
from telegram.error import BadRequest

import app
from journal.period import ReviewPeriodSpec
from journal.read import (
    DailyAveragesSummary,
    ReviewCollection,
    ReviewCoverage,
    ReviewDailyEntry,
    ReviewWeeklyEntry,
)
from messages import TemplateId
from review.llm import (
    LLMConfig,
    LLMConfigError,
    LLMRequestError,
    LLMRequestTooLargeError,
    LLMResult,
)


def _run(coro):
    asyncio.run(coro)


def _make_update() -> MagicMock:
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    update.message.reply_document = AsyncMock()
    return update


def _make_context(args: list[str]) -> MagicMock:
    context = MagicMock()
    context.args = args
    context.user_data = {}
    return context


def _sample_collection() -> ReviewCollection:
    return ReviewCollection(
        period=ReviewPeriodSpec(
            raw_token="2w",
            target_days=14,
            start_date=date(2026, 5, 19),
            end_date=date(2026, 6, 1),
        ),
        daily_entries=[
            ReviewDailyEntry(
                entry_date=date(2026, 5, 19),
                energy=7,
                focus=6,
                satisfaction=8,
                did_today=["Shipped something"],
                meaningful=["Progress"],
                drained=["Interruptions"],
                tomorrow_focus=["Keep going"],
            )
        ],
        weekly_entries=[
            ReviewWeeklyEntry(
                week="2026-week-21",
                saved_date=date(2026, 5, 31),
                momentum=["Stayed consistent"],
                friction=["Context switching"],
                avoidance=["Avoided hard task"],
                meaningful=["Kept journaling"],
                fake_productivity=["Tweaked details"],
                next_week_focus=["Protect focus"],
            )
        ],
        coverage=ReviewCoverage(
            expected_daily_days=14,
            found_daily_count=12,
            found_weekly_count=1,
            missing_day_estimate=2,
        ),
        daily_averages=DailyAveragesSummary(
            energy=7.0,
            focus=6.0,
            satisfaction=8.0,
        ),
    )


def test_review_command_rejects_invalid_args():
    update = _make_update()
    context = _make_context(["2w", "extra"])

    _run(app.review_command(update, context))

    assert (
        update.message.reply_text.await_args.args[0]
        == app.message_renderer.render(TemplateId.TEXT, {"text_key": "review_usage"}).text
    )
    assert update.message.reply_text.await_args.kwargs["parse_mode"] == ParseMode.HTML
    assert update.message.reply_text.await_count == 1


def test_review_command_reports_no_data(monkeypatch):
    update = _make_update()
    context = _make_context(["2w"])
    reader = MagicMock()
    reader.collect_review.return_value = ReviewCollection(
        period=ReviewPeriodSpec("2w", 14, date(2026, 5, 19), date(2026, 6, 1)),
        daily_entries=[],
        weekly_entries=[],
        coverage=ReviewCoverage(14, 0, 0, 14),
        daily_averages=DailyAveragesSummary(None, None, None),
    )
    monkeypatch.setattr(app, "journal_reader", reader)

    _run(app.review_command(update, context))

    assert update.message.reply_text.await_args.args[0] == "No journal entries for 2w."
    assert update.message.reply_text.await_args.kwargs["parse_mode"] == ParseMode.HTML
    assert update.message.reply_text.await_count == 1


def test_review_command_reports_token_cap_failure(monkeypatch):
    update = _make_update()
    context = _make_context(["2w"])
    context.user_data[app.REVIEW_CONTEXT] = "Watch context switching."
    monkeypatch.setattr(
        app,
        "journal_reader",
        MagicMock(collect_review=MagicMock(return_value=_sample_collection())),
    )
    monkeypatch.setattr(
        app,
        "load_llm_config_from_env",
        MagicMock(
            return_value=LLMConfig(
                provider="LOCAL",
                model="test-model",
                base_url="http://localhost:1234/v1",
                api_key=None,
                timeout_seconds=60,
                max_input_tokens=8000,
            )
        ),
    )
    monkeypatch.setattr(
        app,
        "ensure_input_token_budget",
        MagicMock(side_effect=LLMRequestTooLargeError("too large")),
    )

    _run(app.review_command(update, context))

    payload = json.loads(app.ensure_input_token_budget.call_args.args[2])
    assert payload["custom_context"] == "Watch context switching."
    reply = update.message.reply_text.await_args.args[0]
    assert "too large for the configured model input budget" in reply
    assert update.message.reply_text.await_args.kwargs["parse_mode"] == ParseMode.HTML
    assert update.message.reply_text.await_count == 1


def test_review_command_formats_successful_reply(monkeypatch):
    update = _make_update()
    context = _make_context(["2w"])
    monkeypatch.setattr(
        app,
        "journal_reader",
        MagicMock(collect_review=MagicMock(return_value=_sample_collection())),
    )
    monkeypatch.setattr(
        app,
        "load_llm_config_from_env",
        MagicMock(
            return_value=LLMConfig(
                provider="OPENAI",
                model="gpt-test",
                base_url="https://api.openai.com/v1",
                api_key="secret",
                timeout_seconds=60,
                max_input_tokens=8000,
            )
        ),
    )
    monkeypatch.setattr(app, "ensure_input_token_budget", MagicMock(return_value=123))

    async def _fake_generate(*args, **kwargs):
        return LLMResult(
            provider="OPENAI",
            model="gpt-test",
            content="**Positive trends**\n- Strong week.\n- **Visible** progress.",
        )

    monkeypatch.setattr(app, "generate_review_text", _fake_generate)

    _run(app.review_command(update, context))

    replies = update.message.reply_text.await_args_list
    assert len(replies) == 2
    ack = replies[0].args[0]
    reply = replies[1].args[0]
    assert "Review request sent to OPENAI/gpt-test." in ack
    assert "I will reply here when it is ready." in ack
    assert "<b>Review | 2w</b>" in reply
    assert "Coverage: 12/14 daily, 1 weekly" in reply
    assert "Model: OPENAI/gpt-test" in reply
    assert "<b>Positive trends</b>" in reply
    assert "- Strong week." in reply
    assert "- <b>Visible</b> progress." in reply
    assert replies[0].kwargs["parse_mode"] == ParseMode.HTML
    assert replies[1].kwargs["parse_mode"] == ParseMode.HTML
    update.message.reply_document.assert_not_awaited()


def test_paginate_review_message_keeps_short_text_unchanged():
    pages = app._paginate_review_message("short review", period_label="2w", max_length=100)

    assert pages == ["short review"]


def test_paginate_review_message_splits_long_paragraphs_with_page_headers():
    pages = app._paginate_review_message("A" * 220, period_label="2w", max_length=100)

    assert len(pages) > 1
    assert all(len(page) <= 100 for page in pages)
    assert pages[0].startswith("<b>Review | 2w | 1/")
    assert pages[-1].startswith(f"<b>Review | 2w | {len(pages)}/{len(pages)}</b>")
    assert "A" * 20 in "".join(pages)


def test_paginate_review_message_splits_long_lines_with_page_headers():
    text = "intro\n\n" + ("B" * 180)

    pages = app._paginate_review_message(text, period_label="4w", max_length=110)

    assert len(pages) > 1
    assert all(len(page) <= 110 for page in pages)
    assert pages[0].startswith("<b>Review | 4w | 1/")
    assert "intro" in pages[0]
    assert "B" * 20 in "".join(pages)


def test_review_command_sends_long_report_across_multiple_messages(monkeypatch):
    update = _make_update()
    context = _make_context(["2w"])
    monkeypatch.setattr(
        app,
        "journal_reader",
        MagicMock(collect_review=MagicMock(return_value=_sample_collection())),
    )
    monkeypatch.setattr(
        app,
        "load_llm_config_from_env",
        MagicMock(
            return_value=LLMConfig(
                provider="OPENAI",
                model="gpt-test",
                base_url="https://api.openai.com/v1",
                api_key="secret",
                timeout_seconds=60,
                max_input_tokens=8000,
            )
        ),
    )
    monkeypatch.setattr(app, "ensure_input_token_budget", MagicMock(return_value=123))

    async def _fake_generate(*args, **kwargs):
        return LLMResult(
            provider="OPENAI",
            model="gpt-test",
            content="A" * int(MessageLimit.MAX_TEXT_LENGTH),
        )

    monkeypatch.setattr(app, "generate_review_text", _fake_generate)

    _run(app.review_command(update, context))

    replies = update.message.reply_text.await_args_list
    assert len(replies) > 2
    assert "Review request sent to OPENAI/gpt-test." in replies[0].args[0]
    paginated_replies = [call.args[0] for call in replies[1:]]
    assert all(len(reply) <= int(MessageLimit.MAX_TEXT_LENGTH) for reply in paginated_replies)
    assert paginated_replies[0].startswith("<b>Review | 2w | 1/")
    assert paginated_replies[-1].startswith(
        f"<b>Review | 2w | {len(paginated_replies)}/{len(paginated_replies)}</b>"
    )
    assert "Model: OPENAI/gpt-test" in paginated_replies[0]
    assert "A" * 100 in "".join(paginated_replies)
    for call in replies[1:]:
        assert call.kwargs["parse_mode"] == ParseMode.HTML
    update.message.reply_document.assert_not_awaited()


def test_review_command_reports_final_send_failure_without_raising(monkeypatch):
    update = _make_update()
    context = _make_context(["2w"])
    monkeypatch.setattr(
        app,
        "journal_reader",
        MagicMock(collect_review=MagicMock(return_value=_sample_collection())),
    )
    monkeypatch.setattr(
        app,
        "load_llm_config_from_env",
        MagicMock(
            return_value=LLMConfig(
                provider="OPENAI",
                model="gpt-test",
                base_url="https://api.openai.com/v1",
                api_key="secret",
                timeout_seconds=60,
                max_input_tokens=8000,
            )
        ),
    )
    monkeypatch.setattr(app, "ensure_input_token_budget", MagicMock(return_value=123))

    async def _fake_generate(*args, **kwargs):
        return LLMResult(provider="OPENAI", model="gpt-test", content="Analysis")

    async def _reply_text(text, **kwargs):
        if "<b>Review | 2w</b>" in text:
            raise BadRequest("Message is too long")

    update.message.reply_text.side_effect = _reply_text
    monkeypatch.setattr(app, "generate_review_text", _fake_generate)

    _run(app.review_command(update, context))

    replies = update.message.reply_text.await_args_list
    assert len(replies) == 3
    assert "Review request sent to OPENAI/gpt-test." in replies[0].args[0]
    assert "<b>Review | 2w</b>" in replies[1].args[0]
    assert "Review was generated, but I could not send the result" in replies[2].args[0]
    update.message.reply_document.assert_not_awaited()


def test_review_command_includes_saved_context_in_llm_payload(monkeypatch):
    update = _make_update()
    context = _make_context(["2w"])
    context.user_data[app.REVIEW_CONTEXT] = "I am prioritizing deep work this month."
    monkeypatch.setattr(
        app,
        "journal_reader",
        MagicMock(collect_review=MagicMock(return_value=_sample_collection())),
    )
    monkeypatch.setattr(
        app,
        "load_llm_config_from_env",
        MagicMock(
            return_value=LLMConfig(
                provider="OPENAI",
                model="gpt-test",
                base_url="https://api.openai.com/v1",
                api_key="secret",
                timeout_seconds=60,
                max_input_tokens=8000,
            )
        ),
    )
    monkeypatch.setattr(app, "ensure_input_token_budget", MagicMock(return_value=123))
    captured_payload = {}

    async def _fake_generate(config, system_prompt, user_payload):
        captured_payload.update(json.loads(user_payload))
        return LLMResult(provider="OPENAI", model="gpt-test", content="Analysis")

    monkeypatch.setattr(app, "generate_review_text", _fake_generate)

    _run(app.review_command(update, context))

    assert captured_payload["custom_context"] == "I am prioritizing deep work this month."


def test_serialize_review_collection_omits_empty_custom_context():
    payload = json.loads(app._serialize_review_collection(_sample_collection()))

    assert "custom_context" not in payload


def test_review_command_reports_configuration_error(monkeypatch):
    update = _make_update()
    context = _make_context(["2w"])
    monkeypatch.setattr(
        app,
        "journal_reader",
        MagicMock(collect_review=MagicMock(return_value=_sample_collection())),
    )
    monkeypatch.setattr(
        app,
        "load_llm_config_from_env",
        MagicMock(side_effect=LLMConfigError("missing key")),
    )

    _run(app.review_command(update, context))

    assert update.message.reply_text.await_args.args[0] == "Review is not configured: missing key"
    assert update.message.reply_text.await_args.kwargs["parse_mode"] == ParseMode.HTML
    assert update.message.reply_text.await_count == 1


def test_review_command_acks_before_provider_failure(monkeypatch):
    update = _make_update()
    context = _make_context(["2w"])
    monkeypatch.setattr(
        app,
        "journal_reader",
        MagicMock(collect_review=MagicMock(return_value=_sample_collection())),
    )
    monkeypatch.setattr(
        app,
        "load_llm_config_from_env",
        MagicMock(
            return_value=LLMConfig(
                provider="OPENAI",
                model="gpt-test",
                base_url="https://api.openai.com/v1",
                api_key="secret",
                timeout_seconds=60,
                max_input_tokens=8000,
            )
        ),
    )
    monkeypatch.setattr(app, "ensure_input_token_budget", MagicMock(return_value=123))

    async def _raise_provider(*args, **kwargs):
        raise LLMRequestError("provider down")

    monkeypatch.setattr(app, "generate_review_text", _raise_provider)

    _run(app.review_command(update, context))

    replies = update.message.reply_text.await_args_list
    assert len(replies) == 2
    assert "Review request sent to OPENAI/gpt-test." in replies[0].args[0]
    assert replies[0].kwargs["parse_mode"] == ParseMode.HTML
    assert replies[1].args[0] == "Review failed while calling the LLM provider: provider down"
    assert replies[1].kwargs["parse_mode"] == ParseMode.HTML
