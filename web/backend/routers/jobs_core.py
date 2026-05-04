import json
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from routers.auth import (
    is_download_allowed,
    is_log_allowed,
    verify_download_token,
    verify_token,
)
from services.job_api import require_job
from services.job_store import (
    delete_job as delete_job_record,
    get_job_dir,
    get_logs_dir,
    update_job_fields,
)


router = APIRouter()


@router.get("/{job_id}")
async def get_job(job_id: str, _: bool = Depends(verify_token)):
    return require_job(job_id)


@router.patch("/{job_id}")
async def update_job(job_id: str, updates: dict, _: bool = Depends(verify_token)):
    require_job(job_id)
    allowed = {}
    if "name" in updates:
        allowed["name"] = (updates.get("name") or "").strip() or None
    if not allowed:
        return require_job(job_id)
    updated = update_job_fields(job_id, **allowed)
    if not updated:
        raise HTTPException(status_code=404, detail="Job not found")
    return updated


@router.delete("/{job_id}")
async def delete_job(
    job_id: str, delete_files: bool = False, _: bool = Depends(verify_token)
):
    require_job(job_id)
    job_dir = get_job_dir(job_id)

    if delete_files:
        if job_dir.exists():
            shutil.rmtree(job_dir)
        delete_job_record(job_id)
        return {"status": "deleted", "job_id": job_id, "files_deleted": True}

    delete_job_record(job_id)
    return {"status": "deleted", "job_id": job_id, "files_deleted": False}


def _resolve_job_file(job_dir: Path, filename: str) -> Path:
    """Safely resolve a filename within the job directory.

    Prevents path traversal by rejecting any path components that
    would escape the job directory.
    """
    base = job_dir.resolve()
    target = (base / filename).resolve()
    if base not in target.parents and target != base:
        raise HTTPException(status_code=403, detail="Invalid file path")
    return target


@router.get("/{job_id}/download/{filename}")
async def download_file(job_id: str, filename: str, _: bool = Depends(verify_download_token)):
    if not is_download_allowed(filename):
        raise HTTPException(status_code=403, detail="Download not allowed")

    job_dir = get_job_dir(job_id)
    file_path = _resolve_job_file(job_dir, filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    from fastapi.responses import FileResponse

    return FileResponse(file_path)


@router.get("/{job_id}/logs/{logname}")
async def get_log(job_id: str, logname: str, _: bool = Depends(verify_token)):
    if not is_log_allowed(logname):
        raise HTTPException(status_code=403, detail="Log not allowed")

    log_dir = get_logs_dir(job_id)
    log_file = _resolve_job_file(log_dir, f"{logname}.log")
    if not log_file.exists():
        return {"content": ""}
    return {"content": log_file.read_text(encoding="utf-8")}


@router.get("/{job_id}/publish-data")
async def get_publish_data(job_id: str, _: bool = Depends(verify_token)):
    """获取任务的发布数据"""
    require_job(job_id)
    job_dir = get_job_dir(job_id)
    publish_data_file = job_dir / "publish_data.json"

    if not publish_data_file.exists():
        return {}

    try:
        with open(publish_data_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


@router.put("/{job_id}/publish-data")
async def save_publish_data(job_id: str, data: dict, _: bool = Depends(verify_token)):
    """保存任务的发布数据"""
    require_job(job_id)
    job_dir = get_job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    publish_data_file = job_dir / "publish_data.json"

    try:
        with open(publish_data_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return {"status": "saved", "job_id": job_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存失败: {str(e)}")
