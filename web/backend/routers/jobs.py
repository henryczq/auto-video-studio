import os
import shutil
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from routers import (
    jobs_captions,
    jobs_core,
    jobs_pipeline,
    jobs_tts,
    jobs_trim,
    jobs_trim_compose,
)
from routers.auth import verify_token
from services.job_api import list_jobs_sorted
from services.job_paths import get_original_video_path, get_process_log_path
from services.job_store import ensure_job_dir, update_job_fields
from services.upload_normalize import normalize_uploaded_video, upload_temp_path
from services.video_pipeline import create_job, prepare_source_video

# Maximum uploaded video size in bytes (default 2 GB)
MAX_VIDEO_SIZE = int(os.environ.get("AUTO_CUT_MAX_VIDEO_SIZE", "2147483648"))
UPLOAD_CHUNK_SIZE = 1024 * 1024


router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
async def list_jobs(limit: int = 50, offset: int = 0):
    return list_jobs_sorted(limit=limit, offset=offset)


@router.post("")
async def create_new_job(
    video: UploadFile,
    name: Optional[str] = Form(None),
    clip_start: Optional[str] = Form(None),
    clip_end: Optional[str] = Form(None),
    _: bool = Depends(verify_token),
):
    if video.size and video.size > MAX_VIDEO_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Video too large ({video.size} bytes). Maximum allowed: {MAX_VIDEO_SIZE} bytes",
        )

    job = create_job(video.filename or "video.mp4", name=(name or "").strip() or None)
    job_dir = ensure_job_dir(job.id)
    original = get_original_video_path(job.id)
    upload_input = upload_temp_path(job_dir, video.filename)
    log_file = get_process_log_path(job.id)

    await run_in_threadpool(_save_upload_file, video, upload_input)
    try:
        await run_in_threadpool(
            normalize_uploaded_video,
            upload_input,
            original,
            log_file,
        )
    except ValueError as exc:
        update_job_fields(job.id, status="error", process_error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if upload_input.exists() and upload_input != original:
            upload_input.unlink(missing_ok=True)

    clip_start = (clip_start or "").strip() or None
    clip_end = (clip_end or "").strip() or None
    if clip_start or clip_end:
        try:
            job = prepare_source_video(job.id, clip_start, clip_end)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "job_id": job.id,
        "status": job.status,
        "source_video": job.source_video,
        "source_start": job.source_start,
        "source_end": job.source_end,
    }


def _save_upload_file(video: UploadFile, target_path) -> None:
    with open(target_path, "wb") as f:
        shutil.copyfileobj(video.file, f, length=UPLOAD_CHUNK_SIZE)


router.include_router(jobs_core.router)
router.include_router(jobs_pipeline.router)
router.include_router(jobs_captions.router)
router.include_router(jobs_tts.router)
router.include_router(jobs_trim.router)
router.include_router(jobs_trim_compose.router)
