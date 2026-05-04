import datetime
import re
import subprocess
import sys
import uuid
from pathlib import Path

from services.social_config import get_sau_cli, get_sau_python, get_sau_root


def normalize_account_alias(account_name: str | None) -> str:
    raw = (account_name or "").strip()
    normalized = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", raw).strip("_")
    return normalized[:64] if normalized else ""


def build_temp_account_alias(platform: str) -> str:
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"tmp_{platform}_{timestamp}_{uuid.uuid4().hex[:6]}"


def prepare_sau_imports() -> Path:
    sau_root = get_sau_root()
    sau_root_str = str(sau_root)
    if sau_root_str not in sys.path:
        sys.path.insert(0, sau_root_str)
    return sau_root


def get_sau_cookie_path(platform: str, account_name: str) -> Path:
    return get_sau_root() / "cookies" / f"{platform}_{account_name}.json"


def is_account_cookie_valid(platform: str, account_name: str) -> bool:
    sau_python = get_sau_python()
    sau_cli = get_sau_cli()
    sau_root = get_sau_root()
    cookie_path = get_sau_cookie_path(platform, account_name)
    if not cookie_path.exists():
        return False
    try:
        result = subprocess.run(
            [str(sau_python), str(sau_cli), platform, "check", "--account", account_name],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(sau_root),
        )
        return result.returncode == 0 and "valid" in (result.stdout or "").lower()
    except Exception:
        return False
