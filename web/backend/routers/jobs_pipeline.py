from fastapi import APIRouter, Depends
from pydantic import BaseModel

from routers.auth import verify_token
from routers.jobs_shared import run_or_500
from services.background_jobs import start_background_job
from services.job_api import mark_job_status, prepare_process_video_kwargs, require_job
from services.video_pipeline import process_video


router = APIRouter()


class ProcessVideoRequest(BaseModel):
    margin: float = 3.0
    silence_noise: str = "-35dB"
    silence_min_duration: float = 5.0
    silence_keep: float = 1.0
    model: str = "base"
    device: str = "cpu"
    rocm_gfx_override: str | None = None


@router.post("/{job_id}/process-video")
async def start_process_video(
    job_id: str,
    req: ProcessVideoRequest,
    _: bool = Depends(verify_token),
):
    job = require_job(job_id)
    process_kwargs = prepare_process_video_kwargs(req)

    mark_job_status(job_id, "video_processing")
    start_background_job(process_video, job_id, job_id=job_id, **process_kwargs)
    return {"status": "processing", "job_id": job.id}


@router.post("/{job_id}/process")
async def start_process_video_alias(
    job_id: str,
    req: ProcessVideoRequest,
    _: bool = Depends(verify_token),
):
    return await start_process_video(job_id, req, _)
