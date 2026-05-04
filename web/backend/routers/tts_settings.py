from fastapi import APIRouter, Depends, HTTPException

from routers.auth import verify_token
from services.tts_profiles import (
    DEFAULT_TTS_PROFILES,
    load_tts_profiles,
    save_tts_profiles,
    validate_tts_profiles,
)


router = APIRouter(prefix="/api/tts-settings", tags=["tts-settings"])


@router.get("")
async def get_tts_settings(_: bool = Depends(verify_token)):
    return load_tts_profiles()


@router.put("")
async def update_tts_settings(payload: dict, _: bool = Depends(verify_token)):
    return save_tts_profiles(payload)


@router.post("/validate")
async def validate_tts_settings(payload: dict, _: bool = Depends(verify_token)):
    try:
        return {"valid": True, "config": validate_tts_profiles(payload)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reset")
async def reset_tts_settings(_: bool = Depends(verify_token)):
    return save_tts_profiles(DEFAULT_TTS_PROFILES)
