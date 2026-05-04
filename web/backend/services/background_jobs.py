import logging
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

MAX_WORKERS = int(__import__("os").environ.get("AUTO_VIDEO_MAX_BACKGROUND_WORKERS", "4"))
_executor = ThreadPoolExecutor(
    max_workers=MAX_WORKERS,
    thread_name_prefix="auto-video-bg",
    initializer=None,
)


class JobState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BackgroundJob:
    job_id: str
    task_id: str
    state: JobState = JobState.PENDING
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None


_active_jobs: dict[str, BackgroundJob] = {}
_active_jobs_lock = threading.Lock()
_futures: dict[str, Future] = {}


def is_background_job_active(job_id: str) -> bool:
    with _active_jobs_lock:
        return job_id in _active_jobs


def get_active_jobs() -> list[str]:
    with _active_jobs_lock:
        return sorted(_active_jobs.keys())


def get_job_info(job_id: str) -> Optional[dict]:
    with _active_jobs_lock:
        job = _active_jobs.get(job_id)
        if not job:
            return None
        return {
            "job_id": job.job_id,
            "task_id": job.task_id,
            "state": job.state.value,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "error": job.error,
        }


def get_all_jobs_info() -> list[dict]:
    with _active_jobs_lock:
        return [
            {
                "job_id": job.job_id,
                "task_id": job.task_id,
                "state": job.state.value,
                "created_at": job.created_at,
                "started_at": job.started_at,
                "completed_at": job.completed_at,
            }
            for job in _active_jobs.values()
        ]


def start_background_job(
    target: Callable[..., Any],
    *args: Any,
    job_id: Optional[str] = None,
    **kwargs: Any,
) -> tuple[str, Future]:
    if job_id is None:
        job_id = str(uuid.uuid4())[:8]

    task_id = str(uuid.uuid4())
    bg_job = BackgroundJob(job_id=job_id, task_id=task_id, state=JobState.PENDING)

    def run_target() -> None:
        with _active_jobs_lock:
            bg_job.state = JobState.RUNNING
            bg_job.started_at = datetime.now().isoformat()

        try:
            target(*args, **kwargs)
            with _active_jobs_lock:
                bg_job.state = JobState.COMPLETED
                bg_job.completed_at = datetime.now().isoformat()
        except Exception as e:
            with _active_jobs_lock:
                bg_job.state = JobState.FAILED
                bg_job.error = str(e)
                bg_job.completed_at = datetime.now().isoformat()
            logger.exception("Background job %s failed", job_id)
            raise
        finally:
            with _active_jobs_lock:
                _active_jobs.pop(job_id, None)
                _futures.pop(job_id, None)

    with _active_jobs_lock:
        _active_jobs[job_id] = bg_job

    future = _executor.submit(run_target)
    with _active_jobs_lock:
        _futures[job_id] = future

    return job_id, future


def cancel_background_job(job_id: str, timeout: float = 5.0) -> bool:
    with _active_jobs_lock:
        future = _futures.get(job_id)
        if not future:
            return False

    cancelled = future.cancel()
    if cancelled:
        with _active_jobs_lock:
            if job_id in _active_jobs:
                _active_jobs[job_id].state = JobState.CANCELLED
                _active_jobs[job_id].completed_at = datetime.now().isoformat()
            _active_jobs.pop(job_id, None)
            _futures.pop(job_id, None)
        logger.info("Background job %s cancelled", job_id)
    return cancelled


def wait_for_job(job_id: str, timeout: Optional[float] = None) -> Optional[Any]:
    with _active_jobs_lock:
        future = _futures.get(job_id)
        if not future:
            return None

    try:
        return future.result(timeout=timeout)
    except TimeoutError:
        return None
    except Exception as e:
        logger.exception("Background job %s raised exception", job_id)
        raise
