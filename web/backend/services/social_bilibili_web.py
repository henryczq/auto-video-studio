import asyncio
import os
from pathlib import Path

from services.social_common import build_temp_account_alias
from services.social_config import get_bilibili_provider
from services.social_qr import get_qr_session_meta, update_qr_session
from services.social_bridge_runner import ROOT_DIR, _build_bridge_base_cmd


def is_bilibili_web_provider() -> bool:
    return get_bilibili_provider() == "bilibili-web-upload"


async def login_bilibili_web_browser(session_id: str) -> dict:
    meta = get_qr_session_meta(session_id)
    temp_account = meta.get("temp_account") or build_temp_account_alias("bilibili")
    existing_path = (meta.get("account_file") or "").strip()
    cookie_path = Path(existing_path).expanduser().resolve() if existing_path else (
        ROOT_DIR
        / "publish"
        / "bilibili-web-upload"
        / "cookies"
        / "bilibili_web_uploader"
        / f"{temp_account}.json"
    )
    cookie_path.parent.mkdir(parents=True, exist_ok=True)
    update_qr_session(
        session_id,
        platform="bilibili",
        status="pending",
        temp_account=temp_account,
        current_account=temp_account,
        account_file=str(cookie_path),
        last_status="正在打开 B站网页投稿登录浏览器，请完成登录...",
    )

    cmd = _build_bridge_base_cmd("bilibili", cookie_path)
    cmd.append("--setup-cookie")
    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(Path(__file__).resolve().parents[3]),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
    )
    stdout, stderr = await process.communicate()
    output = stdout.decode("utf-8", errors="replace").strip()
    error = stderr.decode("utf-8", errors="replace").strip()
    if process.returncode == 0 and cookie_path.exists():
        update_qr_session(
            session_id,
            status="success",
            current_account=temp_account,
            account_file=str(cookie_path),
            last_message="B站网页投稿登录成功",
        )
        return {
            "success": True,
            "message": "B站网页投稿登录成功",
            "account": temp_account,
            "account_file": str(cookie_path),
            "terminal_output": output[-1000:],
        }

    message = error[-1000:] or output[-1000:] or "B站网页投稿登录失败"
    update_qr_session(
        session_id,
        status="error",
        current_account=temp_account,
        account_file=str(cookie_path),
        last_error=message,
    )
    return {
        "success": False,
        "message": message,
        "account": temp_account,
        "account_file": str(cookie_path),
        "terminal_output": output[-1000:],
    }
