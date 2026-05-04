from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from routers.auth import verify_token
from routers.jobs_shared import run_or_500
from services.captions import apply_terms, captions_to_json, json_to_captions
from services.suggestions import generate_suggestions, load_terms
from services.tts_segments import (
    build_and_store_tts_segments,
    load_saved_tts_segments,
    save_tts_segments,
)
from services.video_pipeline import load_captions, save_captions
from services.voiceover_suggestions import generate_voiceover_suggestions


router = APIRouter()


class CaptionsSaveRequest(BaseModel):
    captions: list[dict[str, Any]]


class ApplyTermsRequest(BaseModel):
    stage: str = "working"


class SuggestionsRequest(BaseModel):
    terms: dict[str, str] | None = None


class VoiceoverSuggestionsRequest(BaseModel):
    stage: str = "working"


class GenerateTtsSegmentsRequest(BaseModel):
    segment_mode: str = "ai"
    stage: str = "auto"


class TtsSegmentsSaveRequest(BaseModel):
    segments: list[dict[str, Any]]
    requested_mode: str = "manual"
    mode_used: str = "manual"
    source_stage: str = "working"


@router.get("/{job_id}/captions")
async def get_captions(
    job_id: str, stage: str = "working", _: bool = Depends(verify_token)
):
    captions = run_or_500(load_captions, job_id, stage)
    return captions_to_json(captions)


@router.post("/{job_id}/captions")
async def save_captions_api(
    job_id: str,
    req: CaptionsSaveRequest,
    stage: str = "working",
    _: bool = Depends(verify_token),
):
    captions = json_to_captions(req.captions)
    job = run_or_500(save_captions, job_id, captions, stage)

    # 保存字幕后，自动重新生成 TTS 分段数据（使用 rule 模式，快速生成分段）
    from services.tts_segments import build_and_store_tts_segments
    try:
        build_and_store_tts_segments(job_id, segment_mode="rule", stage=stage)
    except Exception:
        pass  # 忽略分段生成失败，不影响字幕保存

    return {"status": "saved", "job_id": job.id, "stage": stage}


@router.post("/{job_id}/captions/final")
async def save_captions_final(
    job_id: str, req: CaptionsSaveRequest, _: bool = Depends(verify_token)
):
    captions = json_to_captions(req.captions)
    job = run_or_500(save_captions, job_id, captions, "final")

    # 保存字幕后，自动重新生成 TTS 分段数据（使用 rule 模式，快速生成分段）
    from services.tts_segments import build_and_store_tts_segments
    try:
        build_and_store_tts_segments(job_id, segment_mode="rule", stage="final")
    except Exception:
        pass

    return {"status": "saved", "job_id": job.id, "stage": "final"}


@router.post("/{job_id}/apply-terms")
async def apply_terms_api(
    job_id: str, req: ApplyTermsRequest | None = None, _: bool = Depends(verify_token)
):
    requested_stage = req.stage if req else "working"
    stage = requested_stage if requested_stage in ["source", "working", "final", "trimmed"] else "working"
    captions = run_or_500(load_captions, job_id, stage)
    if not captions:
        captions = run_or_500(load_captions, job_id, "source")
    terms = load_terms()
    new_captions = apply_terms(captions, terms)
    run_or_500(save_captions, job_id, new_captions, "working")
    return {"status": "applied", "applied": len(terms), "count": len(new_captions)}


@router.get("/{job_id}/suggestions")
async def get_suggestions_api(job_id: str, _: bool = Depends(verify_token)):
    captions = run_or_500(load_captions, job_id, "working")
    if not captions:
        captions = run_or_500(load_captions, job_id, "source")
    return run_or_500(generate_suggestions, captions, load_terms())


@router.post("/{job_id}/suggestions")
async def post_suggestions_api(
    job_id: str, _: SuggestionsRequest, __: bool = Depends(verify_token)
):
    captions = run_or_500(load_captions, job_id, "working")
    if not captions:
        captions = run_or_500(load_captions, job_id, "source")
    return run_or_500(generate_suggestions, captions, load_terms())


@router.post("/{job_id}/voiceover-suggestions")
async def generate_voiceover_suggestions_api(
    job_id: str,
    req: VoiceoverSuggestionsRequest,
    _: bool = Depends(verify_token),
):
    stage = req.stage if req.stage in ["working", "final", "source", "trimmed"] else "working"
    captions = run_or_500(load_captions, job_id, stage)
    if not captions and stage != "source":
        captions = run_or_500(load_captions, job_id, "source")
    return {
        "stage": stage,
        "items": run_or_500(generate_voiceover_suggestions, captions),
    }


@router.get("/{job_id}/tts-segments")
async def get_tts_segments(job_id: str, _: bool = Depends(verify_token)):
    payload = run_or_500(load_saved_tts_segments, job_id)
    return payload or {"segments": []}


@router.post("/{job_id}/tts-segments/generate")
async def generate_tts_segments_api(
    job_id: str,
    req: GenerateTtsSegmentsRequest,
    _: bool = Depends(verify_token),
):
    return run_or_500(
        build_and_store_tts_segments,
        job_id,
        segment_mode=req.segment_mode,
        stage=req.stage,
    )


@router.post("/{job_id}/tts-segments")
async def save_tts_segments_api(
    job_id: str,
    req: TtsSegmentsSaveRequest,
    _: bool = Depends(verify_token),
):
    return run_or_500(
        save_tts_segments,
        job_id,
        req.segments,
        requested_mode=req.requested_mode,
        mode_used=req.mode_used,
        source_stage=req.source_stage,
    )
