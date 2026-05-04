from fastapi import APIRouter, Depends
from pydantic import BaseModel

from routers.auth import verify_token
from routers.jobs_shared import run_or_500
from services import compose_service, trim_service


router = APIRouter()


class AudioOptimizeRequest(BaseModel):
    preset: str = "voice_light"
    denoise: bool = True
    loudnorm: bool = True
    compressor: bool = True


class ComposeVideoRequest(BaseModel):
    audio_mode: str = "original"
    playback_rate: float = 1.0


@router.post("/{job_id}/trim/preview")
async def trim_preview(job_id: str, _: bool = Depends(verify_token)):
    return run_or_500(trim_service.preview_trim, job_id)


@router.post("/{job_id}/trim/render")
async def trim_render(job_id: str, _: bool = Depends(verify_token)):
    return run_or_500(trim_service.execute_trim, job_id)


@router.get("/{job_id}/trim/result")
async def trim_result(job_id: str, _: bool = Depends(verify_token)):
    return run_or_500(trim_service.get_trim_result, job_id)


@router.post("/{job_id}/compose/video")
async def compose_video(
    job_id: str,
    req: ComposeVideoRequest | None = None,
    _: bool = Depends(verify_token),
):
    audio_mode = req.audio_mode if req else "original"
    playback_rate = req.playback_rate if req else 1.0
    return run_or_500(compose_service.compose_original_video, job_id, audio_mode, playback_rate)


@router.post("/{job_id}/compose/audio-optimize")
async def compose_audio_optimize(
    job_id: str,
    req: AudioOptimizeRequest,
    _: bool = Depends(verify_token),
):
    options = compose_service.AudioOptimizeOptions(
        preset=req.preset,
        denoise=req.denoise,
        loudnorm=req.loudnorm,
        compressor=req.compressor,
    )
    return run_or_500(compose_service.optimize_audio, job_id, options)


@router.get("/{job_id}/compose/result")
async def compose_result(job_id: str, _: bool = Depends(verify_token)):
    return run_or_500(compose_service.get_compose_result, job_id)
