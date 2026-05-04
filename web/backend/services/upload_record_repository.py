"""Upload record repository for upload_records table CRUD operations."""

import datetime
import hashlib
from typing import Optional, List

from services.db import get_cursor


UPLOAD_RECORD_COLUMNS = {
    "id",
    "job_id",
    "platform",
    "account_id",
    "title",
    "desc",
    "tags",
    "video_path",
    "success",
    "status",
    "url",
    "error",
    "output",
    "log_path",
    "created_at",
    "updated_at",
}
UPLOAD_RECORD_MUTABLE_COLUMNS = UPLOAD_RECORD_COLUMNS - {"id", "created_at"}


def get_all_records(limit: int = 100) -> List[dict]:
    """Get all upload records."""
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT * FROM upload_records ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def query_records(
    platform: str = None,
    status: str = None,
    days: int = None,
    limit: int = 1000,
) -> List[dict]:
    """Query records with optional combined filters."""
    where_clauses = []
    values = []

    if platform:
        where_clauses.append("platform = ?")
        values.append(platform)

    if status == "success":
        where_clauses.append("success = 1")
    elif status == "failed":
        where_clauses.append("success = 0")

    if days:
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()
        where_clauses.append("created_at > ?")
        values.append(cutoff)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    values.append(limit)

    with get_cursor() as cursor:
        cursor.execute(
            f"SELECT * FROM upload_records {where_sql} ORDER BY created_at DESC LIMIT ?",
            values,
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_record(record_id: str) -> Optional[dict]:
    """Get a single record by ID."""
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM upload_records WHERE id = ?", (record_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def create_record(
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
    """Create a new upload record."""
    record_id = hashlib.md5(
        f"{job_id}{platform}{account_id}{datetime.datetime.now().isoformat()}".encode()
    ).hexdigest()[:8]
    
    now = datetime.datetime.now().isoformat()
    
    record = {
        "id": record_id,
        "job_id": job_id,
        "platform": platform,
        "account_id": account_id,
        "title": title,
        "desc": desc,
        "tags": tags,
        "video_path": video_path,
        "success": 1 if success else 0,
        "status": status or ("success" if success else "failed"),
        "url": url,
        "error": error,
        "output": output,
        "log_path": log_path,
        "created_at": now,
        "updated_at": now,
    }
    
    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO upload_records (
                id, job_id, platform, account_id, title, `desc`, tags,
                video_path, success, status, url, error, output, log_path,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record["id"], record["job_id"], record["platform"], record["account_id"],
            record["title"], record["desc"], record["tags"], record["video_path"],
            record["success"], record["status"], record["url"], record["error"],
            record["output"], record["log_path"], record["created_at"], record["updated_at"],
        ))
    
    return record


def update_record(record_id: str, updates: dict) -> Optional[dict]:
    """Update a record with given fields."""
    updates = {k: v for k, v in updates.items() if k in UPLOAD_RECORD_MUTABLE_COLUMNS}
    if not updates:
        return get_record(record_id)
    updates["updated_at"] = datetime.datetime.now().isoformat()
    
    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [record_id]
    
    with get_cursor() as cursor:
        cursor.execute(f"UPDATE upload_records SET {set_clause} WHERE id = ?", values)
        if cursor.rowcount == 0:
            return None
    
    return get_record(record_id)


def delete_record(record_id: str) -> bool:
    """Delete a record."""
    with get_cursor() as cursor:
        cursor.execute("DELETE FROM upload_records WHERE id = ?", (record_id,))
        return cursor.rowcount > 0


def get_records_by_platform(platform: str, limit: int = 100) -> List[dict]:
    """Get records filtered by platform."""
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT * FROM upload_records WHERE platform = ? ORDER BY created_at DESC LIMIT ?",
            (platform, limit)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_records_by_status(success: bool, limit: int = 100) -> List[dict]:
    """Get records filtered by success status."""
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT * FROM upload_records WHERE success = ? ORDER BY created_at DESC LIMIT ?",
            (1 if success else 0, limit)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_records_by_job(job_id: str) -> List[dict]:
    """Get all records for a specific job."""
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT * FROM upload_records WHERE job_id = ? ORDER BY created_at DESC",
            (job_id,)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def import_from_dict(record_data: dict) -> dict:
    """Import a record from a dict into database."""
    record_data = {k: v for k, v in record_data.items() if k in UPLOAD_RECORD_COLUMNS}
    if "success" in record_data and isinstance(record_data["success"], bool):
        record_data["success"] = 1 if record_data["success"] else 0
    
    record_data["updated_at"] = datetime.datetime.now().isoformat()
    
    with get_cursor() as cursor:
        columns = ["id", "job_id", "platform", "account_id", "title", "desc", "tags",
                   "video_path", "success", "status", "url", "error", "output",
                   "log_path", "created_at", "updated_at"]
        
        values = []
        for col in columns:
            val = record_data.get(col, "")
            if col == "success" and isinstance(val, bool):
                val = 1 if val else 0
            values.append(val)
        
        cursor.execute("""
            INSERT OR REPLACE INTO upload_records (
                id, job_id, platform, account_id, title, `desc`, tags,
                video_path, success, status, url, error, output, log_path,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, values)
    
    return record_data
