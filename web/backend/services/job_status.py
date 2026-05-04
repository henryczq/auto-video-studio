"""Job status constants and utilities.

Standardized status values:
- created: Job created, no video processed yet
- processing_video: Video is being processed (ASR + cut silence)
- video_processed: Video processing complete, ready for edit
- processing_tts: TTS segments are being generated
- tts_ready: TTS segments ready
- trimming: Video is being trimmed
- trimmed: Video trimmed, ready for compose
- composing: Video/audio/subtitles are being composed
- composed: Composition complete
- error: An error occurred (check job.errors for details)

Error structure:
- errors.process: Video processing error
- errors.tts: TTS generation error
- errors.trim: Video trimming error
- errors.compose: Composition error
"""

from enum import StrEnum


class JobStatus(StrEnum):
    CREATED = "created"
    PROCESSING_VIDEO = "processing_video"
    VIDEO_PROCESSED = "video_processed"
    PROCESSING_TTS = "processing_tts"
    TTS_READY = "tts_ready"
    TRIMMING = "trimming"
    TRIMMED = "trimmed"
    COMPOSING = "composing"
    COMPOSED = "composed"
    ERROR = "error"


# Legacy status mapping
LEGACY_STATUS_MAP = {
    "processing": JobStatus.PROCESSING_VIDEO,
    "video_processing": JobStatus.PROCESSING_VIDEO,
    "video_processed": JobStatus.VIDEO_PROCESSED,
    "created": JobStatus.CREATED,
    "tts_processing": JobStatus.PROCESSING_TTS,
    "tts_completed": JobStatus.TTS_READY,
    "video_trimmed": JobStatus.TRIMMED,
    "trimming": JobStatus.TRIMMING,
    "audio_optimized": JobStatus.COMPOSING,
    "composing": JobStatus.COMPOSING,
    "video_composed": JobStatus.COMPOSED,
    "composed_replace_audio": JobStatus.COMPOSED,
    "composed_subtitles_only": JobStatus.COMPOSED,
    "error": JobStatus.ERROR,
}


def normalize_status(status: str) -> str:
    """Convert legacy status to new standardized status."""
    if not status:
        return JobStatus.CREATED
    return LEGACY_STATUS_MAP.get(status, status)


def is_processing(status: str) -> bool:
    """Check if status indicates ongoing processing."""
    processing_statuses = {
        JobStatus.PROCESSING_VIDEO,
        JobStatus.PROCESSING_TTS,
        JobStatus.TRIMMING,
        JobStatus.COMPOSING,
    }
    return status in processing_statuses


def is_completed(status: str) -> bool:
    """Check if status indicates completion (no ongoing processing)."""
    completed_statuses = {
        JobStatus.VIDEO_PROCESSED,
        JobStatus.TTS_READY,
        JobStatus.TRIMMED,
        JobStatus.COMPOSED,
    }
    return status in completed_statuses


def has_error(status: str) -> bool:
    """Check if status indicates an error condition."""
    return status == JobStatus.ERROR
