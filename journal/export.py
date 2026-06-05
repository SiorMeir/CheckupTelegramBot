from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
import tempfile
import zipfile

from telegram.constants import FileSizeLimit

from journal.read import JournalScan
from journal.store import ILS_TZ, JournalStore


@dataclass(frozen=True)
class JournalArchive:
    status: str
    file_count: int
    archive_path: Path | None = None
    archive_size: int = 0
    upload_limit: int = int(FileSizeLimit.FILESIZE_UPLOAD)
    cleanup_after_send: bool = False


def build_journal_archive(
    store: JournalStore,
    scan: JournalScan,
    *,
    now: datetime | None = None,
    upload_limit: int = int(FileSizeLimit.FILESIZE_UPLOAD),
) -> JournalArchive:
    file_paths = sorted((record.path for record in scan.records), key=lambda path: str(path))
    if not file_paths:
        return JournalArchive(status="empty", file_count=0, upload_limit=upload_limit)

    timestamp = _timestamp(now)
    temp_path = Path(
        tempfile.NamedTemporaryFile(
            prefix=f"journal-export-{timestamp}-",
            suffix=".zip",
            delete=False,
        ).name
    )

    try:
        with zipfile.ZipFile(temp_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in file_paths:
                relative_path = path.relative_to(store.root)
                archive.write(path, arcname=Path("journal") / relative_path)

        archive_size = temp_path.stat().st_size
        if archive_size <= upload_limit:
            return JournalArchive(
                status="ready",
                file_count=len(file_paths),
                archive_path=temp_path,
                archive_size=archive_size,
                upload_limit=upload_limit,
                cleanup_after_send=True,
            )

        exports_dir = store.root / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)
        persisted_path = exports_dir / f"journal-export-{timestamp}.zip"
        shutil.move(str(temp_path), persisted_path)
        return JournalArchive(
            status="too_large",
            file_count=len(file_paths),
            archive_path=persisted_path,
            archive_size=archive_size,
            upload_limit=upload_limit,
        )
    except Exception:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise


def _timestamp(now: datetime | None) -> str:
    effective_now = datetime.now(ILS_TZ) if now is None else now.astimezone(ILS_TZ)
    return effective_now.strftime("%Y%m%d-%H%M%S-%f")
