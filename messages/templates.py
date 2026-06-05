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
    "start": "Hi! Send me any message and I'll say hello back!",
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
    "log_usage": "Usage: /log [verbose]",
    "log_empty": "No valid journal entries found.",
    "review_usage": "Usage: /review [Nw], for example /review 2w",
    "review_empty": "No journal entries for ${period_label}.",
    "review_not_configured": "Review is not configured: ${error}",
    "review_too_large": (
        "That review period is too large for the configured model input budget. "
        "Retry with fewer weeks."
    ),
    "review_provider_failure": "Review failed while calling the LLM provider: ${error}",
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
