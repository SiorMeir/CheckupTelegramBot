import logging
import os
from datetime import time

from journal.period import parse_period
from journal.read import JournalReader
from journal.stats import format_statistics_report
from journal.store import JournalStore
from parser.parser import CheckupParser, DailyCheckIn, WeeklyReview
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

AWAITING_DAILY = "awaiting_daily_checkin"
AWAITING_WEEKLY = "awaiting_weekly_review"

ILS_TZ = ZoneInfo("Asia/Jerusalem")

DAILY_PROMPT = (
    "Time for your daily check-in. "
    "Send your check-up in the usual daily format when you are ready."
)
WEEKLY_PROMPT = (
    "Time for your weekly review. "
    "Send your check-up in the usual weekly format when you are ready."
)
STATISTICS_USAGE = "Usage: /statistics [Nd|Nw|Nm], for example /statistics 5d, /statistics 2w, /statistics 10m"

journal_store = JournalStore()
journal_reader = JournalReader(journal_store)
# /start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hi! Send me any message and I'll say hello back!")


def format_parsed_daily(d: DailyCheckIn) -> str:
    def block(title: str, items: list[str]) -> str:
        body = "\n".join(f"• {x}" for x in items) if items else "(none)"
        return f"{title}\n{body}"

    scores = f"Energy {d.energy}/10 · Focus {d.focus}/10 · Satisfaction {d.satisfaction}/10"
    sections = [
        block("Did today", d.did_today),
        block("Meaningful", d.meaningful),
        block("Drained", d.drained),
        block("Tomorrow focus", d.tomorrow_focus),
    ]
    return "Parsed daily check-in:\n\n" + scores + "\n\n" + "\n\n".join(sections)


def format_parsed_weekly(w: WeeklyReview) -> str:
    def block(title: str, items: list[str]) -> str:
        body = "\n".join(f"• {x}" for x in items) if items else "(none)"
        return f"{title}\n{body}"

    sections = [
        block("Momentum", w.momentum),
        block("Friction", w.friction),
        block("Avoidance", w.avoidance),
        block("Meaningful", w.meaningful),
        block("Fake productivity", w.fake_productivity),
        block("Next week focus", w.next_week_focus),
    ]
    return "Parsed weekly review:\n\n" + "\n\n".join(sections)


def format_detected_success(checkin_type: str, parsed_text: str, save_note: str = "") -> str:
    return f"Detected as {checkin_type}. Parsed successfully.\n\n{parsed_text}{save_note}"


def format_unknown_payload_message() -> str:
    return (
        "I couldn't recognize that message as a daily check-in or weekly review.\n\n"
        "Send it in the usual format, or use /daily or /weekly to force the expected type."
    )


async def daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(AWAITING_WEEKLY, None)
    context.user_data[AWAITING_DAILY] = True
    await update.message.reply_text(
        "Daily mode enabled for your next message.\n"
        "Auto-detect also works without this command."
    )


async def weekly_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(AWAITING_DAILY, None)
    context.user_data[AWAITING_WEEKLY] = True
    await update.message.reply_text(
        "Weekly mode enabled for your next message.\n"
        "Auto-detect also works without this command."
    )


async def statistics_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    token = context.args[0] if context.args else None
    logger.info(f"Statistics command called with token: {token}")
    try:
        period = parse_period(token)
    except ValueError:
        await update.message.reply_text(STATISTICS_USAGE)
        logger.error(f"Invalid period: {token}")
        return

    collection = journal_reader.collect_daily(period.target_days)
    await update.message.reply_text(
        format_statistics_report(period.label, collection)
    )


async def handle_daily_checkin_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    raw = update.message.text
    detected = CheckupParser.detect_type(raw)
    if detected == "weekly":
        await update.message.reply_text(
            "That looks like a weekly review, but daily mode is enabled.\n\n"
            "Send a daily check-in, or use /weekly to switch the override."
        )
        return

    try:
        parsed = CheckupParser.parse(raw)
    except ValueError as e:
        await update.message.reply_text(
            f"Could not parse that as a daily check-in: {e}\n\n"
            "Fix the message and send again, or send /daily to keep daily mode active."
        )
        return

    save_note = ""
    try:
        path = journal_store.save_daily(raw, parsed)
        save_note = f"\n\nSaved to journal: {path}"
    except OSError as e:
        logger.exception("Failed to save daily check-in to journal")
        save_note = f"\n\nWarning: could not save to journal: {e}"

    context.user_data.pop(AWAITING_DAILY, None)
    await update.message.reply_text(
        format_detected_success("daily", format_parsed_daily(parsed), save_note)
    )


async def handle_weekly_review_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    raw = update.message.text
    detected = CheckupParser.detect_type(raw)
    if detected == "daily":
        await update.message.reply_text(
            "That looks like a daily check-in, but weekly mode is enabled.\n\n"
            "Send a weekly review, or use /daily to switch the override."
        )
        return

    try:
        parsed = CheckupParser.parse(raw)
    except ValueError as e:
        await update.message.reply_text(
            f"Could not parse that as a weekly review: {e}\n\n"
            "Fix the message and send again, or send /weekly to keep weekly mode active."
        )
        return

    save_note = ""
    try:
        path = journal_store.save_weekly(raw, parsed)
        save_note = f"\n\nSaved to journal: {path}"
    except OSError as e:
        logger.exception("Failed to save weekly review to journal")
        save_note = f"\n\nWarning: could not save to journal: {e}"

    context.user_data.pop(AWAITING_WEEKLY, None)
    await update.message.reply_text(
        format_detected_success("weekly", format_parsed_weekly(parsed), save_note)
    )


async def handle_detected_checkin_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    raw = update.message.text
    detected = CheckupParser.detect_type(raw)

    if detected == "unknown":
        await update.message.reply_text(format_unknown_payload_message())
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
    text = DAILY_PROMPT if context.job.data == "daily" else WEEKLY_PROMPT
    await context.bot.send_message(chat_id=chat_id, text=text)


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

    # Daily 21:00 Asia/Jerusalem (IL time); PTB weekday: 0=Sun … 6=Sat
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
        "Scheduled reminders: daily 21:00, Saturday 19:00 (%s) → chat_id=%s",
        ILS_TZ,
        chat_id,
    )


def main():
    # if we're in dev mode, load envs from .env file
    load_dotenv()
    BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Register handlers (commands before catch-all text)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("daily", daily_command))
    app.add_handler(CommandHandler("weekly", weekly_command))
    app.add_handler(CommandHandler("statistics", statistics_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))

    app.run_polling()


if __name__ == "__main__":
    main()
