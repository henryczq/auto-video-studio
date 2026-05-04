"""Per-job drafts for social publishing fields."""

import json
import os
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).parent.parent.parent.parent
DRAFTS_FILE = ROOT_DIR / "data" / "publish_drafts.json"


def _ensure_config_dir() -> None:
    DRAFTS_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_all_drafts(*, strict: bool = False) -> dict[str, dict[str, Any]]:
    _ensure_config_dir()
    if not DRAFTS_FILE.exists():
        return {}
    try:
        data = json.loads(DRAFTS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        if strict:
            raise ValueError(f"发布内容草稿文件读取失败: {exc}") from exc
        return {}


def load_publish_draft(job_id: str) -> dict[str, Any]:
    return load_all_drafts().get(job_id, {})


def save_publish_draft(job_id: str, draft: dict[str, Any]) -> dict[str, Any]:
    _ensure_config_dir()
    drafts = load_all_drafts(strict=True)
    allowed_keys = {
        "video_type",
        "account_id",
        "account_ids",
        "platform",
        "title",
        "desc",
        "tags",
        "thumbnail",
        "thumbnail_text",
        "thumbnail_time",
        "thumbnail_font_size",
        "thumbnail_font_color",
        "mode",
        "schedule",
        "tid",
    }
    normalized = dict(draft)
    if "desc" not in normalized and "description" in normalized:
        normalized["desc"] = normalized.get("description", "")
    cleaned = {key: normalized.get(key, "") for key in allowed_keys}
    drafts[job_id] = cleaned
    tmp_path = DRAFTS_FILE.with_suffix(f"{DRAFTS_FILE.suffix}.tmp")
    tmp_path.write_text(json.dumps(drafts, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, DRAFTS_FILE)
    return cleaned
