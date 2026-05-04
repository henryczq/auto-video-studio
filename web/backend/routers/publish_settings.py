"""Router for publish settings and content generation."""

from fastapi import APIRouter, Depends

from routers.auth import verify_token
from routers.social_shared import run_or_400
from services.publish_settings_store import (
    load_publish_settings,
    save_publish_settings,
)
from services.publish_content_generator import generate_publish_content
from services.publish_content_generator import generate_publish_content_for_job
from services.publish_drafts import load_publish_draft, save_publish_draft

router = APIRouter(prefix="/api/publish-settings", tags=["publish-settings"])


@router.get("")
async def get_settings(_: bool = Depends(verify_token)):
    return load_publish_settings()


@router.post("")
async def save_settings(settings: dict, _: bool = Depends(verify_token)):
    return save_publish_settings(settings)


@router.post("/generate")
async def generate_content(data: dict, _: bool = Depends(verify_token)):
    """Generate title, description and tags from subtitles.
    
    Request body:
        {"srt_path": str}  # Path to final subtitles SRT file
    
    Returns:
        {"title": str, "description": str, "tags": list}
    """
    job_id = data.get("job_id")
    if job_id:
        return run_or_400(generate_publish_content_for_job, job_id)

    srt_path = data.get("srt_path")
    if not srt_path:
        raise ValueError("job_id or srt_path is required")
    return run_or_400(generate_publish_content, srt_path)


@router.get("/drafts/{job_id}")
async def get_publish_draft(job_id: str, _: bool = Depends(verify_token)):
    return load_publish_draft(job_id)


@router.post("/drafts/{job_id}")
async def save_publish_draft_api(
    job_id: str, draft: dict, _: bool = Depends(verify_token)
):
    return save_publish_draft(job_id, draft)
