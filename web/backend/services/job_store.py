"""Job store - now backed by SQLite database with JSON fallback."""

import datetime
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Optional, Dict

from services.job_repository import (
    get_all_jobs as db_get_all_jobs,
    get_job as db_get_job,
    create_job as db_create_job,
    update_job as db_update_job,
    delete_job as db_delete_job,
    job_exists as db_job_exists,
    get_job_dir as repo_get_job_dir,
    ensure_job_dir as repo_ensure_job_dir,
)


JOBS_DIR = Path(__file__).parent.parent.parent.parent / "videos" / "web_jobs"


@dataclass
class Job:
    id: str
    status: str
    created_at: str
    
    name: Optional[str] = None
    video_filename: Optional[str] = None
    source_video: Optional[str] = None
    source_start: Optional[str] = None
    source_end: Optional[str] = None
    
    # Video paths
    processed_video: Optional[str] = None
    video_trimmed: Optional[str] = None
    optimized_audio: Optional[str] = None
    video_audio_optimized: Optional[str] = None
    final_subtitles_video: Optional[str] = None
    
    # Caption paths (legacy, will be phased out)
    captions_initial: Optional[str] = None
    captions_initial_json: Optional[str] = None
    captions_edited: Optional[str] = None
    captions_final: Optional[str] = None
    captions_cut_marks: Optional[str] = None
    captions_trimmed_json: Optional[str] = None
    captions_trimmed: Optional[str] = None
    
    # TTS/voiceover paths
    tts_segments_json: Optional[str] = None
    voiceover: Optional[str] = None
    final_replace_audio: Optional[str] = None
    final_subtitles_only: Optional[str] = None
    
    # Version tracking for derived outputs
    captions_version: int = 0
    trim_version: int = 0
    tts_version: int = 0
    compose_version: int = 0
    
    # Timestamps
    updated_at: Optional[str] = None
    
    # Legacy error fields (kept for compatibility)
    process_error: Optional[str] = None
    tts_error: Optional[str] = None
    trim_error: Optional[str] = None
    compose_error: Optional[str] = None
    
    @property
    def errors(self) -> Dict[str, str]:
        """Get all errors as a dict."""
        return {
            "process": self.process_error or "",
            "tts": self.tts_error or "",
            "trim": self.trim_error or "",
            "compose": self.compose_error or "",
        }
    
    def is_stale(self, derive_type: str) -> bool:
        """Check if a derived output is stale.
        
        Args:
            derive_type: 'trim', 'tts', 'compose', 'srt'
        
        Returns:
            True if the derived output needs regeneration.
        """
        if derive_type == "trim":
            return self.trim_version < self.captions_version or self.trim_version == 0
        elif derive_type == "tts":
            return self.tts_version < self.captions_version or self.tts_version == 0
        elif derive_type == "compose":
            return self.compose_version < self.captions_version or self.compose_version == 0
        elif derive_type == "srt":
            return self.captions_version == 0 or not self.captions_final
        return False


def _dict_to_job(data: dict) -> Job:
    """Convert dict to Job dataclass."""
    if data is None:
        return None
    job_fields = {f.name for f in fields(Job)}
    filtered = {k: v for k, v in data.items() if k in job_fields}
    return Job(**filtered)


def _job_to_dict(job: Job) -> dict:
    """Convert Job dataclass to dict."""
    return asdict(job)


def get_job_dir(job_id: str) -> Path:
    return repo_get_job_dir(job_id)


def get_logs_dir(job_id: str) -> Path:
    return get_job_dir(job_id) / "logs"


def ensure_job_dir(job_id: str) -> Path:
    return repo_ensure_job_dir(job_id)


def load_job(job_id: str) -> Optional[Job]:
    data = db_get_job(job_id)
    return _dict_to_job(data)


def load_all_jobs(limit: int | None = None, offset: int = 0) -> list[Job]:
    jobs = db_get_all_jobs(limit=limit, offset=offset)
    return [_dict_to_job(j) for j in jobs]


def save_job(job: Job) -> None:
    data = _job_to_dict(job)
    if "updated_at" not in data:
        data["updated_at"] = datetime.datetime.now().isoformat()
    db_update_job(job.id, data)


def create_job(video_filename: str, name: Optional[str] = None) -> Job:
    data = db_create_job(video_filename, name)
    return _dict_to_job(data)


def update_job_fields(job_id: str, **kwargs) -> Optional[Job]:
    data = db_update_job(job_id, kwargs)
    return _dict_to_job(data)


def delete_job(job_id: str) -> bool:
    return db_delete_job(job_id)


def job_exists(job_id: str) -> bool:
    return db_job_exists(job_id)


def increment_captions_version(job_id: str) -> Job:
    """Increment captions version when working captions are modified."""
    job = load_job(job_id)
    if job:
        job.captions_version = (job.captions_version or 0) + 1
        save_job(job)
    return job


def mark_trim_stale(job_id: str) -> Job:
    """Mark trim derived outputs as stale."""
    job = load_job(job_id)
    if job:
        job.trim_version = 0
        save_job(job)
    return job


def mark_tts_stale(job_id: str) -> Job:
    """Mark TTS derived outputs as stale."""
    job = load_job(job_id)
    if job:
        job.tts_version = 0
        save_job(job)
    return job


def mark_compose_stale(job_id: str) -> Job:
    """Mark compose derived outputs as stale."""
    job = load_job(job_id)
    if job:
        job.compose_version = 0
        save_job(job)
    return job
