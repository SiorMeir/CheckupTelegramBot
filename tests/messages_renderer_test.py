from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest
from telegram.constants import ParseMode

from journal.period import ReviewPeriodSpec
from journal.read import (
    DailyAveragesSummary,
    DailyCollection,
    DailyEntry,
    JournalLogReport,
    JournalScan,
    ReviewCollection,
    ReviewCoverage,
)
from messages import TelegramMessageRenderer, TemplateId
from parser import DailyCheckIn


def test_render_uses_template_lookup_for_static_message():
    renderer = TelegramMessageRenderer()

    rendered = renderer.render(TemplateId.TEXT, {"text_key": "start"})

    assert "<b>Checkup bot</b>" in rendered.text
    assert "/template daily" in rendered.text
    assert "/help" in rendered.text
    assert rendered.parse_mode == ParseMode.HTML


def test_render_help_lists_core_commands():
    renderer = TelegramMessageRenderer()

    rendered = renderer.render(TemplateId.TEXT, {"text_key": "help"})

    assert "/daily" in rendered.text
    assert "/weekly" in rendered.text
    assert "/template daily|weekly" in rendered.text
    assert "/statistics [Nd|Nw|Nm]" in rendered.text
    assert "/context" in rendered.text
    assert "/context clear" in rendered.text
    assert rendered.parse_mode == ParseMode.HTML


def test_render_daily_template_preserves_copyable_markdown():
    renderer = TelegramMessageRenderer()

    rendered = renderer.render(TemplateId.TEXT, {"text_key": "template_daily"})

    assert "<pre>## Daily Check-In" in rendered.text
    assert "Energy: /10" in rendered.text
    assert "### What should tomorrow focus on?" in rendered.text
    assert rendered.text.endswith("</pre>")
    assert rendered.parse_mode == ParseMode.HTML


def test_render_weekly_template_preserves_copyable_markdown():
    renderer = TelegramMessageRenderer()

    rendered = renderer.render(TemplateId.TEXT, {"text_key": "template_weekly"})

    assert "<pre>## Weekly Review" in rendered.text
    assert "### Momentum" in rendered.text
    assert "### Next Week Focus" in rendered.text
    assert rendered.text.endswith("</pre>")
    assert rendered.parse_mode == ParseMode.HTML


@pytest.mark.parametrize(
    ("text_key", "expected"),
    [
        ("context_usage", "Usage: /context or /context clear"),
        ("context_mode_enabled", "Review context mode enabled"),
        ("context_saved", "Review context saved"),
        ("context_empty", "Review context cannot be empty"),
        ("context_cleared", "Review context cleared"),
    ],
)
def test_render_context_messages(text_key, expected):
    renderer = TelegramMessageRenderer()

    rendered = renderer.render(TemplateId.TEXT, {"text_key": text_key})

    assert expected in rendered.text
    assert rendered.parse_mode == ParseMode.HTML


def test_render_daily_success_escapes_html_and_renders_empty_lists():
    renderer = TelegramMessageRenderer()
    parsed = DailyCheckIn(
        energy=7,
        focus=6,
        satisfaction=8,
        did_today=["Shipped <feature>"],
        meaningful=[],
        drained=[],
        tomorrow_focus=["Keep & improve"],
    )

    rendered = renderer.render(
        TemplateId.CHECKIN_RESULT,
        {
            "checkin_type": "daily",
            "parsed": parsed,
        },
    )

    assert "<b>Detected as daily.</b>" in rendered.text
    assert "- Shipped &lt;feature&gt;" in rendered.text
    assert "- Keep &amp; improve" in rendered.text
    assert rendered.text.count("<i>(none)</i>") == 2
    assert "<ul>" not in rendered.text


def test_render_checkin_success_includes_optional_save_and_warning_blocks():
    renderer = TelegramMessageRenderer()
    parsed = DailyCheckIn(
        energy=7,
        focus=6,
        satisfaction=8,
        did_today=[],
        meaningful=[],
        drained=[],
        tomorrow_focus=[],
    )

    saved = renderer.render(
        TemplateId.CHECKIN_RESULT,
        {
            "checkin_type": "daily",
            "parsed": parsed,
            "saved_path": Path(r"C:\journal\daily\2026-06-03.md"),
        },
    )
    warning = renderer.render(
        TemplateId.CHECKIN_RESULT,
        {
            "checkin_type": "daily",
            "parsed": parsed,
            "save_error": "disk <full>",
        },
    )

    assert "Saved to journal: <code>C:\\journal\\daily\\2026-06-03.md</code>" in saved.text
    assert "Warning: could not save to journal: disk &lt;full&gt;" in warning.text


def test_render_review_report_converts_markdown_like_analysis_to_html():
    renderer = TelegramMessageRenderer()
    collection = ReviewCollection(
        period=ReviewPeriodSpec("2w", 14, date(2026, 5, 19), date(2026, 6, 1)),
        daily_entries=[],
        weekly_entries=[],
        coverage=ReviewCoverage(14, 12, 1, 2),
        daily_averages=DailyAveragesSummary(None, None, None),
    )

    rendered = renderer.render(
        TemplateId.REVIEW_REPORT,
        {
            "collection": collection,
            "provider": "OPENAI",
            "model": "gpt-test",
            "analysis": "**Positive trends**\n- Energy rose from **3** to **5**.\n\nPlain line.",
        },
    )

    assert "<b>Positive trends</b>" in rendered.text
    assert "- Energy rose from <b>3</b> to <b>5</b>." in rendered.text
    assert "Plain line." in rendered.text
    assert "<p>" not in rendered.text
    assert "<ul>" not in rendered.text


def test_render_statistics_report_formats_range_and_scores():
    renderer = TelegramMessageRenderer()
    collection = DailyCollection(
        entries=[
            DailyEntry(entry_date=date(2026, 5, 24), energy=7, focus=6, satisfaction=8),
            DailyEntry(entry_date=date(2026, 5, 25), energy=5, focus=4, satisfaction=6),
        ],
        target_days=28,
    )

    rendered = renderer.render(
        TemplateId.STATISTICS_REPORT,
        {"period_label": "4w", "collection": collection},
    )

    assert "<b>Statistics | 4w</b>" in rendered.text
    assert "Partial: 2 of 28 days | 2026-05-24 - 2026-05-25" in rendered.text
    assert "Energy 6.0 | Focus 5.0 | Satisfaction 7.0" in rendered.text


def test_render_log_report_formats_missing_coverage():
    renderer = TelegramMessageRenderer()
    report = JournalLogReport(
        scan=JournalScan(records=[], today=date(2026, 6, 1)),
        daily_count=10,
        weekly_count=1,
        oldest_entry_date=date(2026, 5, 19),
        weekly_gaps=[],
        verbose=True,
    )

    rendered = renderer.render(
        TemplateId.LOG_REPORT,
        {"report": report},
    )

    assert "<b>Journal Log</b>" in rendered.text
    assert "Daily entries: 10" in rendered.text
    assert "No missing daily or weekly entries." in rendered.text


def test_render_unknown_template_raises_value_error():
    renderer = TelegramMessageRenderer()

    with pytest.raises(ValueError, match="Unknown template"):
        renderer.render("missing-template", cast(dict[str, Any], {}))


def test_render_unknown_text_message_raises_value_error():
    renderer = TelegramMessageRenderer()

    with pytest.raises(ValueError, match="Unknown text message"):
        renderer.render(TemplateId.TEXT, {"text_key": "missing"})
