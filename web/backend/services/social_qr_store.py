import datetime
import json
import queue
import tempfile
import threading
from pathlib import Path
from typing import Dict

from services.social_common import get_sau_cookie_path, is_account_cookie_valid
from services.social_config import PLATFORMS, get_sau_root


QR_LOGIN_SESSIONS_FILE = (
    Path(tempfile.gettempdir()) / "auto-video-studio" / "social_qr_login_sessions.json"
)
RECOVERABLE_QR_COOKIE_MAX_AGE_HOURS = 6
PERSISTED_QR_SESSION_MAX_AGE_HOURS = 24

_active_qr_login_sessions: Dict[str, queue.Queue] = {}
_qr_login_session_meta: Dict[str, dict] = {}
_qr_login_lock = threading.Lock()


def get_qr_login_queue(session_id: str):
    return _active_qr_login_sessions.get(session_id)


def register_qr_login_queue(session_id: str, result_queue: queue.Queue) -> None:
    _active_qr_login_sessions[session_id] = result_queue


def load_persisted_qr_sessions() -> dict:
    if not QR_LOGIN_SESSIONS_FILE.exists():
        return {}
    try:
        data = json.loads(QR_LOGIN_SESSIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_persisted_qr_sessions(sessions: dict) -> None:
    QR_LOGIN_SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    QR_LOGIN_SESSIONS_FILE.write_text(
        json.dumps(sessions, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _parse_iso_datetime(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except Exception:
        return None


def cleanup_stale_qr_sessions() -> dict:
    persisted = load_persisted_qr_sessions()
    if not persisted:
        return {}

    cutoff = datetime.datetime.now() - datetime.timedelta(hours=PERSISTED_QR_SESSION_MAX_AGE_HOURS)
    kept = {}
    removed = {}
    for session_id, meta in persisted.items():
        updated_at = _parse_iso_datetime(meta.get("updated_at") or meta.get("created_at"))
        if updated_at and updated_at < cutoff:
            removed[session_id] = meta
            continue
        kept[session_id] = meta

    if removed:
        save_persisted_qr_sessions(kept)
        with _qr_login_lock:
            for session_id in removed:
                _qr_login_session_meta.pop(session_id, None)
                _active_qr_login_sessions.pop(session_id, None)

    return kept


def get_qr_session_meta(session_id: str) -> dict:
    with _qr_login_lock:
        session = _qr_login_session_meta.get(session_id)
        if session:
            return dict(session)

    persisted = load_persisted_qr_sessions()
    session = persisted.get(session_id) or {}
    if session:
        with _qr_login_lock:
            _qr_login_session_meta[session_id] = dict(session)
    return dict(session)


def update_qr_session(session_id: str, **updates) -> dict:
    with _qr_login_lock:
        session = _qr_login_session_meta.setdefault(session_id, {})
        session.update(updates)
        session["updated_at"] = datetime.datetime.now().isoformat()
        if "created_at" not in session:
            session["created_at"] = session["updated_at"]
        result = dict(session)

        persisted = load_persisted_qr_sessions()
        persisted[session_id] = result
        save_persisted_qr_sessions(persisted)
        return result


def delete_qr_session_meta(session_id: str) -> None:
    with _qr_login_lock:
        _qr_login_session_meta.pop(session_id, None)
        persisted = load_persisted_qr_sessions()
        if session_id in persisted:
            del persisted[session_id]
            save_persisted_qr_sessions(persisted)


def iter_recent_temp_cookie_candidates(platform: str | None = None) -> list[dict]:
    cookies_dir = get_sau_root() / "cookies"
    if not cookies_dir.exists():
        return []

    cutoff = datetime.datetime.now() - datetime.timedelta(hours=RECOVERABLE_QR_COOKIE_MAX_AGE_HOURS)
    requested_platforms = [platform] if platform else PLATFORMS
    candidates = []
    for current_platform in requested_platforms:
        for cookie_file in cookies_dir.glob(f"{current_platform}_tmp_*.json"):
            try:
                stat = cookie_file.stat()
            except FileNotFoundError:
                continue
            modified_at = datetime.datetime.fromtimestamp(stat.st_mtime)
            if modified_at < cutoff:
                try:
                    cookie_file.unlink()
                except FileNotFoundError:
                    pass
                continue
            temp_account = cookie_file.stem[len(f"{current_platform}_") :]
            if not temp_account.startswith("tmp_"):
                continue
            candidates.append(
                {
                    "platform": current_platform,
                    "temp_account": temp_account,
                    "cookie_path": str(cookie_file),
                    "modified_at": modified_at.isoformat(),
                    "mtime": stat.st_mtime,
                }
            )

    candidates.sort(key=lambda item: item["mtime"], reverse=True)
    return candidates


def list_recoverable_qr_logins(platform: str | None = None, limit: int = 5) -> list[dict]:
    persisted = cleanup_stale_qr_sessions()
    session_index = {}
    for session_id, meta in persisted.items():
        key = (meta.get("platform"), meta.get("current_account") or meta.get("temp_account"))
        if not all(key):
            continue
        current = session_index.get(key)
        if not current or meta.get("updated_at", "") > current.get("updated_at", ""):
            session_index[key] = {"session_id": session_id, **meta}

    recoverable = []
    for candidate in iter_recent_temp_cookie_candidates(platform):
        key = (candidate["platform"], candidate["temp_account"])
        session_meta = session_index.get(key, {})
        is_valid = session_meta.get("status") == "success"
        if not is_valid and not session_meta:
            continue
        if not is_valid:
            is_valid = is_account_cookie_valid(candidate["platform"], candidate["temp_account"])
        if not is_valid:
            continue

        recoverable.append(
            {
                "platform": candidate["platform"],
                "temp_account": candidate["temp_account"],
                "cookie_path": candidate["cookie_path"],
                "modified_at": candidate["modified_at"],
                "session_id": session_meta.get("session_id"),
                "status": session_meta.get("status") or "success",
                "current_account": session_meta.get("current_account") or candidate["temp_account"],
                "source": "session" if session_meta else "cookie",
            }
        )
        if len(recoverable) >= max(limit, 1):
            break

    return recoverable


def find_latest_recoverable_qr_login(platform: str | None = None) -> dict | None:
    recoverable = list_recoverable_qr_logins(platform=platform, limit=1)
    return recoverable[0] if recoverable else None


def recover_qr_session_from_cookie(session_id: str, meta: dict | None = None) -> dict:
    session = dict(meta or get_qr_session_meta(session_id))
    if not session or session.get("status") == "success":
        return session
    if session.get("force"):
        return session

    platform = session.get("platform")
    candidate_accounts = [
        session.get("current_account"),
        session.get("temp_account"),
        session.get("requested_account"),
    ]
    for candidate in candidate_accounts:
        if not platform or not candidate:
            continue
        cookie_path = get_sau_cookie_path(platform, candidate)
        if cookie_path.exists() and is_account_cookie_valid(platform, candidate):
            return update_qr_session(
                session_id,
                status="success",
                current_account=candidate,
                recovered_from_cookie=True,
            )
    return session


def close_qr_login_session(session_id: str, clear_meta: bool = False):
    if session_id in _active_qr_login_sessions:
        del _active_qr_login_sessions[session_id]
    if clear_meta:
        delete_qr_session_meta(session_id)


def delete_recoverable_qr_login(platform: str, temp_account: str, session_id: str | None = None) -> dict:
    normalized_platform = (platform or "").strip()
    normalized_temp_account = (temp_account or "").strip()
    if not normalized_platform:
        raise ValueError("platform is required")
    if not normalized_temp_account.startswith("tmp_"):
        raise ValueError("temp_account is required")

    cookie_path = get_sau_cookie_path(normalized_platform, normalized_temp_account)
    cookie_deleted = False
    if cookie_path.exists():
        cookie_path.unlink()
        cookie_deleted = True

    persisted = load_persisted_qr_sessions()
    matched_session_ids = []
    if session_id:
        matched_session_ids.append(session_id)
    matched_session_ids.extend(
        key
        for key, meta in persisted.items()
        if meta.get("platform") == normalized_platform
        and (meta.get("current_account") or meta.get("temp_account")) == normalized_temp_account
    )

    for matched_id in dict.fromkeys(matched_session_ids):
        close_qr_login_session(matched_id, clear_meta=True)

    return {
        "platform": normalized_platform,
        "temp_account": normalized_temp_account,
        "cookie_deleted": cookie_deleted,
        "deleted_sessions": list(dict.fromkeys(matched_session_ids)),
    }
