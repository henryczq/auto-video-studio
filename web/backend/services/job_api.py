from difflib import SequenceMatcher
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException

from services.background_jobs import is_background_job_active
from services.job_store import load_all_jobs, load_job, save_job
from services.tts_generate import DEFAULT_TTS_PARALLEL, DEFAULT_TTS_THREADS
from services.tts_profiles import get_tts_defaults


PROFILE_DEFAULTS = get_tts_defaults()
DEFAULT_TTS_REQUEST = {
    "tts_provider": PROFILE_DEFAULTS.get("tts_provider", "cosyvoice"),
    "tts_runtime_env": PROFILE_DEFAULTS.get("tts_runtime_env", "rocm6.3"),
    "tts_mode": PROFILE_DEFAULTS.get("tts_mode", "instruct2"),
    "segment_mode": "ai",
    "model_name": PROFILE_DEFAULTS.get("tts_model", "Fun-CosyVoice3-0.5B-2512_RL"),
    "model_dir": None,
    "prompt_text": PROFILE_DEFAULTS.get("tts_prompt_text", "各位朋友大家好，我是振振公子，今天我来演示一下利用"),
    "speed": 1.0,
    "max_speedup": 1.18,
    "rocm_gfx_override": PROFILE_DEFAULTS.get("rocm_gfx_override"),
    "disable_text_frontend": False,
    "threads": int(PROFILE_DEFAULTS.get("tts_threads", DEFAULT_TTS_THREADS)),
    "parallel": int(PROFILE_DEFAULTS.get("tts_parallel", DEFAULT_TTS_PARALLEL)),
    "tts_executor": PROFILE_DEFAULTS.get("tts_executor", "workers"),
    "emo_text": PROFILE_DEFAULTS.get("tts_cosyvoice_style_text", ""),
    "emo_alpha": 0.6,
    "reuse_chunks": True,
    "serial_chunk_timeout": int(PROFILE_DEFAULTS.get("tts_serial_chunk_timeout", 1200)),
}


def list_jobs_sorted(limit: int = 50, offset: int = 0):
    return load_all_jobs(limit=max(1, limit), offset=max(0, offset))


def require_job(job_id: str):
    job = load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    reconcile_background_status(job)
    return job


def _parse_updated_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def reconcile_background_status(job):
    background_status_errors = {
        "processing": ("process_error", "视频处理后台任务已中断或服务已重启，请重新提交视频处理。"),
        "video_processing": ("process_error", "视频处理后台任务已中断或服务已重启，请重新提交视频处理。"),
        "tts_processing": ("tts_error", "TTS 后台任务已中断或服务已重启，请使用“续跑缺失分块”重新提交。"),
        "composing": ("compose_error", "视频合成后台任务已中断或服务已重启，请重新提交合成。"),
    }
    if job.status not in background_status_errors:
        return job
    if is_background_job_active(job.id):
        return job
    updated_at = _parse_updated_at(getattr(job, "updated_at", None))
    if updated_at and datetime.now() - updated_at < timedelta(seconds=15):
        return job
    error_field, error_message = background_status_errors[job.status]
    job.status = "error"
    setattr(job, error_field, error_message)
    save_job(job)
    return job


def mark_job_status(job_id: str, status: str):
    job = require_job(job_id)
    job.status = status
    if status in ("processing", "video_processing"):
        job.process_error = None
        job.processed_video = None
        job.captions_initial = None
        job.captions_initial_json = None
    elif status == "tts_processing":
        job.tts_error = None
        job.compose_error = None
        job.voiceover = None
        job.final_replace_audio = None
        job.final_subtitles_only = None
    elif status == "composing":
        job.compose_error = None
        job.final_replace_audio = None
        job.final_subtitles_only = None
    save_job(job)
    return job


def _request_value(req: Any, name: str, default: Any = None):
    if isinstance(req, dict):
        return req.get(name, default)
    return getattr(req, name, default)


def prepare_process_video_kwargs(req: Any) -> dict[str, Any]:
    return {
        "margin": _request_value(req, "margin", 3.0),
        "silence_noise": _request_value(req, "silence_noise", "-35dB"),
        "silence_min_duration": _request_value(req, "silence_min_duration", 5.0),
        "silence_keep": _request_value(req, "silence_keep", 1.0),
        "model": _request_value(req, "model", "base"),
        "device": _request_value(req, "device", "cpu"),
        "rocm_gfx_override": _request_value(req, "rocm_gfx_override"),
    }


def prepare_tts_kwargs(req: Any) -> dict[str, Any]:
    payload = dict(DEFAULT_TTS_REQUEST)
    for key, default in DEFAULT_TTS_REQUEST.items():
        payload[key] = _request_value(req, key, default)
    return payload


def prepare_compose_mode(req: Any) -> str:
    mode = (_request_value(req, "mode", "replace_audio") or "replace_audio").strip()
    return mode or "replace_audio"


def build_prompt_verify_result(result: dict[str, Any], prompt_text: str) -> dict[str, Any]:
    transcribed_text = str(result.get("transcribed_text", "") or "").strip()
    expected_text = (prompt_text or "").strip()

    if expected_text:
        similarity = int(round(SequenceMatcher(None, transcribed_text, expected_text).ratio() * 100))
        if similarity >= 85:
            match_status = "匹配"
        elif similarity >= 50:
            match_status = "部分匹配"
        else:
            match_status = "不匹配"
    else:
        similarity = 0
        match_status = "未提供参考文本"

    return {
        **result,
        "prompt_text": expected_text,
        "similarity": similarity,
        "match_status": match_status,
    }
