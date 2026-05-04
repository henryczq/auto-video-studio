import math
from pathlib import Path
from typing import List, Optional

from services.captions import (
    Caption,
    read_srt,
    write_srt,
    read_json,
    write_json,
)
from services.caption_store import CaptionStore
from services.job_paths import (
    get_edited_captions_json_path,
    get_final_captions_srt_path,
    get_initial_captions_json_path,
    get_initial_captions_srt_path,
    get_original_video_path,
    get_source_video_path,
    get_process_log_path,
    get_processed_video_path,
    get_tts_segments_json_path,
)
from services.job_store import (
    Job,
    create_job,
    ensure_job_dir,
    load_job,
    save_job,
    increment_captions_version,
    mark_trim_stale,
    mark_tts_stale,
    mark_compose_stale,
)
from services.process_runner import run_cmd
from services.video_ops import (
    build_video_factory_command,
    build_video_factory_env,
)


def parse_time_value(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        result = float(value)
        return result if math.isfinite(result) else None
    raw = str(value).strip()
    if not raw:
        return None
    parts = [part.strip() for part in raw.split(":")]
    try:
        if len(parts) == 3:
            result = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            result = float(parts[0]) * 60 + float(parts[1])
        else:
            result = float(raw)
    except ValueError as exc:
        raise ValueError(f"无效的时间格式: {value}") from exc
    if not math.isfinite(result):
        raise ValueError(f"无效的时间格式: {value}")
    return result


def format_time_value(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    normalized = max(0.0, float(seconds))
    return f"{normalized:.3f}".rstrip("0").rstrip(".")


def prepare_source_video(
    job_id: str,
    start_time: str | float | int | None = None,
    end_time: str | float | int | None = None,
) -> Job:
    job = load_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    original_video = get_original_video_path(job_id)
    if not original_video.exists():
        raise FileNotFoundError("Original video not found")

    start_seconds = parse_time_value(start_time)
    end_seconds = parse_time_value(end_time)

    # 验证：要么两个都填，要么两个都不填
    has_start = start_seconds is not None
    has_end = end_seconds is not None
    if has_start != has_end:
        raise ValueError("开始时间和结束时间必须同时填写，或同时为空")

    if not has_start and not has_end:
        job.source_video = None
        job.source_start = None
        job.source_end = None
        save_job(job)
        return job

    start_seconds = max(0.0, float(start_seconds))
    end_seconds = max(0.0, float(end_seconds))
    if end_seconds <= start_seconds:
        raise ValueError("结束时间必须大于开始时间")

    job_dir = ensure_job_dir(job_id)
    source_video = get_source_video_path(job_id)
    log_file = get_process_log_path(job_id)

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-ss",
        format_time_value(start_seconds) or "0",
        "-to",
        format_time_value(end_seconds) or "0",
        "-i",
        str(original_video),
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(source_video),
    ]
    run_cmd(cmd, log_file=log_file, timeout=3600)

    job.source_video = source_video.name
    job.source_start = format_time_value(start_seconds)
    job.source_end = format_time_value(end_seconds)
    save_job(job)
    return job


def get_pipeline_input_video(job_id: str) -> Path:
    job = load_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    if job.source_video:
        source_video = ensure_job_dir(job_id) / job.source_video
        if source_video.exists():
            return source_video
    return get_original_video_path(job_id)


def process_video(
    job_id: str,
    margin: float = 3.0,
    silence_noise: str = "-35dB",
    silence_min_duration: float = 5.0,
    silence_keep: float = 1.0,
    model: str = "base",
    device: str = "cpu",
    rocm_gfx_override: Optional[str] = None,
) -> Job:
    job = load_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    job.status = "video_processing"
    save_job(job)

    job_dir = ensure_job_dir(job_id)
    original_video = get_pipeline_input_video(job_id)

    if not original_video.exists():
        raise FileNotFoundError("Original video not found")

    processed_video = get_processed_video_path(job_id)
    initial_srt = get_initial_captions_srt_path(job_id)
    initial_json = get_initial_captions_json_path(job_id)
    log_file = get_process_log_path(job_id)

    cmd = build_video_factory_command(
        original_video=original_video,
        processed_video=processed_video,
        initial_srt=initial_srt,
        margin=margin,
        silence_noise=silence_noise,
        silence_min_duration=silence_min_duration,
        silence_keep=silence_keep,
        model=model,
        device=device,
        rocm_gfx_override=rocm_gfx_override,
    )
    run_env = build_video_factory_env(rocm_gfx_override)

    try:
        run_cmd(cmd, log_file, env=run_env)

        captions = read_srt(initial_srt)
        write_json(captions, initial_json)

        job.processed_video = str(processed_video)
        job.captions_initial = str(initial_srt)
        job.captions_initial_json = str(initial_json)
        for field_name, file_name in [
            ("video_trimmed", "processed.trimmed.mp4"),
            ("captions_trimmed_json", "captions.trimmed.json"),
            ("captions_trimmed", "captions.trimmed.srt"),
            ("optimized_audio", "optimized.audio.wav"),
            ("video_audio_optimized", "video.audio.optimized.mp4"),
            ("final_subtitles_video", "final.subtitles.video.mp4"),
        ]:
            file_path = job_dir / file_name
            if file_path.exists():
                try:
                    file_path.unlink()
                except Exception:
                    pass
            setattr(job, field_name, None)
        job.status = "video_processed"
        job.process_error = None
        
        caption_store = CaptionStore(job_dir)
        if initial_srt.exists():
            caption_store.initialize_from_srt(initial_srt)
            job.captions_version = 1
        
    except Exception as e:
        job.status = "error"
        job.process_error = str(e)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"ERROR: {e}\n")
    finally:
        save_job(job)

    return job


def load_captions(job_id: str, stage: str = "initial") -> List[Caption]:
    """Load captions by stage.
    
    New model: 'source' = original ASR, 'working' = current editing
    Legacy stages: 'initial', 'edited', 'final', 'trimmed'
    """
    job = load_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")
    
    job_dir = ensure_job_dir(job_id)
    store = CaptionStore(job_dir)
    
    if stage == "source":
        source = store.get_source()
        if source is not None:
            return source
        if job.captions_initial_json:
            path = Path(job.captions_initial_json)
            if path.exists():
                return read_json(path)
        return []
    
    if stage == "working":
        working = store.get_working()
        if working is not None:
            return working
        if job.captions_edited:
            path = Path(job.captions_edited)
            if path.exists():
                return read_json(path)
        return []
    
    if stage == "trimmed":
        trimmed = store.get_trimmed()
        if trimmed is not None:
            return trimmed
        if job.captions_trimmed_json:
            path = Path(job.captions_trimmed_json)
            if path.exists():
                return read_json(path)
        return []
    
    if stage == "final":
        if store.derived_srt_path.exists():
            return read_srt(store.derived_srt_path)
        if job.captions_final:
            path = Path(job.captions_final)
            if path.exists():
                return read_srt(path)
        return []
    
    if stage == "initial":
        if job.captions_initial_json:
            path = Path(job.captions_initial_json)
            if path.exists():
                return read_json(path)
        return []
    
    if stage == "edited":
        if job.captions_edited:
            path = Path(job.captions_edited)
            if path.exists():
                return read_json(path)
        return []
    
    return []


def save_captions(job_id: str, captions: List[Caption], stage: str = "working") -> Job:
    """Save captions with version tracking.
    
    New model: saving to 'working' increments captions_version
    Legacy stages: 'edited', 'final' map to working/final
    """
    job = load_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    job_dir = ensure_job_dir(job_id)
    store = CaptionStore(job_dir)

    def _invalidate_derived() -> None:
        mark_tts_stale(job_id)
        mark_compose_stale(job_id)

        # 注意：不删除以下文件，它们是独立资源：
        # - processed.trimmed.mp4（裁剪视频）
        # - captions.trimmed.*（裁剪字幕，与裁剪视频配套）
        # - tts_segments.json（TTS 分段数据）
        derived_files = [
            "optimized.audio.wav",
            "video.audio.optimized.mp4",
            "final.subtitles.video.mp4",
            "captions.compose.ass",
        ]
        for fname in derived_files:
            fpath = job_dir / fname
            if fpath.exists():
                try:
                    fpath.unlink()
                except Exception:
                    pass

        job.tts_version = 0
        job.compose_version = 0
        job.tts_error = None
        job.compose_error = None

    if stage == "working" or stage == "edited":
        store.save_working(captions)
        job.captions_version = store.versions.captions
        job.captions_edited = str(store.working_path)
        _invalidate_derived()
        
    elif stage == "final":
        store.save_working(captions)
        store.generate_derived_srt()
        job.captions_version = store.versions.captions
        job.captions_final = str(store.derived_srt_path)
        _invalidate_derived()
        # 注意：不清空 voiceover 和 final_replace_audio，它们是独立资源
        if job.processed_video:
            job.status = "video_processed"
        else:
            job.status = "created"
    
    save_job(job)
    return job


def ensure_final_captions_srt(job_id: str) -> Path:
    """Ensure a current SRT exists for consumers that still need SRT files."""
    job = load_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    job_dir = ensure_job_dir(job_id)
    store = CaptionStore(job_dir)
    final_path = store.generate_derived_srt()

    job.captions_final = str(final_path)
    save_job(job)
    return final_path


def migrate_job_to_new_caption_model(job_id: str) -> Job:
    """Migrate a job's captions to the new source/working/derived model."""
    job = load_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")
    
    job_dir = ensure_job_dir(job_id)
    store = CaptionStore(job_dir)
    
    if not store.source_path.exists():
        if job.captions_initial_json:
            initial_path = Path(job.captions_initial_json)
            if initial_path.exists():
                captions = read_json(initial_path)
                write_json(captions, store.source_path)
    
    if not store.working_path.exists():
        if job.captions_edited:
            edited_path = Path(job.captions_edited)
            if edited_path.exists():
                captions = read_json(edited_path)
            elif job.captions_initial_json:
                captions = read_json(Path(job.captions_initial_json))
            else:
                captions = []
        else:
            captions = []
        write_json(captions, store.working_path)
    
    if not store.derived_srt_path.exists():
        if job.captions_final:
            final_path = Path(job.captions_final)
            if final_path.exists():
                captions = read_srt(final_path)
                write_srt(captions, store.derived_srt_path)
    
    job.captions_version = store.versions.captions
    save_job(job)
    return job
