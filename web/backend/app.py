import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader

# Maximum request body size in bytes (default 500 MB)
MAX_REQUEST_BODY_SIZE = int(os.environ.get("AUTO_CUT_MAX_BODY_SIZE", "524288000"))

from routers import jobs, terms, config, social, ai, publish_settings, tts_settings
from services.db import init_db, run_migrations
from services.data_migration import run_all_migrations
from services.background_jobs import get_active_jobs

# Configure root logger for structured output
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
STATUS_DETAIL_TTL_SECONDS = 5
_status_detail_cache_lock = threading.Lock()
_status_detail_cache: dict = {"expires_at": 0.0, "payload": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    JOBS_DIR = Path(__file__).parent.parent.parent.parent / "videos" / "web_jobs"
    JOBS_DIR.mkdir(parents=True, exist_ok=True)

    init_db()
    run_migrations()
    run_all_migrations()

    yield


app = FastAPI(title="视频裁剪与配音工作台", lifespan=lifespan)

# Security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    # Strict CSP for production; adjust as needed for inline scripts
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "font-src 'self'; "
        "media-src 'self' blob:;"
    )
    response.headers["Content-Security-Policy"] = csp
    return response


STATIC_DIR = Path(__file__).parent.parent / "frontend" / "static"
TEMPLATES_DIR = Path(__file__).parent.parent / "frontend" / "templates"
STATIC_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)

jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
STATIC_VERSION = str(int(time.time()))

app.include_router(jobs.router)
app.include_router(terms.router)
app.include_router(config.router)
app.include_router(social.router)
app.include_router(ai.router)
app.include_router(publish_settings.router)
app.include_router(tts_settings.router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all exception handler to prevent leaking stack traces in production."""
    logger.error(
        "Unhandled exception for %s %s: %s",
        request.method,
        request.url.path,
        exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.get("/")
async def root():
    template = jinja_env.get_template("index.html")
    return HTMLResponse(template.render(static_version=str(int(time.time()))))


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/api/status")
async def get_status():
    """Get system status with full backward-compatible fields.

    Returns all fields including gpu, process_count, active_jobs for compatibility.
    For heavy operations (GPU info, pgrep), results are served from a short TTL cache.
    """
    now = time.time()
    with _status_detail_cache_lock:
        if _status_detail_cache["payload"] and _status_detail_cache["expires_at"] > now:
            cached = _status_detail_cache["payload"]
            return {
                "status": cached.get("status", "running"),
                "active_jobs_count": len(cached.get("active_jobs", [])),
                "gpu": cached.get("gpu", {"available": False}),
                "process_count": cached.get("process_count", 0),
                "active_jobs": cached.get("active_jobs", []),
                "health": "/health",
                "ready": "/health/ready",
                "detail": "/api/status/detail",
            }

    payload = _build_status_detail()
    with _status_detail_cache_lock:
        _status_detail_cache["payload"] = payload
        _status_detail_cache["expires_at"] = now + STATUS_DETAIL_TTL_SECONDS

    return {
        "status": payload.get("status", "running"),
        "active_jobs_count": len(payload.get("active_jobs", [])),
        "gpu": payload.get("gpu", {"available": False}),
        "process_count": payload.get("process_count", 0),
        "active_jobs": payload.get("active_jobs", []),
        "health": "/health",
        "ready": "/health/ready",
        "detail": "/api/status/detail",
    }


def _build_status_detail() -> dict:
    import torch

    gpu_info = {"available": False}
    if torch.cuda.is_available():
        gpu_info = {
            "available": True,
            "device_name": torch.cuda.get_device_name(0),
            "memory_allocated_gb": torch.cuda.memory_allocated(0) / (1024**3),
            "memory_reserved_gb": torch.cuda.memory_reserved(0) / (1024**3),
            "memory_total_gb": torch.cuda.get_device_properties(0).total_memory / (1024**3),
        }

    try:
        result = subprocess.run(
            ["pgrep", "-f", "uvicorn|cosyvoice|whisper"],
            capture_output=True,
            text=True,
            check=False,
        )
        process_count = len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0
    except Exception:
        process_count = 0

    return {
        "status": "running",
        "gpu": gpu_info,
        "process_count": process_count,
        "active_jobs": get_active_jobs(),
        "cached_ttl_seconds": STATUS_DETAIL_TTL_SECONDS,
    }


@app.get("/api/status/detail")
async def get_status_detail():
    now = time.time()
    with _status_detail_cache_lock:
        if _status_detail_cache["payload"] and _status_detail_cache["expires_at"] > now:
            return {**_status_detail_cache["payload"], "cache_hit": True}

    payload = _build_status_detail()
    with _status_detail_cache_lock:
        _status_detail_cache["payload"] = payload
        _status_detail_cache["expires_at"] = now + STATUS_DETAIL_TTL_SECONDS
    return {**payload, "cache_hit": False}


@app.get("/health/ready")
async def readiness_check():
    try:
        db_path = Path(__file__).parent.parent.parent.parent / "data" / "app.db"
        if not db_path.parent.exists():
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "reason": "data directory missing"},
            )
        jobs_dir = Path(__file__).parent.parent.parent.parent / "videos" / "web_jobs"
        if not jobs_dir.exists():
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "reason": "jobs directory missing"},
            )
        return {"status": "ready"}
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "reason": str(exc)},
        )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("AUTO_CUT_HOST", "127.0.0.1")
    port = int(os.environ.get("AUTO_CUT_PORT", "8000"))

    uvicorn.run(app, host=host, port=port)
