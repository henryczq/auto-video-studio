import json
import re
import uuid
from datetime import datetime
from pathlib import Path


AI_LOG_DIR = Path(__file__).parent.parent.parent.parent / "logs" / "ai_request_logs"


def redact_headers(headers: dict) -> dict:
    safe_headers = dict(headers)
    if "Authorization" in safe_headers:
        safe_headers["Authorization"] = "Bearer ***"
    return safe_headers


def write_ai_log(log: dict) -> dict:
    AI_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_id = log.get("id") or f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    log["id"] = log_id
    log["created_at"] = log.get("created_at") or datetime.now().isoformat()
    log_path = AI_LOG_DIR / f"{log_id}.json"
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    return log


def list_ai_logs(limit: int = 100) -> list[dict]:
    if not AI_LOG_DIR.exists():
        return []
    logs = []
    for path in sorted(AI_LOG_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        logs.append(
            {
                "id": data.get("id") or path.stem,
                "created_at": data.get("created_at"),
                "type": data.get("type"),
                "status": data.get("status"),
                "model_name": data.get("model_name"),
                "model": data.get("model"),
                "url": data.get("url"),
                "duration_ms": data.get("duration_ms"),
                "error": data.get("error"),
                "response_preview": data.get("response_preview"),
            }
        )
        if len(logs) >= limit:
            break
    return logs


def load_ai_log(log_id: str) -> dict:
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", log_id)
    log_path = AI_LOG_DIR / f"{safe_id}.json"
    if not log_path.exists():
        raise FileNotFoundError("AI 日志不存在")
    return json.loads(log_path.read_text(encoding="utf-8"))
