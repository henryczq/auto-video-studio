from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi import HTTPException
from pydantic import BaseModel

from routers.auth import verify_token
from routers.jobs_shared import run_or_500
from services.background_jobs import start_background_job
from services.job_api import (
    build_prompt_verify_result,
    mark_job_status,
    prepare_compose_mode,
    prepare_tts_kwargs,
    require_job,
)
from services.tts import compose_final_video, generate_tts, get_tts_input_info
from services.video_pipeline import ensure_final_captions_srt


router = APIRouter()


def ensure_tts_job_ready(job_id: str):
    job = require_job(job_id)
    if not job.processed_video:
        raise HTTPException(status_code=400, detail="请先完成视频处理，当前任务没有 processed.mp4")
    try:
        ensure_final_captions_srt(job_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"当前任务没有可用字幕，请先在字幕编辑页保存字幕：{exc}") from exc
    return job


class GenerateTtsRequest(BaseModel):
    prompt_wav: str
    prompt_text: str = "各位朋友大家好，我是振振公子，今天我来演示一下利用"
    tts_provider: str = "cosyvoice"
    tts_runtime_env: str = "rocm6.3"
    tts_mode: str = "cross_lingual"
    segment_mode: str = "ai"
    model_name: str = "Fun-CosyVoice3-0.5B-2512_RL"
    model_dir: str | None = None
    speed: float = 1.0
    max_speedup: float = 1.18
    rocm_gfx_override: str | None = None
    disable_text_frontend: bool = False
    threads: int = 4
    parallel: int = 1
    tts_executor: str = "workers"
    emo_text: str = ""
    emo_alpha: float = 0.6
    reuse_chunks: bool = True
    serial_chunk_timeout: int = 1200


class ComposeRequest(BaseModel):
    mode: str = "replace_audio"
    audio_type: str | None = None
    playback_rate: float = 1.0


class RegenerateSingleChunkRequest(BaseModel):
    chunk_index: int  # 1-based index
    text: str
    prompt_wav: str
    prompt_text: str = ""
    tts_provider: str = "cosyvoice"
    tts_runtime_env: str = "rocm6.3"
    tts_mode: str = "cross_lingual"
    model_name: str = "Fun-CosyVoice3-0.5B-2512_RL"
    model_dir: str | None = None
    speed: float = 1.0
    max_speedup: float = 1.18
    rocm_gfx_override: str | None = None
    disable_text_frontend: bool = False
    threads: int = 4
    emo_text: str = ""
    emo_alpha: float = 0.6


class VerifyPromptRequest(BaseModel):
    prompt_wav: str
    prompt_text: str = ""
    device: str = "cpu"


@router.post("/{job_id}/generate-tts")
async def generate_tts_api(
    job_id: str,
    req: GenerateTtsRequest,
    _: bool = Depends(verify_token),
):
    ensure_tts_job_ready(job_id)
    tts_kwargs = prepare_tts_kwargs(req)

    require_job(job_id)
    mark_job_status(job_id, "tts_processing")
    start_background_job(
        generate_tts,
        job_id,
        job_id=job_id,
        prompt_wav=req.prompt_wav,
        **tts_kwargs,
    )
    return {"status": "processing", "job_id": job_id}


@router.post("/{job_id}/tts")
async def generate_tts_api_alias(
    job_id: str,
    req: GenerateTtsRequest,
    _: bool = Depends(verify_token),
):
    return await generate_tts_api(job_id, req, _)


@router.get("/{job_id}/tts/inputs")
async def get_tts_inputs_api(job_id: str, _: bool = Depends(verify_token)):
    require_job(job_id)
    try:
        return get_tts_input_info(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{job_id}/compose")
async def compose_video_api(
    job_id: str,
    req: ComposeRequest,
    _: bool = Depends(verify_token),
):
    mode = prepare_compose_mode(req)
    if req.audio_type == "replace":
        mode = "replace_audio"

    require_job(job_id)
    mark_job_status(job_id, "composing")
    start_background_job(compose_final_video, job_id, mode, req.playback_rate)
    return {"status": "processing", "job_id": job_id}


@router.post("/verify-prompt")
async def verify_prompt_audio(
    req: VerifyPromptRequest,
    _: bool = Depends(verify_token),
):
    from services.tts import verify_prompt_audio as verify_prompt_audio_impl

    result = run_or_500(verify_prompt_audio_impl, req.prompt_wav, req.device)
    return build_prompt_verify_result(result, req.prompt_text)


@router.post("/{job_id}/tts/chunks/{chunk_index}/regenerate")
async def regenerate_single_chunk(
    job_id: str,
    chunk_index: int,
    req: RegenerateSingleChunkRequest,
    _: bool = Depends(verify_token),
):
    """Regenerate TTS for a single chunk only."""
    from services.tts_models import get_model_dir, infer_model_name, resolve_project_path
    from services.tts_generate import _chunk_output_path, _synthesize_single_chunk
    from services.tts_segments import load_saved_tts_segments
    from services.job_store import get_job_dir

    job = require_job(job_id)
    work_dir = get_job_dir(job_id) / "voice_chunks"
    work_dir.mkdir(parents=True, exist_ok=True)

    # 尝试用保存的分段数据找到对应的 chunk（更准确）
    saved_segments = load_saved_tts_segments(job_id)
    segment_info = None
    if saved_segments and saved_segments.get("segments"):
        segments = saved_segments.get("segments")
        if 0 < chunk_index <= len(segments):
            segment_info = segments[chunk_index - 1]
            # 更新分段中的文本为请求中的新文本
            segment_info = {**segment_info, "text": req.text}
            # 保存更新后的分段
            from services.tts_segments import save_tts_segments
            save_tts_segments(job_id, segments, requested_mode=saved_segments.get("requested_mode", "manual"),
                            mode_used=saved_segments.get("mode_used", "manual"), source_stage=saved_segments.get("source_stage", "working"))

    # 如果没有保存过分段，使用传入的文本
    if not segment_info:
        segment_info = {
            "start": 0.0,
            "end": 0.0,
            "source_ids": [],
            "text": req.text,
        }

    chunk_path = _chunk_output_path(work_dir, chunk_index)

    prompt_wav_path = resolve_project_path(req.prompt_wav)
    if not prompt_wav_path.exists():
        raise HTTPException(status_code=400, detail=f"Prompt wav not found: {prompt_wav_path}")

    prompt_text = (req.prompt_text or "").strip()
    if req.tts_mode == "zero_shot" and not prompt_text:
        from services.tts import verify_prompt_audio as verify_prompt_audio_impl
        verified = verify_prompt_audio_impl(str(prompt_wav_path))
        prompt_text = str(verified.get("transcribed_text") or "").strip()
        if not prompt_text:
            raise HTTPException(status_code=400, detail="zero_shot 模式需要填写参考文本")

    model_dir = get_model_dir(req.model_name, req.model_dir)
    model_dir = infer_model_name(model_dir, req.model_name)

    chunk = {
        "start": float(segment_info.get("start", 0)),
        "end": float(segment_info.get("end", 0)),
        "source_ids": [int(x) for x in (segment_info.get("source_ids") or [])],
        "text": req.text,
    }

    idx, output_path, sample_rate = _synthesize_single_chunk(
        idx=chunk_index,
        chunk=chunk,
        output_path=str(chunk_path),
        model_dir=str(model_dir),
        prompt_text=prompt_text,
        prompt_wav=str(prompt_wav_path),
        speed=req.speed,
        disable_text_frontend=req.disable_text_frontend,
        tts_mode=req.tts_mode,
        emo_text=req.emo_text,
        cosyvoice_dir=str(Path(__file__).parent.parent.parent.parent / "core" / "third_party" / "CosyVoice"),
        rocm_gfx_override=req.rocm_gfx_override,
        threads=req.threads,
    )

    return {
        "status": "success",
        "job_id": job_id,
        "chunk_index": chunk_index,
        "chunk_path": str(chunk_path),
        "sample_rate": sample_rate,
    }
