import json
import math
import shutil
import subprocess
from pathlib import Path

from services.process_runner import run_cmd


VIDEO_EXTENSIONS = {
    ".mp4",
    ".m4v",
    ".mov",
    ".webm",
    ".mkv",
    ".avi",
    ".flv",
    ".wmv",
    ".ts",
    ".mts",
    ".m2ts",
}


def upload_temp_path(job_dir: Path, filename: str | None) -> Path:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        suffix = ".video"
    return job_dir / f"original.upload{suffix}"


def normalize_uploaded_video(input_path: Path, output_path: Path, log_file: Path) -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise ValueError("服务器缺少 ffmpeg/ffprobe，无法识别或转换上传视频。")

    if _is_standard_mp4(input_path):
        if input_path.resolve() != output_path.resolve():
            shutil.move(str(input_path), str(output_path))
        return

    output_path.unlink(missing_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-fflags",
        "+genpts",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    try:
        run_cmd(cmd, log_file=log_file, timeout=7200)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        output_path.unlink(missing_ok=True)
        raise ValueError(
            "无法识别或转换上传视频。请尝试用 VLC/剪映/浏览器重新导出为 MP4 后再上传。"
        ) from exc

    if not _has_usable_duration(output_path):
        output_path.unlink(missing_ok=True)
        raise ValueError("上传视频已转换，但仍无法读取有效时长。请重新导出视频后再上传。")


def _is_standard_mp4(path: Path) -> bool:
    data = _probe(path)
    if not data:
        return False

    format_name = data.get("format", {}).get("format_name", "")
    if "mp4" not in format_name and "mov" not in format_name:
        return False
    if not _parse_duration(data.get("format", {}).get("duration")):
        return False

    streams = data.get("streams", [])
    video_stream = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio_streams = [item for item in streams if item.get("codec_type") == "audio"]
    if not video_stream or video_stream.get("codec_name") != "h264":
        return False
    return all(item.get("codec_name") == "aac" for item in audio_streams)


def _has_usable_duration(path: Path) -> bool:
    data = _probe(path)
    if not data:
        return False
    if _parse_duration(data.get("format", {}).get("duration")):
        return True
    return any(
        _parse_duration(stream.get("duration"))
        for stream in data.get("streams", [])
    )


def _probe(path: Path) -> dict | None:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=format_name,duration:stream=codec_type,codec_name,duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        output = subprocess.check_output(cmd, text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return json.loads(output)


def _parse_duration(value) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(duration) or duration <= 0:
        return None
    return duration
