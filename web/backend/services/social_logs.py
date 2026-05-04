"""Social upload logs - now backed by SQLite database for records."""

import datetime
from pathlib import Path
from typing import List, Optional

from services.upload_record_repository import (
    get_all_records as db_get_all_records,
    get_record as db_get_record,
    query_records as db_query_records,
    create_record as db_create_record,
    update_record as db_update_record,
    delete_record as db_delete_record,
    get_records_by_job as db_get_records_by_job,
)

ROOT_DIR = Path(__file__).parent.parent.parent.parent
LOGS_DIR = ROOT_DIR / "logs" / "social_upload" / "accounts"
UPLOAD_RECORDS_FILE = ROOT_DIR / "logs" / "social_upload" / "upload_records.json"
STALE_RUNNING_SECONDS = 150


def ensure_logs_dir():
    """Ensure logs directory exists."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def get_account_log(account_id: str) -> str:
    """Get account log content from file."""
    log_file = LOGS_DIR / f"{account_id}.log"
    if not log_file.exists():
        return ""
    return log_file.read_text(encoding="utf-8")


def _parse_iso_datetime(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except ValueError:
        return None


def _resolve_record_log_path(record: dict) -> Path | None:
    raw_path = (record.get("log_path") or "").strip()
    if raw_path:
        path = Path(raw_path)
        return path if path.is_absolute() else (ROOT_DIR / path)

    job_id = record.get("job_id")
    platform = record.get("platform")
    if not job_id or not platform:
        return None
    return ROOT_DIR / "videos" / "web_jobs" / job_id / "logs" / f"upload-{platform}.log"


def _reconcile_stale_running_record(record: dict) -> dict:
    if record.get("status") != "running":
        return record

    now = datetime.datetime.now()
    updated_at = _parse_iso_datetime(record.get("updated_at")) or _parse_iso_datetime(record.get("created_at"))
    if not updated_at:
        return record

    age_seconds = (now - updated_at).total_seconds()
    if age_seconds < STALE_RUNNING_SECONDS:
        return record

    log_path = _resolve_record_log_path(record)
    log_is_stale = True
    if log_path and log_path.exists():
        log_mtime = datetime.datetime.fromtimestamp(log_path.stat().st_mtime)
        log_is_stale = (now - log_mtime).total_seconds() >= STALE_RUNNING_SECONDS

    if not log_is_stale:
        return record

    message = "后台发布任务已中断，可能是服务重启或上传进程异常退出，请重新发起。"
    refreshed = db_update_record(
        record["id"],
        {
            "success": 0,
            "status": "failed",
            "error": record.get("error") or message,
            "output": record.get("output") or "",
        },
    )
    return refreshed or {**record, "success": 0, "status": "failed", "error": message}


def get_upload_log(job_id: str, platform: str) -> str:
    """Get upload log content from the per-job log file."""
    log_file = ROOT_DIR / "videos" / "web_jobs" / job_id / "logs" / f"upload-{platform}.log"
    if not log_file.exists():
        return ""
    return log_file.read_text(encoding="utf-8")


def load_upload_records() -> List[dict]:
    """Load all upload records from database."""
    return [_reconcile_stale_running_record(record) for record in db_get_all_records(limit=1000)]


def save_upload_records(records: List[dict]) -> None:
    """Save upload records (for backwards compatibility with file)."""
    pass


def get_upload_record(record_id: str) -> Optional[dict]:
    """Get a single upload record by ID."""
    record = db_get_record(record_id)
    if not record:
        return None
    return _reconcile_stale_running_record(record)


def add_upload_record(
    job_id: str,
    platform: str,
    account_id: str,
    title: str,
    video_path: str,
    success: bool,
    desc: str = "",
    tags: str = "",
    output: str = "",
    error: str = "",
    url: str = "",
    status: str = "",
    log_path: str = "",
) -> dict:
    """Add a new upload record."""
    return db_create_record(
        job_id=job_id,
        platform=platform,
        account_id=account_id,
        title=title,
        video_path=video_path,
        success=success,
        desc=desc,
        tags=tags,
        output=output,
        error=error,
        url=url,
        status=status,
        log_path=log_path,
    )


def get_upload_records(
    platform: str = None,
    status: str = None,
    days: int = None,
) -> List[dict]:
    """Get upload records with optional filters."""
    return [
        _reconcile_stale_running_record(record)
        for record in db_query_records(platform=platform, status=status, days=days, limit=1000)
    ]


def update_upload_record(record_id: str, updates: dict) -> Optional[dict]:
    """Update an upload record."""
    return db_update_record(record_id, updates)


def delete_upload_record(record_id: str) -> bool:
    """Delete an upload record."""
    return db_delete_record(record_id)


def get_upload_records_for_job(job_id: str) -> List[dict]:
    """Get all upload records for a specific job."""
    return [_reconcile_stale_running_record(record) for record in db_get_records_by_job(job_id)]
