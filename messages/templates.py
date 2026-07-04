from __future__ import annotations

TEMPLATES: dict[str, str] = {
    "text": "${body_html}",
    "checkin_result": (
        "<b>Detected as ${checkin_type}.</b> Parsed successfully.\n\n"
        "${summary_html}${save_note_html}"
    ),
    "statistics_report": (
        "<b>Statistics | ${period_label}</b>\n\n"
        "${summary}\n"
        "${scores}"
    ),
    "log_report": (
        "<b>Journal Log</b>\n\n"
        "${summary_html}${details_html}"
    ),
    "review_report": (
        "<b>Review | ${period_label}</b>\n"
        "Period: ${start_date} - ${end_date} (${timezone})\n"
        "Coverage: ${found_daily_count}/${expected_daily_days} daily, ${found_weekly_count} weekly\n"
        "Model: ${provider}/${model}\n"
        "Generated: ${generated_at}\n\n"
        "${analysis_html}"
    ),
}

TEXT_MESSAGES: dict[str, str] = {
    "start": (
        "<b>Checkup bot</b>\n\n"
        "Send a markdown daily check-in or weekly review and I will parse it, save it, "
        "and reply with a clean summary.\n\n"
        "Start with /template daily, or use /help to see every command."
    ),
    "help": (
        "<b>Commands</b>\n\n"
        "/daily - Treat your next message as a daily check-in\n"
        "/weekly - Treat your next message as a weekly review\n"
        "/template daily|weekly - Show copyable markdown formats\n"
        "/statistics [Nd|Nw|Nm] - Score averages, for example /statistics 2w\n"
        "/context - Add background for LLM reviews\n"
        "/context clear - Clear saved review context\n"
        "/review [Nw] - LLM-backed journal review, for example /review 4w\n"
        "/log [verbose] - Journal counts and coverage gaps\n"
        "/dump - Export journal markdown as a ZIP"
    ),
    "template_usage": "Use /template daily or /template weekly.",
    "template_daily": (
        "<b>Daily check-in template</b>\n\n"
        "<pre>## Daily Check-In\n\n"
        "Energy: /10\n"
        "Focus: /10\n"
        "Satisfaction: /10\n\n"
        "### What did I actually do today?\n"
        "- \n\n"
        "### What felt meaningful?\n"
        "- \n\n"
        "### What drained me?\n"
        "- \n\n"
        "### What should tomorrow focus on?\n"
        "- </pre>"
    ),
    "template_weekly": (
        "<b>Weekly review template</b>\n\n"
        "<pre>## Weekly Review\n\n"
        "### Momentum\n"
        "- \n\n"
        "### Friction\n"
        "- \n\n"
        "### Avoidance\n"
        "- \n\n"
        "### Meaningful\n"
        "- \n\n"
        "### Fake productivity\n"
        "- \n\n"
        "### Next Week Focus\n"
        "- </pre>"
    ),
    "daily_mode_enabled": (
        "<b>Daily mode enabled</b> for your next message.\n"
        "Auto-detect also works without this command."
    ),
    "weekly_mode_enabled": (
        "<b>Weekly mode enabled</b> for your next message.\n"
        "Auto-detect also works without this command."
    ),
    "statistics_usage": (
        "Usage: /statistics [Nd|Nw|Nm], for example /statistics 5d, /statistics 2w, /statistics 10m"
    ),
    "statistics_empty": "No daily entries for ${period_label}.",
    "context_usage": "Usage: /context or /context clear",
    "context_mode_enabled": (
        "<b>Review context mode enabled</b> for your next message.\n\n"
        "Send any helpful background you want the LLM to consider during /review: "
        "current goals, constraints, priorities, stressors, work or life context, "
        "or specific patterns you want it to watch for."
    ),
    "context_saved": (
        "<b>Review context saved.</b>\n\n"
        "Future /review calls in this bot session will include it. "
        "Send /context again to replace it, or /context clear to remove it."
    ),
    "context_empty": (
        "Review context cannot be empty.\n\n"
        "Send the context as one message, or use /context clear to leave reviews based only on journal data."
    ),
    "context_cleared": (
        "<b>Review context cleared.</b>\n\n"
        "Future /review calls will use journal data only unless you add new context with /context."
    ),
    "log_usage": "Usage: /log [verbose]",
    "log_empty": "No valid journal entries found.",
    "review_usage": "Usage: /review [Nw], for example /review 2w",
    "review_empty": "No journal entries for ${period_label}.",
    "review_not_configured": "Review is not configured: ${error}",
    "review_request_sent": (
        "Review request sent to ${provider}/${model}. "
        "I will reply here when it is ready."
    ),
    "review_too_large": (
        "That review period is too large for the configured model input budget. "
        "Retry with fewer weeks."
    ),
    "review_provider_failure": "Review failed while calling the LLM provider: ${error}",
    "review_send_failure": (
        "Review was generated, but I could not send the result: ${error}"
    ),
    "dump_usage": "Usage: /dump",
    "dump_empty": "No journal markdown files were found to export.",
    "dump_too_large": (
        "Archive ready but too large to send via Telegram (${archive_size} > ${upload_limit}).\n"
        "Files: ${file_count}\n"
        "Saved to <code>${archive_path}</code>"
    ),
    "dump_failed": "Dump failed while creating or sending the archive: ${error}",
    "daily_mode_mismatch": (
        "That looks like a weekly review, but daily mode is enabled.\n\n"
        "Send a daily check-in, or use /weekly to switch the override."
    ),
    "weekly_mode_mismatch": (
        "That looks like a daily check-in, but weekly mode is enabled.\n\n"
        "Send a weekly review, or use /daily to switch the override."
    ),
    "daily_parse_failure": (
        "Could not parse that as a daily check-in: ${error}\n\n"
        "Fix the message and send again, or send /daily to keep daily mode active."
    ),
    "weekly_parse_failure": (
        "Could not parse that as a weekly review: ${error}\n\n"
        "Fix the message and send again, or send /weekly to keep weekly mode active."
    ),
    "unknown_payload": (
        "I couldn't recognize that message as a daily check-in or weekly review.\n\n"
        "Send it in the usual format, or use /daily or /weekly to force the expected type."
    ),
    "daily_prompt": (
        "Time for your daily check-in. "
        "Send your check-up in the usual daily format when you are ready."
    ),
    "weekly_prompt": (
        "Time for your weekly review. "
        "Send your check-up in the usual weekly format when you are ready."
    ),
}
