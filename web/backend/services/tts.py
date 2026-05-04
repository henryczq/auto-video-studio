import os
import sys
import threading
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from services.captions import read_srt
from services.process_runner import run_cmd
from services.job_store import get_job_dir, get_logs_dir, load_job, save_job
from services.tts_compose import compose_final_video
from services.tts_manifest import prepare_tts_work_dir, tts_manifest
from services.tts_segments import build_and_store_tts_segments, load_saved_tts_segments
from services.tts_chunking import (
    DEFAULT_SEGMENT_MAX_SECONDS,
    DEFAULT_SEGMENT_MODE,
    build_tts_chunks,
    json_to_tts_chunks,
)
from services.tts_generate import (
    DEFAULT_TTS_PARALLEL,
    DEFAULT_TTS_THREADS,
    read_tts_plan,
    synthesize_tts_chunks,
    write_tts_plan,
)
from services.tts_models import (
    COSYVOICE_DIR,
    DEFAULT_TTS_MODE,
    DEFAULT_TTS_MODEL_NAME,
    AVAILABLE_MODELS,
    get_model_dir,
    get_llm_weights_path,
    infer_model_name,
    is_cosyvoice3_model,
    prepare_model_inputs,
    resolve_project_path,
)
from services.tts_timeline import (
    DEFAULT_MAX_PAD_SECONDS,
    DEFAULT_MAX_SPEEDUP,
    DEFAULT_MIN_GAP_SILENCE,
    build_audio_timeline,
    probe_duration,
)
from services.tts_runtime import validate_zero_shot
from services.tts_profiles import resolve_runtime_profile
from services.video_pipeline import ensure_final_captions_srt

INDEXTTS2_DIR = Path(__file__).parent.parent.parent.parent / "core" / "third_party" / "index-tts"
INDEXTTS2_MODEL_DIR = INDEXTTS2_DIR / "checkpoints"
_WHISPER_MODEL_CACHE: dict[str, object] = {}
_WHISPER_CACHE_LOCK = threading.Lock()


def resolve_tts_input_paths(job_id: str) -> tuple[Path, Path, str]:
    """Return the video and subtitle files that TTS should follow."""
    job = load_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    job_dir = get_job_dir(job_id)

    if job.video_trimmed:
        video_path = job_dir / job.video_trimmed
        captions_name = job.captions_trimmed or "captions.trimmed.srt"
        captions_path = job_dir / captions_name
        if video_path.exists() and captions_path.exists():
            return video_path, captions_path, "trimmed"

    if not job.processed_video:
        raise FileNotFoundError("Processed video not found.")
    return Path(job.processed_video), ensure_final_captions_srt(job_id), "final"


def _safe_probe_duration(path: Path | None) -> float | None:
    if not path or not path.exists():
        return None
    try:
        return probe_duration(path)
    except Exception:
        return None


def get_tts_input_info(job_id: str) -> dict:
    job = load_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    video_path, captions_path, source_stage = resolve_tts_input_paths(job_id)
    captions = read_srt(captions_path) if captions_path.exists() else []
    saved_segments = load_saved_tts_segments(job_id)
    voiceover_path = Path(job.voiceover) if job.voiceover else None
    work_dir = get_job_dir(job_id) / "voice_chunks"
    chunk_files = sorted(work_dir.glob("chunk_*.raw.wav")) if work_dir.exists() else []
    total_chunks = 0
    plan_path = work_dir / "chunks.tsv"
    if plan_path.exists():
        total_chunks = len([line for line in plan_path.read_text(encoding="utf-8").splitlines() if line.strip()])

    return {
        "source_stage": source_stage,
        "source_label": "裁剪后素材" if source_stage == "trimmed" else "当前处理素材",
        "video_file": video_path.name,
        "video_path": str(video_path),
        "video_exists": video_path.exists(),
        "video_duration": _safe_probe_duration(video_path),
        "captions_file": captions_path.name,
        "captions_path": str(captions_path),
        "captions_exists": captions_path.exists(),
        "captions_count": len(captions),
        "captions_duration": max((caption.end for caption in captions), default=None),
        "tts_segments_file": Path(job.tts_segments_json).name if job.tts_segments_json else None,
        "tts_segments_source_stage": saved_segments.get("source_stage") if saved_segments else None,
        "tts_segments_mode": saved_segments.get("mode_used") if saved_segments else None,
        "chunk_cache_dir": work_dir.name,
        "chunk_cache_count": len(chunk_files),
        "chunk_plan_count": total_chunks,
        "voiceover_file": voiceover_path.name if voiceover_path else None,
        "voiceover_duration": _safe_probe_duration(voiceover_path),
    }


def generate_tts(
    job_id: str,
    prompt_wav: str,
    tts_provider: str = "cosyvoice",
    tts_runtime_env: str = "rocm6.3",
    prompt_text: str = "",
    tts_mode: str = DEFAULT_TTS_MODE,
    model_name: str = DEFAULT_TTS_MODEL_NAME,
    model_dir: str | None = None,
    segment_mode: str = DEFAULT_SEGMENT_MODE,
    speed: float = 1.0,
    max_speedup: float = DEFAULT_MAX_SPEEDUP,
    rocm_gfx_override: Optional[str] = None,
    disable_text_frontend: bool = False,
    threads: int = DEFAULT_TTS_THREADS,
    parallel: int = DEFAULT_TTS_PARALLEL,
    tts_executor: str = "workers",
    emo_text: str = "",
    emo_alpha: float = 0.6,
    reuse_chunks: bool = True,
    serial_chunk_timeout: int = 1200,
) -> str:
    job = load_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    job_dir = get_job_dir(job_id)
    log_file = get_logs_dir(job_id) / "tts.log"
    job.status = "tts_processing"
    job.tts_error = None
    job.voiceover = None
    save_job(job)

    try:
        tts_video_path, tts_captions_path, tts_source_stage = resolve_tts_input_paths(job_id)

        tts_provider = (tts_provider or "cosyvoice").strip()
        tts_mode = (tts_mode or DEFAULT_TTS_MODE).strip()
        runtime_resolved = resolve_runtime_profile(
            provider=tts_provider,
            mode=tts_mode,
            runtime_env=tts_runtime_env,
            rocm_gfx_override=rocm_gfx_override,
        )
        tts_runtime_env = runtime_resolved["runtime_env"]
        rocm_gfx_override = runtime_resolved["rocm_gfx_override"]
        runtime_profile = runtime_resolved["runtime_profile"]
        prompt_wav_path = resolve_project_path(prompt_wav)
        if not prompt_wav_path.exists():
            raise FileNotFoundError(f"Prompt wav not found: {prompt_wav_path}")

        prompt_text = (prompt_text or "").strip()
        if tts_mode == "zero_shot" and not prompt_text:
            verified = verify_prompt_audio(
                str(prompt_wav_path),
                rocm_gfx_override=rocm_gfx_override,
            )
            prompt_text = str(verified.get("transcribed_text") or "").strip()
            if not prompt_text:
                raise ValueError("zero_shot 模式未填写参考文本，且自动识别参考音频失败")

        if tts_provider == "indextts2":
            model_dir = INDEXTTS2_MODEL_DIR
            model_name = "IndexTTS2"
        else:
            model_dir = get_model_dir(model_name, model_dir)
            model_name = infer_model_name(model_dir, model_name)

        work_dir = job_dir / ("voice_chunks_indextts2" if tts_provider == "indextts2" else "voice_chunks")
        plan_path = work_dir / "chunks.tsv"
        if reuse_chunks and plan_path.exists():
            chunks = read_tts_plan(plan_path)
            segment_mode_used = "cached-plan"
        else:
            # 优先使用已保存的分段数据（按字幕 ID 对应，分段数固定）
            saved_segments = load_saved_tts_segments(job_id)
            if saved_segments and tts_source_stage == "trimmed" and saved_segments.get("source_stage") != "trimmed":
                saved_segments = None

            if saved_segments and saved_segments.get("segments"):
                tts_chunks = json_to_tts_chunks(saved_segments.get("segments") or [])
                segment_mode_used = f"saved:{saved_segments.get('mode_used') or 'manual'}"
            else:
                # 没有保存过分段，先生成并自动保存
                captions = read_srt(tts_captions_path)
                tts_chunks, segment_mode_used = build_tts_chunks(
                    captions,
                    segment_mode=segment_mode,
                )
                # 自动保存本次生成分段，方便后续单独修改某个 chunk
                build_and_store_tts_segments(
                    job_id,
                    segment_mode=segment_mode,
                    stage=tts_source_stage,
                )

            chunks = [
                {
                    "start": item.start,
                    "end": item.end,
                    "text": item.text,
                    "source_ids": item.source_ids,
                }
                for item in tts_chunks
            ]

        video_duration = probe_duration(tts_video_path)
        output_audio = job_dir / "voiceover.wav"

        manifest = tts_manifest(
            chunks,
            prompt_wav_path,
            prompt_text,
            tts_mode,
            model_dir,
            speed,
            max_speedup,
            segment_mode,
            emo_text=emo_text,
            disable_text_frontend=disable_text_frontend,
        )
        legacy_manifest = tts_manifest(
            chunks,
            prompt_wav_path,
            prompt_text,
            tts_mode,
            model_dir,
            speed,
            max_speedup,
            segment_mode,
            include_style_metadata=False,
        )
        prepare_tts_work_dir(work_dir, manifest, compatible_manifests=[legacy_manifest])
        write_tts_plan(chunks, work_dir / "chunks.tsv")

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n{'=' * 50}\n")
            f.write(f"[TTS Config]\n")
            f.write(f"  provider: {tts_provider}\n")
            f.write(f"  runtime_env: {tts_runtime_env}\n")
            f.write(f"  model: {model_name}\n")
            f.write(f"  model_dir: {model_dir.resolve()}\n")
            f.write(f"  tts_mode: {tts_mode}\n")
            f.write(f"  segment_mode: {segment_mode}\n")
            f.write(f"  segment_mode_used: {segment_mode_used}\n")
            f.write(f"  source_stage: {tts_source_stage}\n")
            f.write(f"  video_input: {tts_video_path.resolve()}\n")
            f.write(f"  captions_input: {tts_captions_path.resolve()}\n")
            f.write(f"  prompt_wav: {prompt_wav_path}\n")
            f.write(f"  prompt_text: {prompt_text[:50]}... (len={len(prompt_text)})\n")
            f.write(f"  emo_text: {emo_text[:50]}... (len={len((emo_text or '').strip())})\n")
            f.write(f"  emo_alpha: {emo_alpha}\n")
            f.write(f"  speed: {speed}\n")
            f.write(f"  max_speedup: {max_speedup}\n")
            f.write(f"  threads: {threads}\n")
            f.write(f"  tts_executor: {tts_executor}\n")
            f.write(f"  batch_size_or_workers: {parallel}\n")
            f.write(f"  reuse_chunks: {reuse_chunks}\n")
            f.write(f"  serial_chunk_timeout: {serial_chunk_timeout}s\n")
            f.write(f"  chunk_max_seconds: {DEFAULT_SEGMENT_MAX_SECONDS}\n")
            f.write(f"  min_gap_silence: {DEFAULT_MIN_GAP_SILENCE}\n")
            f.write(f"  max_pad_seconds: {DEFAULT_MAX_PAD_SECONDS}\n")
            f.write(f"  chunks: {len(chunks)}\n")
            f.write(f"\n")

        if tts_provider == "indextts2":
            if not runtime_profile:
                raise ValueError(f"Unknown IndexTTS2 runtime env: {tts_runtime_env}")
            runtime_python = Path(str(runtime_profile.get("python") or ""))
            if not runtime_python.exists():
                raise FileNotFoundError(f"IndexTTS2 runtime python not found: {runtime_python}")
            if not INDEXTTS2_MODEL_DIR.exists():
                raise FileNotFoundError(f"IndexTTS2 model dir not found: {INDEXTTS2_MODEL_DIR}")

            output_audio = job_dir / "voiceover.indextts2.wav"
            cmd = [
                str(runtime_python),
                "-u",
                str((Path(__file__).parent.parent.parent.parent / "core" / "tools" / "indextts2_voiceover.py").resolve()),
                "--video",
                str(tts_video_path.resolve()),
                "--srt",
                str(tts_captions_path.resolve()),
                "--prompt-wav",
                str(prompt_wav_path.resolve()),
                "--output-audio",
                str(output_audio.resolve()),
                "--work-dir",
                str(work_dir.resolve()),
                "--model-dir",
                str(INDEXTTS2_MODEL_DIR.resolve()),
                "--segment-mode",
                segment_mode,
                "--max-speedup",
                str(max_speedup),
                "--min-gap-silence",
                str(DEFAULT_MIN_GAP_SILENCE),
                "--max-pad-seconds",
                str(DEFAULT_MAX_PAD_SECONDS),
            ]
            if reuse_chunks:
                cmd.append("--reuse-chunks")
            if (emo_text or "").strip():
                cmd.extend(["--emo-text", emo_text.strip(), "--emo-alpha", str(emo_alpha)])
            run_env = {}
            runtime_gfx = runtime_profile.get("rocm_gfx_override")
            if runtime_gfx:
                run_env["HSA_OVERRIDE_GFX_VERSION"] = str(runtime_gfx)
            run_cmd(cmd, log_file=log_file, env=run_env or None, cwd=Path(__file__).parent.parent.parent.parent)
        else:
            if not model_dir.exists():
                raise FileNotFoundError(f"Model not found: {model_dir}")
            llm_weights_path = get_llm_weights_path(model_dir)
            if not llm_weights_path.exists():
                raise FileNotFoundError(f"LLM weights not found: {llm_weights_path}")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"  llm_weights: {llm_weights_path.resolve()}\n")
                f.write(f"  cosyvoice3: {is_cosyvoice3_model(model_dir)}\n")
            if rocm_gfx_override:
                os.environ["HSA_OVERRIDE_GFX_VERSION"] = rocm_gfx_override
            if tts_mode == "zero_shot":
                for chunk in chunks:
                    validate_zero_shot(chunk["text"], prompt_text, strict=False)

            chunk_paths, sample_rate = synthesize_tts_chunks(
                chunks=chunks,
                work_dir=work_dir,
                prompt_text=prompt_text,
                prompt_wav=prompt_wav_path,
                tts_mode=tts_mode,
                model_dir=model_dir,
                cosyvoice_dir=COSYVOICE_DIR,
                speed=speed,
                disable_text_frontend=disable_text_frontend,
                rocm_gfx_override=rocm_gfx_override,
                threads=threads,
                parallel=parallel,
                tts_executor=tts_executor,
                emo_text=emo_text,
                reuse_chunks=reuse_chunks,
                serial_chunk_timeout=serial_chunk_timeout,
                log_file=log_file,
            )
            build_audio_timeline(
                chunks=chunks,
                chunk_paths=chunk_paths,
                output_audio=output_audio,
                sample_rate=sample_rate,
                video_duration=video_duration,
                work_dir=work_dir,
                max_speedup=max_speedup,
                min_gap_silence=DEFAULT_MIN_GAP_SILENCE,
                max_pad_seconds=DEFAULT_MAX_PAD_SECONDS,
                log_file=log_file,
            )

        job.voiceover = str(output_audio)
        job.tts_version = job.captions_version
        job.status = "tts_completed"
        job.tts_error = None

    except Exception as e:
        job.status = "error"
        job.tts_error = str(e)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"ERROR: {e}\n")
        raise
    finally:
        save_job(job)

    return job.voiceover


def verify_prompt_audio(
    prompt_wav: str,
    device: Optional[str] = None,
    rocm_gfx_override: Optional[str] = None,
) -> dict:
    import torch
    import whisper

    prompt_wav_path = resolve_project_path(prompt_wav)
    if not prompt_wav_path.exists():
        raise FileNotFoundError(f"Prompt wav not found: {prompt_wav_path}")

    # 自动检测 GPU
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    with _WHISPER_CACHE_LOCK:
        model = _WHISPER_MODEL_CACHE.get(device)
        if model is None:
            model = whisper.load_model("base", device=device)
            _WHISPER_MODEL_CACHE[device] = model
    result = model.transcribe(str(prompt_wav_path), language="zh", verbose=False)

    text = result.get("text", "").strip()

    return {
        "transcribed_text": text,
        "prompt_wav": str(prompt_wav_path),
        "duration": probe_duration(prompt_wav_path),
    }
