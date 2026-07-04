import json
import logging
import os
import time as perf_clock
from datetime import datetime, time
from pathlib import Path
from typing import Any, Mapping

from dotenv import load_dotenv
from journal.export import build_journal_archive
from journal.period import parse_period, parse_review_period
from journal.read import JournalReader, ReviewCollection
from journal.store import ILS_TZ, JournalStore
from messages import TelegramMessageRenderer, TemplateId
from observability import (
    load_metrics_settings_from_env,
    log_event,
    measure_duration_seconds,
    observe_command,
    observe_reminder_job,
    observe_review_request,
    observe_text_message,
    observe_journal_save,
    set_reminders_enabled,
    set_service_start_time_seconds,
    start_metrics_http_server,
)
from parser import CheckupParser
from review.llm import (
    LLMConfigError,
    LLMRequestError,
    LLMRequestTooLargeError,
    ensure_input_token_budget,
    generate_review_text,
    load_llm_config_from_env,
)
from review.prompt import REVIEW_SYSTEM_PROMPT
from telegram import Bot, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

AWAITING_DAILY = "awaiting_daily_checkin"
AWAITING_WEEKLY = "awaiting_weekly_review"
AWAITING_CONTEXT = "awaiting_review_context"
REVIEW_CONTEXT = "review_context"
BOT_COMMANDS = [
    ("start", "Open the bot and see the quick start"),
    ("help", "Show commands and examples"),
    ("daily", "Treat your next message as a daily check-in"),
    ("weekly", "Treat your next message as a weekly review"),
    ("template", "Show daily or weekly markdown templates"),
    ("statistics", "Show score averages for a period"),
    ("context", "Add or clear context for LLM reviews"),
    ("review", "Generate an LLM-backed journal review"),
    ("log", "Show journal counts and coverage gaps"),
    ("dump", "Export journal markdown as a ZIP"),
]

journal_store = JournalStore()
journal_reader = JournalReader(journal_store)
message_renderer = TelegramMessageRenderer()


def _safe_numeric_id(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _update_actor_fields(update: Update) -> dict[str, int | None]:
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    return {
        "chat_id": _safe_numeric_id(getattr(chat, "id", None)),
        "user_id": _safe_numeric_id(getattr(user, "id", None)),
    }


def _command_log_context(
    update: Update,
    *,
    command: str,
    outcome: str,
    started_at: float,
    arg_token: str | None = None,
) -> None:
    duration_seconds = measure_duration_seconds(started_at)
    actor_fields = _update_actor_fields(update)
    log_event(
        logger,
        logging.INFO,
        "command_complete",
        command=command,
        outcome=outcome,
        duration_ms=round(duration_seconds * 1000, 3),
        arg_token=arg_token,
        **actor_fields,
    )
    observe_command(command, outcome, duration_seconds)


def _text_log_context(
    update: Update,
    *,
    event: str,
    level: int,
    **fields: Any,
) -> None:
    actor_fields = _update_actor_fields(update)
    log_event(logger, level, event, **fields, **actor_fields)


async def _reply_with_template(
    update: Update,
    template: TemplateId,
    message: Mapping[str, Any] | None = None,
) -> None:
    rendered = message_renderer.render(template, message or {})
    await update.message.reply_text(
        rendered.text,
        parse_mode=rendered.parse_mode,
    )


async def _send_with_template(
    bot: Bot,
    *,
    chat_id: int,
    template: TemplateId,
    message: Mapping[str, Any] | None = None,
) -> None:
    rendered = message_renderer.render(template, message or {})
    await bot.send_message(
        chat_id=chat_id,
        text=rendered.text,
        parse_mode=rendered.parse_mode,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    started_at = perf_clock.perf_counter()
    await _reply_with_template(update, TemplateId.TEXT, {"text_key": "start"})
    _command_log_context(update, command="start", outcome="success", started_at=started_at)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    started_at = perf_clock.perf_counter()
    await _reply_with_template(update, TemplateId.TEXT, {"text_key": "help"})
    _command_log_context(update, command="help", outcome="success", started_at=started_at)


async def template_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    started_at = perf_clock.perf_counter()
    args = context.args or []
    token = args[0].strip().lower() if args else None
    if len(args) != 1 or token not in {"daily", "weekly"}:
        await _reply_with_template(update, TemplateId.TEXT, {"text_key": "template_usage"})
        outcome = "success" if not args else "invalid_args"
        _command_log_context(
            update,
            command="template",
            outcome=outcome,
            started_at=started_at,
            arg_token=token,
        )
        return

    text_key = "template_daily" if token == "daily" else "template_weekly"
    await _reply_with_template(update, TemplateId.TEXT, {"text_key": text_key})
    _command_log_context(
        update,
        command="template",
        outcome="success",
        started_at=started_at,
        arg_token=token,
    )


def _format_size(size: int) -> str:
    return f"{size} bytes"


def _cleanup_archive(path: Path, *, cleanup: bool) -> None:
    if not cleanup:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove temporary archive %s", path)


def _serialize_review_collection(
    collection: ReviewCollection,
    *,
    custom_context: str | None = None,
) -> str:
    payload = {
        "period": {
            "token": collection.period.label,
            "start_date": collection.period.start_date.isoformat(),
            "end_date": collection.period.end_date.isoformat(),
            "timezone": str(ILS_TZ),
        },
        "coverage": {
            "expected_daily_days": collection.coverage.expected_daily_days,
            "found_daily_count": collection.coverage.found_daily_count,
            "found_weekly_count": collection.coverage.found_weekly_count,
            "missing_day_estimate": collection.coverage.missing_day_estimate,
        },
        "daily_averages": {
            "energy": collection.daily_averages.energy,
            "focus": collection.daily_averages.focus,
            "satisfaction": collection.daily_averages.satisfaction,
        },
        "daily_entries": [
            {
                "date": entry.entry_date.isoformat(),
                "energy": entry.energy,
                "focus": entry.focus,
                "satisfaction": entry.satisfaction,
                "did_today": entry.did_today,
                "meaningful": entry.meaningful,
                "drained": entry.drained,
                "tomorrow_focus": entry.tomorrow_focus,
            }
            for entry in collection.daily_entries
        ],
        "weekly_entries": [
            {
                "week": entry.week,
                "saved_date": entry.saved_date.isoformat(),
                "momentum": entry.momentum,
                "friction": entry.friction,
                "avoidance": entry.avoidance,
                "meaningful": entry.meaningful,
                "fake_productivity": entry.fake_productivity,
                "next_week_focus": entry.next_week_focus,
            }
            for entry in collection.weekly_entries
        ],
    }
    if custom_context:
        payload["custom_context"] = custom_context
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    started_at = perf_clock.perf_counter()
    context.user_data.pop(AWAITING_WEEKLY, None)
    context.user_data.pop(AWAITING_CONTEXT, None)
    context.user_data[AWAITING_DAILY] = True
    await _reply_with_template(update, TemplateId.TEXT, {"text_key": "daily_mode_enabled"})
    _command_log_context(update, command="daily", outcome="success", started_at=started_at)


async def weekly_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    started_at = perf_clock.perf_counter()
    context.user_data.pop(AWAITING_DAILY, None)
    context.user_data.pop(AWAITING_CONTEXT, None)
    context.user_data[AWAITING_WEEKLY] = True
    await _reply_with_template(update, TemplateId.TEXT, {"text_key": "weekly_mode_enabled"})
    _command_log_context(update, command="weekly", outcome="success", started_at=started_at)


async def context_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    started_at = perf_clock.perf_counter()
    args = context.args or []
    token = args[0].strip().lower() if args else None

    if len(args) > 1 or (token is not None and token != "clear"):
        await _reply_with_template(update, TemplateId.TEXT, {"text_key": "context_usage"})
        _command_log_context(
            update,
            command="context",
            outcome="invalid_args",
            started_at=started_at,
            arg_token=token,
        )
        return

    if token == "clear":
        context.user_data.pop(REVIEW_CONTEXT, None)
        context.user_data.pop(AWAITING_CONTEXT, None)
        await _reply_with_template(update, TemplateId.TEXT, {"text_key": "context_cleared"})
        _command_log_context(
            update,
            command="context",
            outcome="cleared",
            started_at=started_at,
            arg_token=token,
        )
        return

    context.user_data.pop(AWAITING_DAILY, None)
    context.user_data.pop(AWAITING_WEEKLY, None)
    context.user_data[AWAITING_CONTEXT] = True
    await _reply_with_template(update, TemplateId.TEXT, {"text_key": "context_mode_enabled"})
    _command_log_context(update, command="context", outcome="success", started_at=started_at)


async def statistics_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    started_at = perf_clock.perf_counter()
    token = context.args[0] if context.args else None
    try:
        period = parse_period(token)
    except ValueError:
        await _reply_with_template(update, TemplateId.TEXT, {"text_key": "statistics_usage"})
        _command_log_context(
            update,
            command="statistics",
            outcome="invalid_args",
            started_at=started_at,
            arg_token=token,
        )
        return

    collection = journal_reader.collect_daily(period.target_days)
    if not collection.entries:
        await _reply_with_template(
            update,
            TemplateId.TEXT,
            {"text_key": "statistics_empty", "period_label": period.label},
        )
        _command_log_context(
            update,
            command="statistics",
            outcome="empty",
            started_at=started_at,
            arg_token=token,
        )
        return

    await _reply_with_template(
        update,
        TemplateId.STATISTICS_REPORT,
        {
            "period_label": period.label,
            "collection": collection,
        },
    )
    _command_log_context(
        update,
        command="statistics",
        outcome="success",
        started_at=started_at,
        arg_token=token,
    )


async def log_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    started_at = perf_clock.perf_counter()
    token = context.args[0] if context.args else None
    if len(context.args) > 1 or (
        context.args and context.args[0].strip().lower() != "verbose"
    ):
        await _reply_with_template(update, TemplateId.TEXT, {"text_key": "log_usage"})
        _command_log_context(
            update,
            command="log",
            outcome="invalid_args",
            started_at=started_at,
            arg_token=token,
        )
        return

    report = journal_reader.collect_log_report(verbose=bool(context.args))
    if report.oldest_entry_date is None:
        await _reply_with_template(update, TemplateId.TEXT, {"text_key": "log_empty"})
        _command_log_context(
            update,
            command="log",
            outcome="empty",
            started_at=started_at,
            arg_token=token,
        )
        return

    await _reply_with_template(update, TemplateId.LOG_REPORT, {"report": report})
    _command_log_context(
        update,
        command="log",
        outcome="success",
        started_at=started_at,
        arg_token=token,
    )


async def dump_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    started_at = perf_clock.perf_counter()
    if context.args:
        await _reply_with_template(update, TemplateId.TEXT, {"text_key": "dump_usage"})
        _command_log_context(
            update,
            command="dump",
            outcome="invalid_args",
            started_at=started_at,
            arg_token=context.args[0],
        )
        return

    try:
        scan = journal_reader.scan_journal()
        archive = build_journal_archive(journal_store, scan)
    except OSError as exc:
        logger.exception("Dump command failed while building archive")
        await _reply_with_template(
            update,
            TemplateId.TEXT,
            {"text_key": "dump_failed", "error": exc},
        )
        _command_log_context(
            update,
            command="dump",
            outcome="build_error",
            started_at=started_at,
        )
        return

    if archive.status == "empty":
        await _reply_with_template(update, TemplateId.TEXT, {"text_key": "dump_empty"})
        _command_log_context(update, command="dump", outcome="empty", started_at=started_at)
        return

    if archive.status == "too_large":
        await _reply_with_template(
            update,
            TemplateId.TEXT,
            {
                "text_key": "dump_too_large",
                "archive_size": _format_size(archive.archive_size),
                "upload_limit": _format_size(archive.upload_limit),
                "file_count": archive.file_count,
                "archive_path": archive.archive_path,
            },
        )
        _command_log_context(
            update,
            command="dump",
            outcome="too_large",
            started_at=started_at,
        )
        return

    if archive.archive_path is None:
        await _reply_with_template(
            update,
            TemplateId.TEXT,
            {"text_key": "dump_failed", "error": "Archive path was not created"},
        )
        _command_log_context(
            update,
            command="dump",
            outcome="build_error",
            started_at=started_at,
        )
        return

    sent_archive = False
    try:
        await update.message.reply_document(
            document=archive.archive_path,
            filename=archive.archive_path.name,
            caption=(
                f"Journal export | {archive.file_count} files | "
                f"{_format_size(archive.archive_size)}"
            ),
        )
        sent_archive = True
    except Exception as exc:
        log_event(logger, logging.ERROR, "archive_send_failed", error=str(exc))
        logger.exception("Dump command failed while sending archive")
        await _reply_with_template(
            update,
            TemplateId.TEXT,
            {"text_key": "dump_failed", "error": exc},
        )
        _command_log_context(
            update,
            command="dump",
            outcome="send_error",
            started_at=started_at,
        )
    finally:
        _cleanup_archive(archive.archive_path, cleanup=archive.cleanup_after_send)
    if sent_archive:
        _command_log_context(update, command="dump", outcome="success", started_at=started_at)


async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    started_at = perf_clock.perf_counter()
    if len(context.args) > 1:
        await _reply_with_template(update, TemplateId.TEXT, {"text_key": "review_usage"})
        observe_review_request("invalid_args")
        _command_log_context(
            update,
            command="review",
            outcome="invalid_args",
            started_at=started_at,
            arg_token=context.args[0],
        )
        return

    token = context.args[0] if context.args else None
    try:
        period = parse_review_period(token)
    except ValueError:
        await _reply_with_template(update, TemplateId.TEXT, {"text_key": "review_usage"})
        observe_review_request("invalid_args")
        _command_log_context(
            update,
            command="review",
            outcome="invalid_args",
            started_at=started_at,
            arg_token=token,
        )
        return

    collection = journal_reader.collect_review(period)
    if not collection.daily_entries and not collection.weekly_entries:
        await _reply_with_template(
            update,
            TemplateId.TEXT,
            {"text_key": "review_empty", "period_label": period.label},
        )
        observe_review_request("empty")
        _command_log_context(
            update,
            command="review",
            outcome="empty",
            started_at=started_at,
            arg_token=token,
        )
        return

    try:
        config = load_llm_config_from_env()
    except LLMConfigError as exc:
        log_event(logger, logging.ERROR, "review_config_error", error=str(exc))
        await _reply_with_template(
            update,
            TemplateId.TEXT,
            {"text_key": "review_not_configured", "error": exc},
        )
        observe_review_request("config_error")
        _command_log_context(
            update,
            command="review",
            outcome="config_error",
            started_at=started_at,
            arg_token=token,
        )
        return

    custom_context = context.user_data.get(REVIEW_CONTEXT)
    user_payload = _serialize_review_collection(
        collection,
        custom_context=custom_context if isinstance(custom_context, str) else None,
    )
    try:
        ensure_input_token_budget(config, REVIEW_SYSTEM_PROMPT, user_payload)
    except LLMRequestTooLargeError:
        await _reply_with_template(update, TemplateId.TEXT, {"text_key": "review_too_large"})
        observe_review_request("too_large")
        _command_log_context(
            update,
            command="review",
            outcome="too_large",
            started_at=started_at,
            arg_token=token,
        )
        return

    try:
        result = await generate_review_text(config, REVIEW_SYSTEM_PROMPT, user_payload)
    except LLMRequestError as exc:
        logger.exception("Review command failed while calling the LLM provider")
        await _reply_with_template(
            update,
            TemplateId.TEXT,
            {"text_key": "review_provider_failure", "error": exc},
        )
        observe_review_request("provider_error")
        _command_log_context(
            update,
            command="review",
            outcome="provider_error",
            started_at=started_at,
            arg_token=token,
        )
        return

    await _reply_with_template(
        update,
        TemplateId.REVIEW_REPORT,
        {
            "collection": collection,
            "provider": result.provider,
            "model": result.model,
            "analysis": result.content,
        },
    )
    observe_review_request("success")
    _command_log_context(
        update,
        command="review",
        outcome="success",
        started_at=started_at,
        arg_token=token,
    )


async def handle_daily_checkin_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    route: str = "auto_detect",
    detected_type: str | None = None,
) -> None:
    raw = update.message.text
    detected = detected_type or CheckupParser.detect_type(raw)
    if detected == "weekly":
        _text_log_context(
            update,
            event="mode_mismatch",
            level=logging.WARNING,
            awaiting_type="daily",
            detected_type=detected,
        )
        observe_text_message(route, detected, "mode_mismatch")
        await _reply_with_template(update, TemplateId.TEXT, {"text_key": "daily_mode_mismatch"})
        return

    try:
        parsed = CheckupParser.parse(raw)
    except ValueError as exc:
        _text_log_context(
            update,
            event="parse_failed",
            level=logging.WARNING,
            expected_type="daily",
            detected_type=detected,
            error=str(exc),
        )
        observe_text_message(route, detected, "parse_failed")
        await _reply_with_template(
            update,
            TemplateId.TEXT,
            {"text_key": "daily_parse_failure", "error": exc},
        )
        return

    saved_path = None
    save_error = None
    save_started_at = perf_clock.perf_counter()
    save_when = datetime.now(ILS_TZ)
    target_path = journal_store.daily_path_for_when(save_when)
    overwrote_existing = bool(target_path.exists())
    try:
        saved_path = journal_store.save_daily(raw, parsed)
        duration_seconds = measure_duration_seconds(save_started_at)
        observe_journal_save("daily", "success", duration_seconds)
        observe_text_message(route, detected, "saved")
        _text_log_context(
            update,
            event="checkin_saved",
            level=logging.INFO,
            kind="daily",
            path=str(saved_path),
            overwrote_existing=overwrote_existing,
            duration_ms=round(duration_seconds * 1000, 3),
        )
    except OSError as exc:
        logger.exception("Failed to save daily check-in to journal")
        save_error = exc
        observe_journal_save("daily", "failure", measure_duration_seconds(save_started_at))
        observe_text_message(route, detected, "save_failed")
        _text_log_context(
            update,
            event="checkin_save_failed",
            level=logging.ERROR,
            kind="daily",
            error=str(exc),
        )

    context.user_data.pop(AWAITING_DAILY, None)
    await _reply_with_template(
        update,
        TemplateId.CHECKIN_RESULT,
        {
            "checkin_type": "daily",
            "parsed": parsed,
            "saved_path": saved_path,
            "save_error": save_error,
        },
    )


async def handle_weekly_review_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    route: str = "auto_detect",
    detected_type: str | None = None,
) -> None:
    raw = update.message.text
    detected = detected_type or CheckupParser.detect_type(raw)
    if detected == "daily":
        _text_log_context(
            update,
            event="mode_mismatch",
            level=logging.WARNING,
            awaiting_type="weekly",
            detected_type=detected,
        )
        observe_text_message(route, detected, "mode_mismatch")
        await _reply_with_template(update, TemplateId.TEXT, {"text_key": "weekly_mode_mismatch"})
        return

    try:
        parsed = CheckupParser.parse(raw)
    except ValueError as exc:
        _text_log_context(
            update,
            event="parse_failed",
            level=logging.WARNING,
            expected_type="weekly",
            detected_type=detected,
            error=str(exc),
        )
        observe_text_message(route, detected, "parse_failed")
        await _reply_with_template(
            update,
            TemplateId.TEXT,
            {"text_key": "weekly_parse_failure", "error": exc},
        )
        return

    saved_path = None
    save_error = None
    save_started_at = perf_clock.perf_counter()
    save_when = datetime.now(ILS_TZ)
    target_path = journal_store.weekly_path_for_when(save_when)
    overwrote_existing = bool(target_path.exists())
    try:
        saved_path = journal_store.save_weekly(raw, parsed)
        duration_seconds = measure_duration_seconds(save_started_at)
        observe_journal_save("weekly", "success", duration_seconds)
        observe_text_message(route, detected, "saved")
        _text_log_context(
            update,
            event="checkin_saved",
            level=logging.INFO,
            kind="weekly",
            path=str(saved_path),
            overwrote_existing=overwrote_existing,
            duration_ms=round(duration_seconds * 1000, 3),
        )
    except OSError as exc:
        logger.exception("Failed to save weekly review to journal")
        save_error = exc
        observe_journal_save("weekly", "failure", measure_duration_seconds(save_started_at))
        observe_text_message(route, detected, "save_failed")
        _text_log_context(
            update,
            event="checkin_save_failed",
            level=logging.ERROR,
            kind="weekly",
            error=str(exc),
        )

    context.user_data.pop(AWAITING_WEEKLY, None)
    await _reply_with_template(
        update,
        TemplateId.CHECKIN_RESULT,
        {
            "checkin_type": "weekly",
            "parsed": parsed,
            "saved_path": saved_path,
            "save_error": save_error,
        },
    )


async def handle_review_context_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    raw = update.message.text
    custom_context = raw.strip()
    if not custom_context:
        await _reply_with_template(update, TemplateId.TEXT, {"text_key": "context_empty"})
        return

    context.user_data[REVIEW_CONTEXT] = custom_context
    context.user_data.pop(AWAITING_CONTEXT, None)
    await _reply_with_template(update, TemplateId.TEXT, {"text_key": "context_saved"})


async def handle_detected_checkin_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    raw = update.message.text
    detected = CheckupParser.detect_type(raw)

    if detected == "unknown":
        observe_text_message("auto_detect", detected, "unknown_payload")
        await _reply_with_template(update, TemplateId.TEXT, {"text_key": "unknown_payload"})
        return

    if detected == "daily":
        await handle_daily_checkin_text(
            update,
            context,
            route="auto_detect",
            detected_type=detected,
        )
        return

    await handle_weekly_review_text(
        update,
        context,
        route="auto_detect",
        detected_type=detected,
    )


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw = update.message.text
    detected = CheckupParser.detect_type(raw)
    if context.user_data.get(AWAITING_CONTEXT):
        _text_log_context(
            update,
            event="message_routed",
            level=logging.INFO,
            route="awaiting_context",
            detected_type=detected,
        )
        await handle_review_context_text(update, context)
    elif context.user_data.get(AWAITING_DAILY):
        _text_log_context(
            update,
            event="message_routed",
            level=logging.INFO,
            route="awaiting_daily",
            detected_type=detected,
        )
        await handle_daily_checkin_text(
            update,
            context,
            route="awaiting_daily",
            detected_type=detected,
        )
    elif context.user_data.get(AWAITING_WEEKLY):
        _text_log_context(
            update,
            event="message_routed",
            level=logging.INFO,
            route="awaiting_weekly",
            detected_type=detected,
        )
        await handle_weekly_review_text(
            update,
            context,
            route="awaiting_weekly",
            detected_type=detected,
        )
    else:
        _text_log_context(
            update,
            event="message_routed",
            level=logging.INFO,
            route="auto_detect",
            detected_type=detected,
        )
        await handle_detected_checkin_text(update, context)


async def scheduled_checkup_prompt(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = context.bot_data["checkup_chat_id"]
    kind = "daily" if context.job.data == "daily" else "weekly"
    text_key = "daily_prompt" if kind == "daily" else "weekly_prompt"
    try:
        await _send_with_template(
            context.bot,
            chat_id=chat_id,
            template=TemplateId.TEXT,
            message={"text_key": text_key},
        )
    except Exception as exc:
        observe_reminder_job(kind, "send_failed")
        log_event(
            logger,
            logging.ERROR,
            "reminder_send_failed",
            kind=kind,
            chat_id=chat_id,
            error=str(exc),
        )
        raise
    observe_reminder_job(kind, "sent")


async def register_bot_commands(application: Application) -> None:
    try:
        await application.bot.set_my_commands(BOT_COMMANDS)
    except Exception as exc:
        log_event(
            logger,
            logging.WARNING,
            "bot_command_registration_failed",
            error=str(exc),
        )
        return

    log_event(
        logger,
        logging.INFO,
        "bot_commands_registered",
        command_count=len(BOT_COMMANDS),
    )


async def post_init(application: Application) -> None:
    await register_bot_commands(application)

    raw = os.environ.get("CHECKUP_CHAT_ID")
    if not raw:
        set_reminders_enabled(False)
        observe_reminder_job("daily", "disabled")
        observe_reminder_job("weekly", "disabled")
        log_event(
            logger,
            logging.WARNING,
            "reminders_disabled_missing_chat_id",
        )
        return

    chat_id = int(raw.strip())
    application.bot_data["checkup_chat_id"] = chat_id

    jq = application.job_queue
    if jq is None:
        set_reminders_enabled(False)
        observe_reminder_job("daily", "disabled")
        observe_reminder_job("weekly", "disabled")
        log_event(logger, logging.WARNING, "reminders_disabled_no_job_queue")
        return

    jq.run_daily(
        scheduled_checkup_prompt,
        time=time(21, 0, tzinfo=ILS_TZ),
        data="daily",
        name="daily_checkup_prompt",
    )
    jq.run_daily(
        scheduled_checkup_prompt,
        time=time(19, 0, tzinfo=ILS_TZ),
        days=(6,),
        data="weekly",
        name="weekly_checkup_prompt",
    )
    set_reminders_enabled(True)
    log_event(
        logger,
        logging.INFO,
        "reminders_scheduled",
        daily_time="21:00",
        weekly_time="Saturday 19:00",
        timezone=str(ILS_TZ),
        chat_id=chat_id,
    )


def main():
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
    if os.environ.get("DEV_MODE") == "true":
        load_dotenv(override=True)

    metrics_settings = load_metrics_settings_from_env(dict(os.environ))
    start_metrics_http_server(metrics_settings)
    set_service_start_time_seconds()
    set_reminders_enabled(bool(os.environ.get("CHECKUP_CHAT_ID")))
    log_event(
        logger,
        logging.INFO,
        "service_start",
        journal_root=str(journal_store.root),
        metrics_enabled=metrics_settings.enabled,
        metrics_port=metrics_settings.port,
        llm_provider_configured=bool(os.environ.get("LLM_PROVIDER", "").strip()),
        reminders_enabled=bool(os.environ.get("CHECKUP_CHAT_ID", "").strip()),
    )

    app = (
        ApplicationBuilder()
        .token(bot_token)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("daily", daily_command))
    app.add_handler(CommandHandler("weekly", weekly_command))
    app.add_handler(CommandHandler("template", template_command))
    app.add_handler(CommandHandler("statistics", statistics_command))
    app.add_handler(CommandHandler("context", context_command))
    app.add_handler(CommandHandler("log", log_command))
    app.add_handler(CommandHandler("dump", dump_command))
    app.add_handler(CommandHandler("review", review_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))

    app.run_polling()


if __name__ == "__main__":
    main()
