import asyncio
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import app
from journal.export import JournalArchive
from journal.read import JournalLogReport, JournalMissingWeek, JournalScan
from messages import TemplateId
from telegram.constants import ParseMode


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
    return context


def _sample_log_report(*, verbose: bool) -> JournalLogReport:
    gaps = []
    if verbose:
        gaps = [
            JournalMissingWeek(
                week_label="2026-week-22",
                week_start=date(2026, 5, 24),
                week_end=date(2026, 5, 30),
                missing_daily_dates=[date(2026, 5, 27), date(2026, 5, 30)],
                missing_weekly_review=True,
            )
        ]
    return JournalLogReport(
        scan=JournalScan(records=[], today=date(2026, 6, 1)),
        daily_count=10,
        weekly_count=1,
        oldest_entry_date=date(2026, 5, 19),
        weekly_gaps=gaps,
        verbose=verbose,
    )


def test_log_command_formats_summary(monkeypatch):
    update = _make_update()
    context = _make_context([])
    reader = MagicMock()
    reader.collect_log_report.return_value = _sample_log_report(verbose=False)
    monkeypatch.setattr(app, "journal_reader", reader)

    _run(app.log_command(update, context))

    reader.collect_log_report.assert_called_once_with(verbose=False)
    reply = update.message.reply_text.await_args.args[0]
    assert "<b>Journal Log</b>" in reply
    assert "Daily entries: 10" in reply
    assert "Weekly entries: 1" in reply
    assert "Oldest entry: 2026-05-19" in reply
    assert update.message.reply_text.await_args.kwargs["parse_mode"] == ParseMode.HTML


def test_log_command_formats_verbose_missing_groups(monkeypatch):
    update = _make_update()
    context = _make_context(["verbose"])
    reader = MagicMock()
    reader.collect_log_report.return_value = _sample_log_report(verbose=True)
    monkeypatch.setattr(app, "journal_reader", reader)

    _run(app.log_command(update, context))

    reply = update.message.reply_text.await_args.args[0]
    assert "<b>Missing coverage</b>" in reply
    assert "<b>2026-week-22</b> | 2026-05-24 - 2026-05-30" in reply
    assert "Daily gaps: 2026-05-27, 2026-05-30" in reply
    assert "Weekly review: missing" in reply


def test_log_command_rejects_invalid_args():
    update = _make_update()
    context = _make_context(["verbose", "extra"])

    _run(app.log_command(update, context))

    assert (
        update.message.reply_text.await_args.args[0]
        == app.message_renderer.render(TemplateId.TEXT, {"text_key": "log_usage"}).text
    )


def test_dump_command_sends_zip_archive_and_cleans_up(tmp_path, monkeypatch):
    update = _make_update()
    context = _make_context([])
    archive_path = tmp_path / "journal-export.zip"
    archive_path.write_bytes(b"zip")

    monkeypatch.setattr(app, "journal_reader", MagicMock(scan_journal=MagicMock(return_value=MagicMock())))
    monkeypatch.setattr(
        app,
        "build_journal_archive",
        MagicMock(
            return_value=JournalArchive(
                status="ready",
                file_count=2,
                archive_path=archive_path,
                archive_size=3,
                cleanup_after_send=True,
            )
        ),
    )

    _run(app.dump_command(update, context))

    kwargs = update.message.reply_document.await_args.kwargs
    assert kwargs["document"] == archive_path
    assert kwargs["filename"] == "journal-export.zip"
    assert kwargs["caption"] == "Journal export | 2 files | 3 bytes"
    assert not archive_path.exists()


def test_dump_command_reports_oversized_archive(monkeypatch):
    update = _make_update()
    context = _make_context([])
    monkeypatch.setattr(app, "journal_reader", MagicMock(scan_journal=MagicMock(return_value=MagicMock())))
    monkeypatch.setattr(
        app,
        "build_journal_archive",
        MagicMock(
            return_value=JournalArchive(
                status="too_large",
                file_count=4,
                archive_path=Path(r"C:\journal\exports\journal-export.zip"),
                archive_size=60,
                upload_limit=50,
            )
        ),
    )

    _run(app.dump_command(update, context))

    reply = update.message.reply_text.await_args.args[0]
    assert "Archive ready but too large to send via Telegram" in reply
    assert "Files: 4" in reply
    assert "C:\\journal\\exports\\journal-export.zip" in reply
    update.message.reply_document.assert_not_awaited()


def test_dump_command_reports_empty_export(monkeypatch):
    update = _make_update()
    context = _make_context([])
    monkeypatch.setattr(app, "journal_reader", MagicMock(scan_journal=MagicMock(return_value=MagicMock())))
    monkeypatch.setattr(
        app,
        "build_journal_archive",
        MagicMock(return_value=JournalArchive(status="empty", file_count=0)),
    )

    _run(app.dump_command(update, context))

    assert (
        update.message.reply_text.await_args.args[0]
        == app.message_renderer.render(TemplateId.TEXT, {"text_key": "dump_empty"}).text
    )


def test_dump_command_reports_archive_build_failure(monkeypatch):
    update = _make_update()
    context = _make_context([])
    monkeypatch.setattr(app, "journal_reader", MagicMock(scan_journal=MagicMock(return_value=MagicMock())))
    monkeypatch.setattr(
        app,
        "build_journal_archive",
        MagicMock(side_effect=OSError("disk full")),
    )

    _run(app.dump_command(update, context))

    assert "Dump failed while creating or sending the archive: disk full" in (
        update.message.reply_text.await_args.args[0]
    )
