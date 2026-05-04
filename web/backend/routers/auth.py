import os
import secrets
from typing import Optional
from fastapi import HTTPException, Header, Query

WEB_TOKEN = os.environ.get("AUTO_CUT_TOKEN", "")
ALLOWED_DOWNLOAD_FILES = {
    "original.mp4",
    "source.input.mp4",
    "processed.mp4",
    "processed.trimmed.mp4",
    "captions.initial.srt",
    "captions.initial.json",
    "captions.edited.json",
    "captions.final.srt",
    "voiceover.wav",
    "optimized.audio.wav",
    "video.audio.optimized.mp4",
    "final.subtitles.video.mp4",
    "final_replace_audio_subtitled.mp4",
    "final_subtitles_only.mp4",
    "publish_cover.jpg",
    "publish_cover_text.jpg",
    "publish_cover_uploaded.jpg",
}
ALLOWED_LOG_FILES = {
    "process",
    "tts",
    "compose",
}


def verify_token(
    x_token: Optional[str] = Header(None),
):
    """Verify API token from X-Token header only.

    Query parameter token is intentionally removed for API endpoints
    to prevent token leakage in URLs, logs, and browser history.
    """
    if not WEB_TOKEN:
        return None
    if not x_token or not secrets.compare_digest(x_token, WEB_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


def verify_download_token(
    x_token: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    """Verify token for file download endpoints.

    Downloads (video preview, images) are initiated by browser tags
    (<img>, <video>, <a>) which cannot send custom headers, so query
    token is still accepted here as a pragmatic compromise.
    Consider migrating to signed URLs in the future.
    """
    if not WEB_TOKEN:
        return None
    provided = x_token or token
    if not provided or not secrets.compare_digest(provided, WEB_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


def is_download_allowed(filename: str) -> bool:
    return filename in ALLOWED_DOWNLOAD_FILES


def is_log_allowed(logname: str) -> bool:
    return logname in ALLOWED_LOG_FILES
