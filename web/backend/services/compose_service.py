import json
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from services.job_store import get_job_dir, get_logs_dir, load_job, save_job
from services.process_runner import run_cmd
from services.video_pipeline import ensure_final_captions_srt


@dataclass
class AudioOptimizeOptions:
    preset: str = "voice_light"
    denoise: bool = True
    loudnorm: bool = True
    compressor: bool = True


def validate_playback_rate(playback_rate: float) -> float:
    rate = float(playback_rate or 1.0)
    if rate < 0.8 or rate > 1.5:
        raise ValueError("合成倍速只支持 0.80x 到 1.50x")
    return rate


def get_compose_video_path(job_id: str) -> tuple[Path | None, str]:
    job = load_job(job_id)
    if not job:
        return None, "任务不存在"
    job_dir = get_job_dir(job_id)
    if job.video_trimmed:
        return job_dir / job.video_trimmed, "裁剪后视频"
    if job.processed_video:
        return job_dir / job.processed_video, "处理后视频"
    return job_dir / "processed.mp4", "处理后视频"


def get_compose_captions_path(job_id: str) -> tuple[Path | None, str]:
    job = load_job(job_id)
    if not job:
        return None, "任务不存在"
    job_dir = get_job_dir(job_id)
    if job.captions_trimmed:
        return job_dir / job.captions_trimmed, "裁剪后字幕"
    trimmed_json_srt = job_dir / "captions.trimmed.srt"
    if trimmed_json_srt.exists():
        return trimmed_json_srt, "裁剪后字幕"
    try:
        return ensure_final_captions_srt(job_id), "当前字幕"
    except Exception:
        if job.captions_final:
            return job_dir / job.captions_final, "当前字幕"
        return job_dir / "captions.final.srt", "当前字幕"


def get_video_dimensions(video_path: Path) -> tuple[int, int]:
    try:
        result = run_cmd(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                str(video_path),
            ],
            check=True,
            timeout=30,
        )
        info = json.loads(result.stdout)
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "video":
                width = int(stream.get("width") or 1080)
                height = int(stream.get("height") or 1920)
                return width, height
    except Exception:
        pass
    return 1080, 1920


def build_audio_filter(options: AudioOptimizeOptions) -> str:
    if options.preset == "voice_light":
        return (
            "highpass=f=80,"
            "lowpass=f=8500,"
            "afftdn=nf=-25,"
            "equalizer=f=3000:t=q:w=1.2:g=3,"
            "acompressor=threshold=-20dB:ratio=2.5:attack=5:release=80:makeup=2,"
            "alimiter=limit=0.95"
        )
    if options.preset == "voice_strong":
        return (
            "highpass=f=100,"
            "lowpass=f=7200,"
            "afftdn=nf=-30,"
            "equalizer=f=2500:t=q:w=1.0:g=4,"
            "equalizer=f=4500:t=q:w=1.0:g=2,"
            "dynaudnorm=f=151:g=12,"
            "alimiter=limit=0.92"
        )

    filters = []
    if options.denoise:
        filters.append("afftdn=nf=-25")
    if options.loudnorm:
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    if options.compressor:
        filters.extend(
            [
                "acompressor=threshold=-18dB:ratio=3:attack=5:release=80:makeup=2",
                "alimiter=limit=0.95",
            ]
        )
    return ",".join(filters) or "anull"


def optimize_audio(job_id: str, options: AudioOptimizeOptions | None = None) -> dict[str, str]:
    options = options or AudioOptimizeOptions()
    job_dir = get_job_dir(job_id)
    video_path, video_label = get_compose_video_path(job_id)
    if not video_path or not video_path.exists():
        return {"error": f"视频文件不存在（{video_label}）"}

    audio_path = job_dir / "optimized.audio.wav"
    old_preview_path = job_dir / "video.audio.optimized.mp4"
    log_file = get_logs_dir(job_id) / "compose.log"
    audio_filter = build_audio_filter(options)

    extract_cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-i",
        str(video_path),
        "-vn",
        "-af",
        audio_filter,
        "-ar",
        "48000",
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        str(audio_path),
    ]

    try:
        result = run_cmd(extract_cmd, log_file=log_file, check=False, timeout=1800)
        if result.returncode != 0:
            return {"error": f"声音优化失败: {result.stderr[:500]}"}
    except subprocess.TimeoutExpired:
        return {"error": "声音优化超时"}
    except Exception as e:
        return {"error": f"声音优化异常: {str(e)}"}

    if old_preview_path.exists():
        try:
            old_preview_path.unlink()
        except Exception:
            pass

    job = load_job(job_id)
    if job:
        job.optimized_audio = "optimized.audio.wav"
        job.video_audio_optimized = None
        job.status = "audio_optimized"
        job.compose_error = None
        save_job(job)

    return {
        "status": "audio_optimized",
        "audio_path": "optimized.audio.wav",
        "video_label": video_label,
        "audio_filter": audio_filter,
    }


def compose_original_video(job_id: str, audio_mode: str = "original", playback_rate: float = 1.0) -> dict[str, str]:
    job_dir = get_job_dir(job_id)
    video_path, video_label = get_compose_video_path(job_id)
    if not video_path or not video_path.exists():
        return {"error": f"视频文件不存在（{video_label}）"}

    captions_path, captions_label = get_compose_captions_path(job_id)
    if not captions_path or not captions_path.exists():
        return {"error": f"字幕文件不存在（{captions_label}）"}

    playback_rate = validate_playback_rate(playback_rate)
    output_path = job_dir / "final.subtitles.video.mp4"
    log_file = get_logs_dir(job_id) / "compose.log"

    srt_content = captions_path.read_text(encoding="utf-8")
    if abs(playback_rate - 1.0) > 1e-6:
        srt_content = scale_srt_timing(srt_content, playback_rate)
    video_width, video_height = get_video_dimensions(video_path)
    ass_content = convert_srt_to_ass(srt_content, video_width, video_height)
    ass_path = job_dir / "captions.compose.ass"
    ass_path.write_text(ass_content, encoding="utf-8")

    vf_filters = []
    if abs(playback_rate - 1.0) > 1e-6:
        vf_filters.append(f"setpts=PTS/{playback_rate:.6f}")
    vf_filters.append(f"ass={ass_path}")
    vf_filter = ",".join(vf_filters)

    audio_filters = []
    if abs(playback_rate - 1.0) > 1e-6:
        audio_filters.append(f"atempo={playback_rate:.6f}")

    if audio_mode == "optimized":
        job = load_job(job_id)
        optimized_audio_name = getattr(job, "optimized_audio", None) if job else None
        optimized_audio = job_dir / optimized_audio_name if optimized_audio_name else None
        if not optimized_audio or not optimized_audio.exists():
            return {"error": "还没有优化后的声音，请先执行声音优化，或改用原视频声音"}
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-i",
            str(video_path),
            "-i",
            str(optimized_audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-vf",
            vf_filter,
        ]
        if audio_filters:
            cmd.extend(["-af", ",".join(audio_filters)])
        cmd.extend([
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(output_path),
        ])
        audio_label = "优化后声音"
    else:
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-i",
            str(video_path),
            "-vf",
            vf_filter,
        ]
        if audio_filters:
            cmd.extend([
                "-af",
                ",".join(audio_filters),
                "-c:a",
                "aac",
                "-b:a",
                "192k",
            ])
        else:
            cmd.extend(["-c:a", "copy"])
        cmd.extend(["-shortest", str(output_path)])
        audio_label = "原视频声音"

    try:
        result = run_cmd(cmd, log_file=log_file, check=False, timeout=1800)
        if result.returncode != 0:
            return {"error": f"合成失败: {result.stderr[:500]}"}
    except subprocess.TimeoutExpired:
        return {"error": "合成超时"}
    except Exception as e:
        return {"error": f"合成异常: {str(e)}"}

    job = load_job(job_id)
    if job:
        job.final_subtitles_video = "final.subtitles.video.mp4"
        job.compose_version = job.captions_version
        job.status = "video_composed"
        save_job(job)

    return {
        "status": "composed",
        "video_path": "final.subtitles.video.mp4",
        "video_label": video_label,
        "captions_label": captions_label,
        "audio_label": audio_label,
        "playback_rate": playback_rate,
    }


def convert_srt_to_ass(
    srt_content: str, video_width: int = 1080, video_height: int = 1920
) -> str:
    font_size = max(32, min(48, round(video_width * 0.058)))
    margin_lr = max(42, round(video_width * 0.08))
    margin_v = max(36, round(video_height * 0.055))
    max_text_width = max(24, round((video_width - margin_lr * 2) / max(font_size * 0.45, 1)))

    ass_header = f"""[Script Info]
Title: Generated by Auto-Cut
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: None

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans CJK SC,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H90000000,1,0,0,0,100,100,0,0,1,2.4,0.7,2,{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ass_lines = [ass_header]

    for block in srt_content.strip().split("\n\n"):
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        time_line = lines[1]
        text_lines = lines[2:]

        try:
            start_str, end_str = time_line.split(" --> ")
            start = srt_time_to_ass(start_str.strip())
            end = srt_time_to_ass(end_str.strip())
        except Exception:
            continue

        text = wrap_ass_text("".join(text_lines), max_width=max_text_width)
        ass_lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    return "\n".join(ass_lines)


def ass_display_width(char: str) -> int:
    if unicodedata.east_asian_width(char) in {"F", "W", "A"}:
        return 2
    return 1


def wrap_ass_text(text: str, max_width: int = 34) -> str:
    normalized = escape_ass_text(" ".join(text.replace("\\N", " ").split()))
    if not normalized:
        return ""

    lines: list[str] = []
    current = ""
    width = 0
    for char in normalized:
        char_width = ass_display_width(char)
        if current and width + char_width > max_width:
            lines.append(current.rstrip())
            current = char.lstrip()
            width = ass_display_width(current) if current else 0
        else:
            current += char
            width += char_width

    if current:
        lines.append(current.rstrip())
    return "\\N".join(lines)


def escape_ass_text(text: str) -> str:
    return (
        text.replace("\\", "＼")
        .replace("{", "｛")
        .replace("}", "｝")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def srt_time_to_ass(time_str: str) -> str:
    time_str = time_str.replace(",", ".")
    parts = time_str.split(":")
    if len(parts) == 3:
        h, m, sec = parts
        return f"{int(h)}:{int(m)}:{float(sec):05.2f}"
    return "0:00:00.00"


def parse_srt_timestamp(value: str) -> float:
    normalized = value.replace(",", ".").strip()
    hours, minutes, seconds = normalized.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def format_srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours = total_ms // 3600000
    total_ms %= 3600000
    minutes = total_ms // 60000
    total_ms %= 60000
    secs = total_ms // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def scale_srt_timing(srt_content: str, playback_rate: float) -> str:
    blocks: list[str] = []
    for block in srt_content.strip().split("\n\n"):
        lines = block.strip().splitlines()
        if len(lines) < 3:
            blocks.append(block)
            continue
        try:
            start_str, end_str = lines[1].split(" --> ")
            start = parse_srt_timestamp(start_str) / playback_rate
            end = parse_srt_timestamp(end_str) / playback_rate
            lines[1] = f"{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}"
        except Exception:
            pass
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + ("\n" if srt_content.endswith("\n") else "")


def get_compose_result(job_id: str) -> dict[str, str]:
    job = load_job(job_id)
    if not job:
        return {"error": "任务不存在"}

    return {
        "final_subtitles_video": job.final_subtitles_video,
        "optimized_audio": getattr(job, "optimized_audio", None),
        "video_audio_optimized": getattr(job, "video_audio_optimized", None),
        "status": job.status,
    }
