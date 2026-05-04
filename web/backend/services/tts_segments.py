import json
from pathlib import Path
from typing import Any

from services.job_paths import get_tts_segments_json_path
from services.job_store import ensure_job_dir, load_job, save_job
from services.tts_chunking import (
    build_tts_chunks,
    json_to_tts_chunks,
    tts_chunks_to_json,
)
from services.video_pipeline import load_captions


def _resolve_caption_source(job_id: str, stage: str = "auto") -> tuple[list[Any], str]:
    job = load_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    normalized_stage = (stage or "auto").strip()
    if normalized_stage in {"working", "edited"}:
        return load_captions(job_id, "working"), "working"
    if normalized_stage in {"source", "initial"}:
        return load_captions(job_id, "source"), "source"
    if normalized_stage == "trimmed":
        return load_captions(job_id, "trimmed"), "trimmed"
    if normalized_stage == "final":
        return load_captions(job_id, "final"), "final"

    if job.captions_trimmed_json or job.captions_trimmed or job.video_trimmed:
        captions = load_captions(job_id, "trimmed")
        if captions:
            return captions, "trimmed"
    captions = load_captions(job_id, "working")
    if captions:
        return captions, "working"
    captions = load_captions(job_id, "final")
    if captions:
        return captions, "final"
    return load_captions(job_id, "source"), "source"


def load_saved_tts_segments(job_id: str) -> dict[str, Any] | None:
    job = load_job(job_id)

    # 优先使用 job 中记录的路徑
    if job and job.tts_segments_json:
        path = Path(job.tts_segments_json)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))

    # 備用：檢查 job 目錄下的預設路徑
    from services.job_store import get_job_dir
    default_path = get_job_dir(job_id) / "tts.segments.json"
    if default_path.exists():
        return json.loads(default_path.read_text(encoding="utf-8"))

    return None


def save_tts_segments(
    job_id: str,
    segments: list[dict[str, Any]],
    *,
    requested_mode: str = "manual",
    mode_used: str = "manual",
    source_stage: str = "working",
) -> dict[str, Any]:
    job = load_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    ensure_job_dir(job_id)
    chunks = json_to_tts_chunks(segments)
    payload = {
        "requested_mode": requested_mode,
        "mode_used": mode_used,
        "source_stage": source_stage,
        "segments": tts_chunks_to_json(chunks),
    }
    path = get_tts_segments_json_path(job_id)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    job.tts_segments_json = str(path)
    save_job(job)
    return payload


def build_and_store_tts_segments(
    job_id: str,
    *,
    segment_mode: str = "ai",
    stage: str = "auto",
) -> dict[str, Any]:
    captions, source_stage = _resolve_caption_source(job_id, stage)
    if not captions:
        return {
            "requested_mode": segment_mode,
            "mode_used": "empty",
            "source_stage": source_stage,
            "segments": [],
        }

    chunks, mode_used = build_tts_chunks(captions, segment_mode=segment_mode)
    return save_tts_segments(
        job_id,
        tts_chunks_to_json(chunks),
        requested_mode=segment_mode,
        mode_used=mode_used,
        source_stage=source_stage,
    )
