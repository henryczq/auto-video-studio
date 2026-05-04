"""Job repository for jobs table CRUD operations."""

import datetime
import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from services.db import get_cursor, get_connection

logger = logging.getLogger(__name__)

JOBS_DIR = Path(__file__).parent.parent.parent.parent / "videos" / "web_jobs"
JOB_COLUMNS = {
    "id",
    "status",
    "created_at",
    "updated_at",
    "name",
    "video_filename",
    "source_video",
    "source_start",
    "source_end",
    "processed_video",
    "captions_initial",
    "captions_initial_json",
    "captions_edited",
    "captions_final",
    "captions_cut_marks",
    "video_trimmed",
    "captions_trimmed_json",
    "captions_trimmed",
    "optimized_audio",
    "video_audio_optimized",
    "final_subtitles_video",
    "tts_segments_json",
    "voiceover",
    "final_replace_audio",
    "final_subtitles_only",
    "captions_version",
    "trim_version",
    "tts_version",
    "compose_version",
    "process_error",
    "tts_error",
    "trim_error",
    "compose_error",
}
JOB_MUTABLE_COLUMNS = JOB_COLUMNS - {"id", "created_at"}


def get_job_dir(job_id: str) -> Path:
    return JOBS_DIR / job_id


def ensure_job_dir(job_id: str) -> Path:
    job_dir = get_job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "logs").mkdir(exist_ok=True)
    return job_dir


def get_all_jobs(limit: int | None = None, offset: int = 0) -> list:
    """Get all jobs from database."""
    query = "SELECT * FROM jobs ORDER BY created_at DESC"
    params: list[object] = []
    if limit is not None:
        query += " LIMIT ? OFFSET ?"
        params.extend([limit, max(0, offset)])
    with get_cursor() as cursor:
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_job(job_id: str) -> Optional[dict]:
    """Get a single job by ID."""
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def create_job(video_filename: str, name: Optional[str] = None) -> dict:
    """Create a new job."""
    job_id = str(uuid.uuid4())[:8]
    now = datetime.datetime.now().isoformat()
    
    job = {
        "id": job_id,
        "status": "created",
        "created_at": now,
        "updated_at": now,
        "name": name,
        "video_filename": video_filename,
        "source_video": None,
        "source_start": None,
        "source_end": None,
    }
    
    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO jobs (
                id, status, created_at, updated_at, name, video_filename, source_video, source_start, source_end
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job["id"], job["status"], job["created_at"],
            job["updated_at"], job["name"], job["video_filename"],
            job["source_video"], job["source_start"], job["source_end"]
        ))
    
    ensure_job_dir(job_id)
    _save_json_fallback(job_id, job)
    
    return job


def update_job(job_id: str, updates: dict) -> Optional[dict]:
    """Update a job with given fields."""
    updates = {k: v for k, v in updates.items() if k in JOB_MUTABLE_COLUMNS}
    if not updates:
        return get_job(job_id)

    updates["updated_at"] = datetime.datetime.now().isoformat()
    
    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [job_id]
    
    with get_cursor() as cursor:
        cursor.execute(f"UPDATE jobs SET {set_clause} WHERE id = ?", values)
        if cursor.rowcount == 0:
            return None
    
    job = get_job(job_id)
    _save_json_fallback(job_id, job)
    
    return job


def delete_job(job_id: str) -> bool:
    """Delete a job."""
    with get_cursor() as cursor:
        cursor.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        deleted = cursor.rowcount > 0
    
    if deleted:
        job_dir = get_job_dir(job_id)
        job_file = job_dir / "job.json"
        if job_file.exists():
            job_file.unlink()
    
    return deleted


def job_exists(job_id: str) -> bool:
    """Check if a job exists."""
    with get_cursor() as cursor:
        cursor.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,))
        return cursor.fetchone() is not None


def _save_json_fallback(job_id: str, job: dict):
    """Save job to JSON file for backwards compatibility."""
    job_dir = ensure_job_dir(job_id)
    job_file = job_dir / "job.json"
    try:
        with open(job_file, "w", encoding="utf-8") as f:
            json.dump(job, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save job.json fallback for {job_id}: {e}")


def import_from_json(job_id: str, job_data: dict) -> dict:
    """Import a job from JSON data into database."""
    job_data = {k: v for k, v in job_data.items() if k in JOB_COLUMNS}
    job_data["updated_at"] = datetime.datetime.now().isoformat()
    
    with get_cursor() as cursor:
        columns = list(job_data.keys())
        placeholders = ",".join(["?"] * len(columns))
        column_names = ",".join(columns)
        
        cursor.execute(f"""
            INSERT OR REPLACE INTO jobs ({column_names})
            VALUES ({placeholders})
        """, list(job_data.values()))
    
    return job_data
