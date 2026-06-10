import asyncio
import logging
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import app
from journal.period import ReviewPeriodSpec
from journal.read import (
    DailyAveragesSummary,
    ReviewCollection,
    ReviewCoverage,
    ReviewDailyEntry,
    ReviewWeeklyEntry,
)
from journal.store import JournalStore
from observability import (
    COMMAND_DURATION_SECONDS,
    COMMAND_REQUESTS_TOTAL,
    JOURNAL_INVALID_FILES_TOTAL,
    LLM_REQUESTS_TOTAL,
    REVIEW_INPUT_ESTIMATED_TOKENS,
    REVIEW_REQUESTS_TOTAL,
    TEXT_MESSAGES_TOTAL,
    get_counter_value,
    get_histogram_count,
    reset_metrics_for_tests,
)
from review.llm import (
    LLMConfig,
    LLMRequestError,
    LLMRequestTooLargeError,
    ensure_input_token_budget,
    generate_review_text,
)


DAILY_MARKDOWN = """## Daily Check-In

Energy: 7/10
Focus: 5/10
Satisfaction: 8/10

What did I actually do today?
- Finished Telegram webhook
"""

WEEKLY_MARKDOWN = """## Week 2 Review

Momentum:
- Daily coding sessions worked well
"""


def _run(coro):
    return asyncio.run(coro)


def _make_update(text: str | None = None) -> MagicMock:
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    update.message.reply_document = AsyncMock()
    update.message.text = text
    update.effective_chat.id = 1001
    update.effective_user.id = 2002
    return update


def _make_context(args: list[str] | None = None) -> MagicMock:
    context = MagicMock()
    context.args = args or []
    context.user_data = {}
    return context


def _sample_review_collection() -> ReviewCollection:
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
        daily_averages=DailyAveragesSummary(7.0, 6.0, 8.0),
    )


@pytest.fixture(autouse=True)
def _reset_metrics():
    reset_metrics_for_tests()
    yield
    reset_metrics_for_tests()


def test_statistics_invalid_args_records_command_metrics():
    update = _make_update()
    context = _make_context(["2", "weeks"])

    _run(app.statistics_command(update, context))

    assert get_counter_value(
        COMMAND_REQUESTS_TOTAL,
        command="statistics",
        outcome="invalid_args",
    ) == 1
    assert get_histogram_count(COMMAND_DURATION_SECONDS, command="statistics") == 1


def test_review_provider_error_records_command_and_review_metrics(monkeypatch):
    update = _make_update()
    context = _make_context(["2w"])
    monkeypatch.setattr(
        app,
        "journal_reader",
        MagicMock(collect_review=MagicMock(return_value=_sample_review_collection())),
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

    assert get_counter_value(
        COMMAND_REQUESTS_TOTAL,
        command="review",
        outcome="provider_error",
    ) == 1
    assert get_counter_value(REVIEW_REQUESTS_TOTAL, outcome="provider_error") == 1


def test_dump_build_error_records_metrics(monkeypatch):
    update = _make_update()
    context = _make_context([])
    monkeypatch.setattr(
        app,
        "journal_reader",
        MagicMock(scan_journal=MagicMock(return_value=MagicMock())),
    )
    monkeypatch.setattr(
        app,
        "build_journal_archive",
        MagicMock(side_effect=OSError("disk full")),
    )

    _run(app.dump_command(update, context))

    assert get_counter_value(
        COMMAND_REQUESTS_TOTAL,
        command="dump",
        outcome="build_error",
    ) == 1


def test_text_message_unknown_payload_records_metric():
    update = _make_update("hello world")
    context = _make_context([])

    _run(app.text_message(update, context))

    assert get_counter_value(
        TEXT_MESSAGES_TOTAL,
        route="auto_detect",
        detected_type="unknown",
        outcome="unknown_payload",
    ) == 1


def test_text_message_mode_mismatch_records_metric():
    update = _make_update(WEEKLY_MARKDOWN.strip())
    context = _make_context([])
    context.user_data[app.AWAITING_DAILY] = True

    _run(app.text_message(update, context))

    assert get_counter_value(
        TEXT_MESSAGES_TOTAL,
        route="awaiting_daily",
        detected_type="weekly",
        outcome="mode_mismatch",
    ) == 1


def test_text_message_save_failure_records_metric(monkeypatch, tmp_path):
    store = MagicMock()
    store.daily_path_for_when.return_value = tmp_path / "2026-06-05.md"
    store.save_daily.side_effect = OSError("disk full")
    monkeypatch.setattr(app, "journal_store", store)

    update = _make_update(DAILY_MARKDOWN.strip())
    context = _make_context([])

    _run(app.text_message(update, context))

    assert get_counter_value(
        TEXT_MESSAGES_TOTAL,
        route="auto_detect",
        detected_type="daily",
        outcome="save_failed",
    ) == 1


def test_scan_journal_invalid_file_reasons_are_bounded(tmp_path):
    root = tmp_path / "journal"
    daily_dir = root / "daily"
    weekly_dir = root / "weekly"
    daily_dir.mkdir(parents=True)
    weekly_dir.mkdir(parents=True)
    (daily_dir / "bad-name.md").write_text("## Daily Check-In", encoding="utf-8")
    (weekly_dir / "2026-week-21.md").write_text(
        "---\n"
        "type: weekly\n"
        "date: nope\n"
        "week: 2026-week-21\n"
        "---\n"
        + WEEKLY_MARKDOWN,
        encoding="utf-8",
    )

    reader = app.JournalReader(JournalStore(root))
    reader.scan_journal(today=date(2026, 6, 1))

    assert get_counter_value(
        JOURNAL_INVALID_FILES_TOTAL,
        kind="daily",
        reason="invalid_filename",
    ) == 1
    assert get_counter_value(
        JOURNAL_INVALID_FILES_TOTAL,
        kind="weekly",
        reason="date_error",
    ) == 1


def test_token_budget_rejection_records_histogram():
    config = LLMConfig(
        provider="LOCAL",
        model="test-model",
        base_url="http://localhost:1234/v1",
        api_key=None,
        timeout_seconds=60,
        max_input_tokens=5,
    )

    with pytest.raises(LLMRequestTooLargeError):
        ensure_input_token_budget(config, "abcd" * 4, "efgh" * 4)

    assert get_histogram_count(
        REVIEW_INPUT_ESTIMATED_TOKENS,
        provider="LOCAL",
        model="test-model",
    ) == 1


def test_generate_review_text_transport_failure_records_metrics(monkeypatch):
    config = LLMConfig(
        provider="LOCAL",
        model="transport-model",
        base_url="http://localhost:1234/v1",
        api_key=None,
        timeout_seconds=60,
        max_input_tokens=8000,
    )

    class _TransportFailClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _TransportFailClient())

    with pytest.raises(LLMRequestError):
        _run(generate_review_text(config, "system", "user"))

    assert get_counter_value(
        LLM_REQUESTS_TOTAL,
        provider="LOCAL",
        model="transport-model",
        outcome="transport",
    ) == 1


def test_generate_review_text_http_failure_records_metrics(monkeypatch):
    config = LLMConfig(
        provider="OPENAI",
        model="http-model",
        base_url="https://api.openai.com/v1",
        api_key="secret",
        timeout_seconds=60,
        max_input_tokens=8000,
    )
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(500, request=request, text="bad")

    class _HttpFailClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            raise httpx.HTTPStatusError("bad", request=request, response=response)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _HttpFailClient())

    with pytest.raises(LLMRequestError):
        _run(generate_review_text(config, "system", "user"))

    assert get_counter_value(
        LLM_REQUESTS_TOTAL,
        provider="OPENAI",
        model="http-model",
        outcome="http_status",
    ) == 1


def test_generate_review_text_success_records_metrics(monkeypatch):
    config = LLMConfig(
        provider="OPENAI",
        model="success-model",
        base_url="https://api.openai.com/v1",
        api_key="secret",
        timeout_seconds=60,
        max_input_tokens=8000,
    )

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "Looks good"}}]}

    class _SuccessClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return _Response()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _SuccessClient())

    result = _run(generate_review_text(config, "system", "user"))

    assert result.content == "Looks good"
    assert get_counter_value(
        LLM_REQUESTS_TOTAL,
        provider="OPENAI",
        model="success-model",
        outcome="success",
    ) == 1


def test_logs_do_not_include_raw_message_on_success(monkeypatch, caplog, tmp_path):
    store = MagicMock()
    store.daily_path_for_when.return_value = tmp_path / "2026-06-05.md"
    store.save_daily.return_value = Path(r"C:\journal\daily\2026-06-05.md")
    monkeypatch.setattr(app, "journal_store", store)
    update = _make_update(DAILY_MARKDOWN.strip())
    context = _make_context([])

    with caplog.at_level(logging.INFO):
        _run(app.text_message(update, context))

    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "checkin_saved" in joined
    assert "Finished Telegram webhook" not in joined
    assert "Energy: 7/10" not in joined


def test_logs_do_not_include_raw_message_on_parse_failure(caplog):
    update = _make_update("## Daily Check-In\n\nFocus: 5/10")
    context = _make_context([])

    with caplog.at_level(logging.WARNING):
        _run(app.text_message(update, context))

    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "parse_failed" in joined
    assert "Focus: 5/10" not in joined
    assert "Missing score for Energy" in joined
