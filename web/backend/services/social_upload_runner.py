import datetime
import subprocess
import threading
from pathlib import Path

from services.social_accounts import get_account
from services.social_config import get_sau_cli, get_sau_python, get_sau_root
from services.social_logs import add_upload_record, update_upload_record


def _normalize_upload_error(platform: str, error_text: str) -> str:
    text = (error_text or "").strip()
    if not text:
        return text

    if platform == "bilibili" and ("21150" in text or "投稿入口升级中" in text):
        return (
            "B站投稿接口暂时不可用：投稿入口升级中（21150）。"
            " 当前 CLI 已自动尝试 app / b-cut-android / web 三套投稿接口，但都被 B站拒绝。"
            " 请先打开 B站创作中心手动补发，或稍后再试。"
        )

    return text


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


def _resolve_job_file_path(job_id: str, file_path: str) -> Path:
    """Safely resolve a file path within a job directory.

    Rejects paths that escape the job directory (path traversal).
    """
    root_dir = Path(__file__).parent.parent.parent.parent
    job_dir = (root_dir / "videos" / "web_jobs" / job_id).resolve()
    target = Path(file_path)
    if not target.is_absolute():
        target = (job_dir / file_path).resolve()
    else:
        target = target.resolve()
    if job_dir not in target.parents and target != job_dir:
        raise ValueError(f"Invalid path: {file_path}")
    return target


def upload_video(
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

    sau_root = get_sau_root()
    sau_python = get_sau_python()
    sau_cli = get_sau_cli()
    platform = account["platform"]
    cli_platform = cli_name or platform

    root_dir = Path(__file__).parent.parent.parent.parent
    job_logs_dir = root_dir / "videos" / "web_jobs" / job_id / "logs"
    job_logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = job_logs_dir / f"upload-{platform}.log"
    resolved_video_path = _resolve_job_file_path(job_id, video_path)
    resolved_thumbnail_path = None
    if thumbnail and thumbnail.strip():
        resolved_thumbnail_path = _resolve_job_file_path(job_id, thumbnail.strip())

    cmd = [
        str(sau_python),
        "-u",
        str(sau_cli),
        cli_platform,
        "upload-video",
        "--account",
        account["account"],
        "--file",
        str(resolved_video_path),
        "--title",
        title,
    ]

    if desc:
        cmd.extend(["--desc", desc])
    if tags:
        cmd.extend(["--tags", tags])
    if platform == "xiaohongshu" and publish_mode == "draft":
        cmd.append("--draft")
    if schedule:
        cmd.extend(["--schedule", schedule])
    if platform == "bilibili" and tid:
        cmd.extend(["--tid", tid])
    if resolved_thumbnail_path:
        cmd.extend(["--thumbnail", str(resolved_thumbnail_path)])
    if platform in {"douyin", "kuaishou", "xiaohongshu"}:
        cmd.append("--headed")
    if preview:
        cmd.append("--preview")

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"\n{'=' * 50}\n")
        f.write(f"[{datetime.datetime.now().isoformat()}] 上传视频\n")
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

    try:
        process = subprocess.Popen(
            cmd,
            cwd=str(sau_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
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
            returncode = process.wait(timeout=600)
        except subprocess.TimeoutExpired:
            process.kill()
            returncode = -1
            with log_lock:
                _append_log_line(log_file, "\nError: 上传超时\n")
            stdout_thread.join(timeout=2)
            stderr_thread.join(timeout=2)
            output_text = "".join(stdout_lines)
            error_text = "".join(stderr_lines)
            normalized_error = _normalize_upload_error(platform, error_text)
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
        normalized_error = _normalize_upload_error(platform, error_text)
        with log_lock:
            _append_log_line(log_file, f"\nExit code: {returncode}\n")

        success = returncode == 0
        record_updates = {
            "success": 1 if success else 0,
            "status": "success" if success else "failed",
            "output": output_text[:2000],
            "error": normalized_error[:500] if normalized_error else "",
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
            error=normalized_error[:500] if normalized_error else "",
            status="success" if success else "failed",
            log_path=str(log_file),
        )
        return {
            "success": success,
            "output": output_text,
            "error": normalized_error[:500] if normalized_error else "",
            "exit_code": returncode,
            "log_file": str(log_file),
            "record_id": record["id"],
        }
    except Exception as exc:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\nError: {exc}\n")
        record = update_upload_record(
            record_id,
            {
                "success": 0,
                "status": "failed",
                "error": str(exc),
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
            error=str(exc),
            status="failed",
            log_path=str(log_file),
        )
        return {
            "success": False,
            "output": "",
            "error": str(exc),
            "exit_code": -1,
            "log_file": str(log_file),
            "record_id": record["id"],
        }
