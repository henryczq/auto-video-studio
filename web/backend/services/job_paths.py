from pathlib import Path

from services.job_store import ensure_job_dir, get_job_dir, get_logs_dir


def get_original_video_path(job_id: str) -> Path:
    return get_job_dir(job_id) / "original.mp4"


def get_source_video_path(job_id: str) -> Path:
    return get_job_dir(job_id) / "source.input.mp4"


def get_processed_video_path(job_id: str) -> Path:
    return get_job_dir(job_id) / "processed.mp4"


def get_initial_captions_srt_path(job_id: str) -> Path:
    return get_job_dir(job_id) / "captions.initial.srt"


def get_initial_captions_json_path(job_id: str) -> Path:
    return get_job_dir(job_id) / "captions.initial.json"


def get_edited_captions_json_path(job_id: str) -> Path:
    return get_job_dir(job_id) / "captions.edited.json"


def get_final_captions_srt_path(job_id: str) -> Path:
    return get_job_dir(job_id) / "captions.final.srt"


def get_tts_segments_json_path(job_id: str) -> Path:
    return get_job_dir(job_id) / "tts.segments.json"


def get_process_log_path(job_id: str) -> Path:
    return get_logs_dir(job_id) / "process.log"
