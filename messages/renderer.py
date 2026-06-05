from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from html import escape
import re
from string import Template
from typing import Any, Mapping

from journal.read import DailyCollection, JournalLogReport, ReviewCollection
from journal.stats import compute_daily_averages
from journal.store import ILS_TZ
from parser import DailyCheckIn, WeeklyReview
from telegram.constants import ParseMode

from messages.templates import TEMPLATES, TEXT_MESSAGES


class TemplateId(StrEnum):
    TEXT = "text"
    CHECKIN_RESULT = "checkin_result"
    STATISTICS_REPORT = "statistics_report"
    LOG_REPORT = "log_report"
    REVIEW_REPORT = "review_report"


@dataclass(frozen=True)
class RenderedMessage:
    text: str
    parse_mode: ParseMode


class TelegramMessageRenderer:
    def __init__(
        self,
        templates: Mapping[TemplateId, str] | None = None,
        text_messages: Mapping[str, str] | None = None,
    ) -> None:
        source_templates = TEMPLATES if templates is None else templates
        self._templates = {
            TemplateId(str(key)): value for key, value in source_templates.items()
        }
        self._text_messages = dict(
            TEXT_MESSAGES if text_messages is None else text_messages
        )

    def render(
        self,
        template: TemplateId,
        message: Mapping[str, Any],
    ) -> RenderedMessage:
        template_text = self._templates.get(template)
        if template_text is None:
            raise ValueError(f"Unknown template: {template}")

        rendered = Template(template_text).substitute(
            self._build_template_values(template, message)
        )
        return RenderedMessage(text=rendered, parse_mode=ParseMode.HTML)

    def _build_template_values(
        self,
        template: TemplateId,
        message: Mapping[str, Any],
    ) -> dict[str, str]:
        if template == TemplateId.TEXT:
            return self._build_text_message(message)
        if template == TemplateId.CHECKIN_RESULT:
            return self._build_checkin_result(message)
        if template == TemplateId.STATISTICS_REPORT:
            return self._build_statistics_report(message)
        if template == TemplateId.LOG_REPORT:
            return self._build_log_report(message)
        if template == TemplateId.REVIEW_REPORT:
            return self._build_review_report(message)
        raise ValueError(f"Unsupported template: {template!r}")

    def _build_text_message(self, message: Mapping[str, Any]) -> dict[str, str]:
        text_key = str(message["text_key"])
        body_template = self._text_messages.get(text_key)
        if body_template is None:
            raise ValueError(f"Unknown text message: {text_key}")

        body_html = Template(body_template).substitute(
            {
                key: escape(str(value))
                for key, value in message.items()
                if key != "text_key"
            }
        )
        return {"body_html": body_html}

    def _build_checkin_result(self, message: Mapping[str, Any]) -> dict[str, str]:
        parsed = message["parsed"]
        return {
            "checkin_type": escape(str(message["checkin_type"])),
            "summary_html": self._render_checkin_summary(parsed),
            "save_note_html": self._render_save_note(
                saved_path=message.get("saved_path"),
                save_error=message.get("save_error"),
            ),
        }

    def _build_statistics_report(self, message: Mapping[str, Any]) -> dict[str, str]:
        period_label = escape(str(message["period_label"]))
        collection = message["collection"]
        if not isinstance(collection, DailyCollection):
            raise TypeError("collection must be a DailyCollection")

        averages = compute_daily_averages(collection)
        if averages is None or collection.date_min is None or collection.date_max is None:
            raise ValueError("statistics report requires non-empty data")

        if collection.found < collection.target_days:
            summary = (
                f"Partial: {collection.found} of {collection.target_days} days | "
                f"{collection.date_min.isoformat()} - {collection.date_max.isoformat()}"
            )
        else:
            summary = (
                f"{collection.found} days | "
                f"{collection.date_min.isoformat()} - {collection.date_max.isoformat()}"
            )

        scores = (
            f"Energy {averages.energy:.1f} | "
            f"Focus {averages.focus:.1f} | "
            f"Satisfaction {averages.satisfaction:.1f}"
        )
        return {
            "period_label": period_label,
            "summary": escape(summary),
            "scores": escape(scores),
        }

    def _build_log_report(self, message: Mapping[str, Any]) -> dict[str, str]:
        report = message["report"]
        if not isinstance(report, JournalLogReport):
            raise TypeError("report must be a JournalLogReport")

        oldest = (
            report.oldest_entry_date.isoformat()
            if report.oldest_entry_date is not None
            else "n/a"
        )
        summary_lines = [
            f"Daily entries: {report.daily_count}",
            f"Weekly entries: {report.weekly_count}",
            f"Oldest entry: {oldest}",
        ]
        summary_html = escape("\n".join(summary_lines))

        if not report.verbose:
            return {
                "summary_html": summary_html,
                "details_html": "",
            }

        if not report.has_missing_entries:
            details_html = "\n\nNo missing daily or weekly entries."
            return {
                "summary_html": summary_html,
                "details_html": escape(details_html),
            }

        blocks: list[str] = ["<b>Missing coverage</b>"]
        for gap in report.weekly_gaps:
            lines = [
                (
                    f"<b>{escape(gap.week_label)}</b> | "
                    f"{escape(gap.week_start.isoformat())} - {escape(gap.week_end.isoformat())}"
                )
            ]
            if gap.missing_daily_dates:
                dates = ", ".join(day.isoformat() for day in gap.missing_daily_dates)
                lines.append(f"Daily gaps: {escape(dates)}")
            if gap.missing_weekly_review:
                lines.append("Weekly review: missing")
            blocks.append("\n".join(lines))

        return {
            "summary_html": summary_html,
            "details_html": "\n\n" + "\n\n".join(blocks),
        }

    def _build_review_report(self, message: Mapping[str, Any]) -> dict[str, str]:
        collection = message["collection"]
        if not isinstance(collection, ReviewCollection):
            raise TypeError("collection must be a ReviewCollection")

        generated_at = datetime.now(ILS_TZ).strftime("%Y-%m-%d %H:%M")
        return {
            "period_label": escape(collection.period.label),
            "start_date": escape(collection.period.start_date.isoformat()),
            "end_date": escape(collection.period.end_date.isoformat()),
            "timezone": escape(str(ILS_TZ)),
            "found_daily_count": escape(str(collection.coverage.found_daily_count)),
            "expected_daily_days": escape(str(collection.coverage.expected_daily_days)),
            "found_weekly_count": escape(str(collection.coverage.found_weekly_count)),
            "provider": escape(str(message["provider"])),
            "model": escape(str(message["model"])),
            "generated_at": escape(generated_at),
            "analysis_html": self._render_review_analysis_html(str(message["analysis"])),
        }

    def _render_checkin_summary(self, parsed: Any) -> str:
        if isinstance(parsed, DailyCheckIn):
            sections = [
                self._render_named_list("Did today", parsed.did_today),
                self._render_named_list("Meaningful", parsed.meaningful),
                self._render_named_list("Drained", parsed.drained),
                self._render_named_list("Tomorrow focus", parsed.tomorrow_focus),
            ]
            scores = (
                f"Energy {parsed.energy}/10 | "
                f"Focus {parsed.focus}/10 | "
                f"Satisfaction {parsed.satisfaction}/10"
            )
            return (
                "<b>Parsed daily check-in</b>\n\n"
                f"{escape(scores)}\n\n"
                + "\n\n".join(sections)
            )

        if isinstance(parsed, WeeklyReview):
            sections = [
                self._render_named_list("Momentum", parsed.momentum),
                self._render_named_list("Friction", parsed.friction),
                self._render_named_list("Avoidance", parsed.avoidance),
                self._render_named_list("Meaningful", parsed.meaningful),
                self._render_named_list("Fake productivity", parsed.fake_productivity),
                self._render_named_list("Next week focus", parsed.next_week_focus),
            ]
            return "<b>Parsed weekly review</b>\n\n" + "\n\n".join(sections)

        raise TypeError("parsed must be a DailyCheckIn or WeeklyReview")

    def _render_named_list(self, title: str, items: list[str]) -> str:
        return f"<b>{escape(title)}</b>\n{self._render_list(items)}"

    def _render_list(self, items: list[str]) -> str:
        if not items:
            return "<i>(none)</i>"
        return "\n".join(f"- {escape(item)}" for item in items)

    def _render_save_note(
        self,
        *,
        saved_path: Any | None,
        save_error: Any | None,
    ) -> str:
        if saved_path is not None:
            return f"\n\nSaved to journal: <code>{escape(str(saved_path))}</code>"
        if save_error is not None:
            return f"\n\nWarning: could not save to journal: {escape(str(save_error))}"
        return ""

    def _render_review_inline_html(self, text: str) -> str:
        parts: list[str] = []
        cursor = 0
        for match in re.finditer(r"\*\*(.+?)\*\*", text):
            parts.append(escape(text[cursor : match.start()]))
            parts.append(f"<b>{escape(match.group(1))}</b>")
            cursor = match.end()
        parts.append(escape(text[cursor:]))
        return "".join(parts)

    def _render_review_analysis_html(self, text: str) -> str:
        blocks: list[str] = []
        paragraph_lines: list[str] = []
        list_items: list[str] = []

        def flush_paragraph() -> None:
            if paragraph_lines:
                blocks.append("\n".join(paragraph_lines))
                paragraph_lines.clear()

        def flush_list() -> None:
            if list_items:
                blocks.append("\n".join(f"- {item}" for item in list_items))
                list_items.clear()

        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                flush_paragraph()
                flush_list()
                continue

            if stripped.startswith("- "):
                flush_paragraph()
                list_items.append(self._render_review_inline_html(stripped[2:].strip()))
                continue

            flush_list()
            paragraph_lines.append(self._render_review_inline_html(stripped))

        flush_paragraph()
        flush_list()
        return "\n\n".join(blocks)
