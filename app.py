import json
import logging
import os
from datetime import time
from typing import Any, Mapping

from dotenv import load_dotenv
from journal.period import parse_period, parse_review_period
from journal.read import JournalReader, ReviewCollection
from journal.store import ILS_TZ, JournalStore
from messages import TelegramMessageRenderer, TemplateId
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

journal_store = JournalStore()
journal_reader = JournalReader(journal_store)
message_renderer = TelegramMessageRenderer()


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
    await _reply_with_template(update, TemplateId.TEXT, {"text_key": "start"})


def _serialize_review_collection(collection: ReviewCollection) -> str:
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
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(AWAITING_WEEKLY, None)
    context.user_data[AWAITING_DAILY] = True
    await _reply_with_template(update, TemplateId.TEXT, {"text_key": "daily_mode_enabled"})


async def weekly_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(AWAITING_DAILY, None)
    context.user_data[AWAITING_WEEKLY] = True
    await _reply_with_template(update, TemplateId.TEXT, {"text_key": "weekly_mode_enabled"})


async def statistics_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    token = context.args[0] if context.args else None
    logger.info("Statistics command called with token: %s", token)
    try:
        period = parse_period(token)
    except ValueError:
        await _reply_with_template(update, TemplateId.TEXT, {"text_key": "statistics_usage"})
        logger.error("Invalid period: %s", token)
        return

    collection = journal_reader.collect_daily(period.target_days)
    if not collection.entries:
        await _reply_with_template(
            update,
            TemplateId.TEXT,
            {"text_key": "statistics_empty", "period_label": period.label},
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


async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) > 1:
        await _reply_with_template(update, TemplateId.TEXT, {"text_key": "review_usage"})
        return

    token = context.args[0] if context.args else None
    try:
        period = parse_review_period(token)
    except ValueError:
        await _reply_with_template(update, TemplateId.TEXT, {"text_key": "review_usage"})
        return

    collection = journal_reader.collect_review(period)
    if not collection.daily_entries and not collection.weekly_entries:
        await _reply_with_template(
            update,
            TemplateId.TEXT,
            {"text_key": "review_empty", "period_label": period.label},
        )
        return

    try:
        config = load_llm_config_from_env()
    except LLMConfigError as exc:
        logger.error("Review command configuration error: %s", exc)
        await _reply_with_template(
            update,
            TemplateId.TEXT,
            {"text_key": "review_not_configured", "error": exc},
        )
        return

    user_payload = _serialize_review_collection(collection)
    try:
        ensure_input_token_budget(config, REVIEW_SYSTEM_PROMPT, user_payload)
    except LLMRequestTooLargeError:
        await _reply_with_template(update, TemplateId.TEXT, {"text_key": "review_too_large"})
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


async def handle_daily_checkin_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    raw = update.message.text
    detected = CheckupParser.detect_type(raw)
    if detected == "weekly":
        await _reply_with_template(update, TemplateId.TEXT, {"text_key": "daily_mode_mismatch"})
        return

    try:
        parsed = CheckupParser.parse(raw)
    except ValueError as exc:
        await _reply_with_template(
            update,
            TemplateId.TEXT,
            {"text_key": "daily_parse_failure", "error": exc},
        )
        return

    saved_path = None
    save_error = None
    try:
        saved_path = journal_store.save_daily(raw, parsed)
    except OSError as exc:
        logger.exception("Failed to save daily check-in to journal")
        save_error = exc

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
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    raw = update.message.text
    detected = CheckupParser.detect_type(raw)
    if detected == "daily":
        await _reply_with_template(update, TemplateId.TEXT, {"text_key": "weekly_mode_mismatch"})
        return

    try:
        parsed = CheckupParser.parse(raw)
    except ValueError as exc:
        await _reply_with_template(
            update,
            TemplateId.TEXT,
            {"text_key": "weekly_parse_failure", "error": exc},
        )
        return

    saved_path = None
    save_error = None
    try:
        saved_path = journal_store.save_weekly(raw, parsed)
    except OSError as exc:
        logger.exception("Failed to save weekly review to journal")
        save_error = exc

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


async def handle_detected_checkin_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    raw = update.message.text
    detected = CheckupParser.detect_type(raw)

    if detected == "unknown":
        await _reply_with_template(update, TemplateId.TEXT, {"text_key": "unknown_payload"})
        return

    if detected == "daily":
        await handle_daily_checkin_text(update, context)
        return

    await handle_weekly_review_text(update, context)


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get(AWAITING_DAILY):
        await handle_daily_checkin_text(update, context)
    elif context.user_data.get(AWAITING_WEEKLY):
        await handle_weekly_review_text(update, context)
    else:
        await handle_detected_checkin_text(update, context)


async def scheduled_checkup_prompt(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = context.bot_data["checkup_chat_id"]
    text_key = "daily_prompt" if context.job.data == "daily" else "weekly_prompt"
    await _send_with_template(
        context.bot,
        chat_id=chat_id,
        template=TemplateId.TEXT,
        message={"text_key": text_key},
    )


async def post_init(application: Application) -> None:
    raw = os.environ.get("CHECKUP_CHAT_ID")
    if not raw:
        logger.warning(
            "CHECKUP_CHAT_ID is not set; daily/weekly reminder jobs are disabled."
        )
        return

    chat_id = int(raw.strip())
    application.bot_data["checkup_chat_id"] = chat_id

    jq = application.job_queue
    if jq is None:
        logger.warning("Job queue unavailable; reminders not scheduled.")
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
    logger.info(
        "Scheduled reminders: daily 21:00, Saturday 19:00 (%s) -> chat_id=%s",
        ILS_TZ,
        chat_id,
    )


def main():
    load_dotenv()
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

    app = (
        ApplicationBuilder()
        .token(bot_token)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("daily", daily_command))
    app.add_handler(CommandHandler("weekly", weekly_command))
    app.add_handler(CommandHandler("statistics", statistics_command))
    app.add_handler(CommandHandler("review", review_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))

    app.run_polling()


if __name__ == "__main__":
    main()
