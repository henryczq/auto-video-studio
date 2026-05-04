import datetime
import os
import subprocess
import threading
from pathlib import Path

from services.social_accounts import get_account, update_account
from services.social_config import get_bilibili_provider, get_categories, get_sau_python
from services.social_logs import LOGS_DIR, add_upload_record, ensure_logs_dir, update_upload_record


ROOT_DIR = Path(__file__).parent.parent.parent.parent
BRIDGE_PLATFORMS = {"tencent", "baijiahao", "tiktok"}
COOKIE_DIR_NAMES = {
    "tencent": "tencent_uploader",
    "baijiahao": "baijiahao_uploader",
    "tiktok": "tk_uploader",
    "bilibili": "bilibili_web_uploader",
}


def is_bridge_platform(platform: str) -> bool:
    return platform in BRIDGE_PLATFORMS or (
        platform == "bilibili" and get_bilibili_provider() == "bilibili-web-upload"
    )


def _append_log_line(log_file: Path, text: str) -> None:
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(text)


def _stream_reader(stream, sink: list[str], log_file: Path, prefix: str, lock: threading.Lock) -> None:
    try:
        for line in iter(stream.readline, ""):
            if not line:
                break
            sink.append(line)
            with lock:
                _append_log_line(log_file, f"{prefix}{line}")
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _find_chrome_path() -> str:
    candidates = [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/snap/bin/chromium",
    ]
    for item in candidates:
        if Path(item).exists():
            return item
    return ""


def _resolve_cookie_path(account: dict) -> Path:
    custom = (account.get("cookie_path") or "").strip()
    if custom:
        return Path(custom).expanduser().resolve()

    platform = account["platform"]
    account_name = (account.get("account") or "").strip()
    if not account_name:
        raise ValueError("请先给账号填写保存名称，再执行网页登录")

    if platform == "bilibili":
        path = ROOT_DIR / "publish" / "bilibili-web-upload" / "cookies" / COOKIE_DIR_NAMES[platform] / f"{account_name}.json"
    else:
        path = ROOT_DIR / "publish" / "social-auto-upload" / "cookies" / COOKIE_DIR_NAMES[platform] / f"{account_name}.json"
    update_account(account["id"], {"cookie_path": str(path)})
    return path


def _build_bridge_base_cmd(platform: str, cookie_path: Path) -> list[str]:
    sau_python = get_sau_python()
    bridge_script = ROOT_DIR / "core" / "tools" / "bridge_publish.py"
    cmd = [
        str(sau_python),
        str(bridge_script),
        "--platform",
        platform,
        "--account-file",
        str(cookie_path),
    ]
    chrome_path = _find_chrome_path()
    if chrome_path:
        cmd.extend(["--chrome-path", chrome_path])
    return cmd


def _resolve_bilibili_category(tid: str) -> str:
    value = (tid or "").strip()
    if not value:
        return ""
    for item in get_categories("bilibili"):
        if str(item.get("id")) == value:
            return str(item.get("name") or "").strip()
    return value


def prepare_bridge_account_cookie(account_id: str) -> dict:
    account = get_account(account_id)
    if not account:
        raise ValueError(f"账号不存在: {account_id}")
    if not is_bridge_platform(account["platform"]):
        raise ValueError(f"平台 {account['platform']} 不需要桥接网页登录")

    ensure_logs_dir()
    log_file = LOGS_DIR / f"{account_id}.log"
    cookie_path = _resolve_cookie_path(account)
    cookie_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = _build_bridge_base_cmd(account["platform"], cookie_path)
    cmd.append("--setup-cookie")

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"\n{'=' * 50}\n")
        f.write(f"[{datetime.datetime.now().isoformat()}] Web 登录准备\n")
        f.write(f"$ {' '.join(cmd)}\n")
        f.write("说明: 浏览器打开后，请在页面中完成登录；当前实现基于 Playwright pause，登录完成后需要在 Inspector 中 Resume。\n\n")

    env = os.environ.copy()
    env["DISPLAY"] = env.get("DISPLAY", ":0")
    process = subprocess.Popen(
        cmd,
        cwd=str(ROOT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    log_lock = threading.Lock()
    stdout_thread = threading.Thread(
        target=_stream_reader,
        args=(process.stdout, stdout_lines, log_file, "", log_lock),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_stream_reader,
        args=(process.stderr, stderr_lines, log_file, "[stderr] ", log_lock),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    def _wait() -> None:
        returncode = process.wait()
        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)
        output_text = "".join(stdout_lines)
        error_text = "".join(stderr_lines)
        with log_lock:
            _append_log_line(log_file, f"\nExit code: {returncode}\n")
        update_account(
            account_id,
            {
                "last_check_status": "valid" if returncode == 0 else "invalid",
                "last_check_at": datetime.datetime.now().isoformat(),
                "last_error": error_text[:500] if error_text else "",
                "cookie_path": str(cookie_path),
            },
        )

    threading.Thread(target=_wait, daemon=True).start()
    return {
        "status": "queued",
        "account_id": account_id,
        "cookie_path": str(cookie_path),
        "log_file": str(log_file),
    }


def check_bridge_account_status(account_id: str) -> dict:
    account = get_account(account_id)
    if not account:
        raise ValueError(f"账号不存在: {account_id}")
    if not is_bridge_platform(account["platform"]):
        raise ValueError(f"平台 {account['platform']} 不需要桥接校验")

    ensure_logs_dir()
    log_file = LOGS_DIR / f"{account_id}.log"
    cookie_path = _resolve_cookie_path(account)
    cmd = _build_bridge_base_cmd(account["platform"], cookie_path)
    cmd.append("--check-cookie")

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"\n{'=' * 50}\n")
        f.write(f"[{datetime.datetime.now().isoformat()}] 检查桥接登录状态\n")
        f.write(f"$ {' '.join(cmd)}\n\n")

    result = subprocess.run(
        cmd,
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
    )

    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    with open(log_file, "a", encoding="utf-8") as f:
        if output:
            f.write(output + "\n")
        if error:
            f.write("[stderr] " + error + "\n")
        f.write(f"Exit code: {result.returncode}\n")

    status = "valid" if result.returncode == 0 else "invalid"
    update_account(
        account_id,
        {
            "last_check_status": status,
            "last_check_at": datetime.datetime.now().isoformat(),
            "last_error": error[:500],
            "cookie_path": str(cookie_path),
        },
    )
    return {
        "status": status,
        "output": output,
        "error": error[:500],
    }


def bridge_publish_video(
    job_id: str,
    account_id: str,
    video_path: str,
    title: str,
    desc: str = "",
    tags: str = "",
    publish_mode: str = "",
    schedule: str = "",
    tid: str = "",
    cli_name: str = None,
    record_id: str | None = None,
    thumbnail: str = "",
    preview: bool = False,
) -> dict:
    account = get_account(account_id)
    if not account:
        raise ValueError(f"账号不存在: {account_id}")
    if not is_bridge_platform(account["platform"]):
        raise ValueError(f"平台 {account['platform']} 不支持桥接发布")

    platform = account["platform"]
    cookie_path = _resolve_cookie_path(account)
    root_dir = ROOT_DIR
    job_dir = (root_dir / "videos" / "web_jobs" / job_id).resolve()
    job_logs_dir = job_dir / "logs"
    job_logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = job_logs_dir / f"upload-{platform}.log"

    resolved_video_path = Path(video_path)
    if not resolved_video_path.is_absolute():
        resolved_video_path = (job_dir / video_path).resolve()
    else:
        resolved_video_path = resolved_video_path.resolve()
    if job_dir not in resolved_video_path.parents and resolved_video_path != job_dir:
        raise ValueError(f"Invalid video path: {video_path}")

    resolved_thumbnail_path = None
    if thumbnail and thumbnail.strip():
        resolved_thumbnail_path = Path(thumbnail.strip())
        if not resolved_thumbnail_path.is_absolute():
            resolved_thumbnail_path = (job_dir / thumbnail.strip()).resolve()
        else:
            resolved_thumbnail_path = resolved_thumbnail_path.resolve()
        if job_dir not in resolved_thumbnail_path.parents and resolved_thumbnail_path != job_dir:
            raise ValueError(f"Invalid thumbnail path: {thumbnail}")

    cmd = _build_bridge_base_cmd(platform, cookie_path)
    cmd.extend(
        [
            "--job-id",
            job_id,
            "--video-path",
            str(resolved_video_path),
            "--title",
            title,
        ]
    )

    if tags:
        cmd.extend(["--tags", tags])
    if desc:
        cmd.extend(["--desc", desc])
    if schedule:
        cmd.extend(["--schedule", schedule])
    if platform == "tencent" and publish_mode == "draft":
        cmd.append("--draft")
    if platform == "bilibili":
        category = _resolve_bilibili_category(tid)
        if category:
            cmd.extend(["--category", category])
    if resolved_thumbnail_path:
        cmd.extend(["--thumbnail", str(resolved_thumbnail_path)])
    if preview:
        cmd.append("--preview")

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"\n{'=' * 50}\n")
        f.write(f"[{datetime.datetime.now().isoformat()}] 桥接上传视频\n")
        f.write(f"$ {' '.join(cmd)}\n\n")

    if record_id:
        update_upload_record(
            record_id,
            {
                "status": "running",
                "video_path": str(resolved_video_path),
                "log_path": str(log_file),
                "error": "",
                "output": "",
            },
        )

    process = subprocess.Popen(
        cmd,
        cwd=str(root_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    log_lock = threading.Lock()
    stdout_thread = threading.Thread(
        target=_stream_reader,
        args=(process.stdout, stdout_lines, log_file, "", log_lock),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_stream_reader,
        args=(process.stderr, stderr_lines, log_file, "[stderr] ", log_lock),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    try:
        returncode = process.wait(timeout=3600)
    except subprocess.TimeoutExpired:
        process.kill()
        returncode = -1
        with log_lock:
            _append_log_line(log_file, "\nError: 上传超时\n")
        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)
        output_text = "".join(stdout_lines)
        record = update_upload_record(
            record_id,
            {
                "success": 0,
                "status": "timeout",
                "output": output_text[:2000],
                "error": "上传超时",
                "log_path": str(log_file),
                "video_path": str(resolved_video_path),
            },
        ) if record_id else add_upload_record(
            job_id=job_id,
            platform=platform,
            account_id=account_id,
            title=title,
            video_path=str(resolved_video_path),
            success=False,
            desc=desc,
            tags=tags,
            output=output_text[:2000],
            error="上传超时",
            status="timeout",
            log_path=str(log_file),
        )
        return {
            "success": False,
            "output": output_text,
            "error": "上传超时",
            "exit_code": -1,
            "log_file": str(log_file),
            "record_id": record["id"],
        }

    stdout_thread.join(timeout=2)
    stderr_thread.join(timeout=2)
    output_text = "".join(stdout_lines)
    error_text = "".join(stderr_lines)
    with log_lock:
        _append_log_line(log_file, f"\nExit code: {returncode}\n")

    success = returncode == 0
    record_updates = {
        "success": 1 if success else 0,
        "status": "success" if success else "failed",
        "output": output_text[:2000],
        "error": error_text[:500] if error_text else "",
        "log_path": str(log_file),
        "video_path": str(resolved_video_path),
    }
    record = update_upload_record(record_id, record_updates) if record_id else add_upload_record(
        job_id=job_id,
        platform=platform,
        account_id=account_id,
        title=title,
        video_path=str(resolved_video_path),
        success=success,
        desc=desc,
        tags=tags,
        output=output_text[:2000],
        error=error_text[:500] if error_text else "",
        status="success" if success else "failed",
        log_path=str(log_file),
    )
    return {
        "success": success,
        "output": output_text,
        "error": error_text[:500] if error_text else "",
        "exit_code": returncode,
        "log_file": str(log_file),
        "record_id": record["id"],
    }
