import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from routers.auth import verify_token
from routers.jobs_shared import run_or_500
from services.caption_store import CaptionStore
from services.job_store import get_job_dir, load_job, save_job, mark_tts_stale


router = APIRouter()


class ManualCutSegment(BaseModel):
    start: float
    end: float
    type: str | None = None


class CutMarksSaveRequest(BaseModel):
    cut_indices: list[int]
    manual_segments: list[ManualCutSegment] = Field(default_factory=list)


def get_cut_marks_file(job_id: str) -> Path:
    job_dir = get_job_dir(job_id)
    return job_dir / "captions.cut_marks.json"


def load_cut_marks(job_id: str) -> dict[str, Any]:
    job_dir = get_job_dir(job_id)
    store = CaptionStore(job_dir)
    
    cut_marks = store.get_cut_marks()
    return {
        "cut_indices": [m["index"] for m in cut_marks if "index" in m],
        "manual_segments": [m for m in cut_marks if "start" in m and "end" in m],
        "version": 1,
    }


def save_cut_marks(
    job_id: str,
    cut_indices: list[int],
    manual_segments: list[ManualCutSegment | dict[str, Any]] | None = None,
) -> dict[str, Any]:
    job_dir = get_job_dir(job_id)
    store = CaptionStore(job_dir)
    
    cut_marks = []
    normalized_manual_segments = []
    for idx in sorted(set(cut_indices)):
        cut_marks.append({"index": idx, "type": "caption"})
    for segment in manual_segments or []:
        segment_data = (
            segment.model_dump()
            if isinstance(segment, BaseModel)
            else segment
        )
        start = float(segment_data.get("start", 0))
        end = float(segment_data.get("end", 0))
        if end > start:
            normalized_segment = {"start": start, "end": end, "type": "manual"}
            cut_marks.append(normalized_segment)
            normalized_manual_segments.append(normalized_segment)
    
    store.save_cut_marks(cut_marks)
    
    return {
        "cut_indices": sorted(set(cut_indices)),
        "manual_segments": normalized_manual_segments,
        "version": 1,
    }


def invalidate_tts_after_trim(job_id: str) -> None:
    job_dir = get_job_dir(job_id)
    
    for field, filename in [
        ("tts_segments_json", "tts_segments.json"),
        ("voiceover", None),
        ("final_replace_audio", None),
        ("final_subtitles_only", None),
    ]:
        job = load_job(job_id)
        if not job:
            return
        old_path = getattr(job, field, None)
        if old_path:
            file_path = job_dir / old_path if filename else None
            if file_path and file_path.exists():
                file_path.unlink()
        setattr(job, field, None)
    
    job = load_job(job_id)
    if job:
        job.tts_segments_json = None
        job.voiceover = None
        job.final_replace_audio = None
        job.final_subtitles_only = None
        save_job(job)
    
    mark_tts_stale(job_id)


@router.get("/{job_id}/captions/cut-marks")
async def get_cut_marks(job_id: str, _: bool = Depends(verify_token)):
    return run_or_500(load_cut_marks, job_id)


@router.post("/{job_id}/captions/cut-marks")
async def save_cut_marks_api(
    job_id: str,
    req: CutMarksSaveRequest,
    _: bool = Depends(verify_token),
):
    result = run_or_500(save_cut_marks, job_id, req.cut_indices, req.manual_segments)
    return {"status": "saved", **result}


@router.delete("/{job_id}/captions/cut-marks")
async def clear_cut_marks(job_id: str, _: bool = Depends(verify_token)):
    run_or_500(save_cut_marks, job_id, [], [])
    return {"status": "cleared"}
