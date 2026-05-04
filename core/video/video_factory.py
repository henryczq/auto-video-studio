#!/usr/bin/env python3
import argparse
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class Range:
    start: float
    end: float


SILENCE_START_RE = re.compile(r"silence_start:\s*(?P<time>[0-9.]+)")
SILENCE_END_RE = re.compile(r"silence_end:\s*(?P<time>[0-9.]+)")
_OPENCC_CONVERTER = None
_OPENCC_INITIALIZED = False


def get_opencc_converter():
    global _OPENCC_CONVERTER, _OPENCC_INITIALIZED
    if _OPENCC_INITIALIZED:
        return _OPENCC_CONVERTER
    _OPENCC_INITIALIZED = True
    try:
        from opencc import OpenCC

        _OPENCC_CONVERTER = OpenCC("t2s")
        print("字幕字形归一化: 已启用 OpenCC t2s（繁体转简体）。")
    except ModuleNotFoundError:
        _OPENCC_CONVERTER = None
        print("字幕字形归一化: 未安装 OpenCC，保持 Whisper 原始字形输出。")
    return _OPENCC_CONVERTER


def normalize_chinese_text(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        return normalized
    converter = get_opencc_converter()
    if not converter:
        return normalized
    return converter.convert(normalized)


def run_cmd(cmd: Sequence[str]) -> None:
    print("$", " ".join(shlex.quote(part) for part in cmd))
    subprocess.run(list(cmd), check=True)


def ensure_binary(name: str) -> None:
    if shutil.which(name):
        return
    raise SystemExit(f"未找到依赖: {name}")


def _is_rocm_kernel_error(exc: Exception) -> bool:
    message = str(exc)
    return (
        "HIP error" in message
        or "hipErrorInvalidImage" in message
        or "hipErrorInvalidKernelFile" in message
        or "device kernel image is invalid" in message
        or "invalid kernel file" in message
    )


def load_whisper_model(model_name: str, device: str):
    try:
        import whisper
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "未安装 openai-whisper。先执行: pip install openai-whisper"
        ) from exc
    whisper_device = "cuda" if device == "rocm" else device
    try:
        return whisper.load_model(model_name, device=whisper_device), whisper_device
    except RuntimeError as exc:
        if device == "rocm" and _is_rocm_kernel_error(exc):
            print(
                "检测到 ROCm Whisper 加载失败，自动回退到 CPU 转写。"
                f" 原因: {exc}"
            )
            return whisper.load_model(model_name, device="cpu"), "cpu"
        raise


def transcribe(input_file: str, model_name: str, language: str, device: str) -> List[Segment]:
    whisper_device = "cuda" if device == "rocm" else device
    print(
        f"正在转写音频: model={model_name}, language={language}, "
        f"device={device}, whisper_device={whisper_device}"
    )
    model, actual_device = load_whisper_model(model_name, device)
    print(f"Whisper 实际运行设备: {actual_device}")
    try:
        result = model.transcribe(input_file, language=language, verbose=False)
    except RuntimeError as exc:
        if device == "rocm" and actual_device != "cpu" and _is_rocm_kernel_error(exc):
            print(
                "检测到 ROCm Whisper 推理失败，自动回退到 CPU 转写。"
                f" 原因: {exc}"
            )
            model, actual_device = load_whisper_model(model_name, "cpu")
            print(f"Whisper 实际运行设备: {actual_device}")
            result = model.transcribe(input_file, language=language, verbose=False)
        else:
            raise
    segments = []
    for item in result.get("segments", []):
        text = normalize_chinese_text(item.get("text", ""))
        if not text:
            continue
        segments.append(
            Segment(
                start=float(item["start"]),
                end=float(item["end"]),
                text=text,
            )
        )
    if not segments:
        raise SystemExit("Whisper 没识别到任何带文本的语音片段。")
    return segments


def parse_duration_value(value) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(duration) or duration <= 0:
        return None
    return duration


def get_probe_duration(input_file: str) -> float | None:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=duration",
        "-of",
        "json",
        input_file,
    ]
    output = subprocess.check_output(cmd, text=True)
    data = json.loads(output)

    duration = parse_duration_value(data.get("format", {}).get("duration"))
    if duration:
        return duration

    stream_durations = [
        parsed
        for stream in data.get("streams", [])
        if (parsed := parse_duration_value(stream.get("duration"))) is not None
    ]
    if stream_durations:
        return max(stream_durations)
    return None


def get_packet_duration(input_file: str) -> float | None:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_packets",
        "-show_entries",
        "packet=pts_time,dts_time,duration_time",
        "-of",
        "csv=p=0",
        input_file,
    ]
    print("常规时长不可用，正在扫描媒体包时间戳推算时长。")
    print("$", " ".join(shlex.quote(part) for part in cmd))
    max_end = 0.0
    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as process:
        assert process.stdout is not None
        for line in process.stdout:
            fields = [field.strip() for field in line.strip().split(",")]
            pts = parse_duration_value(fields[0] if len(fields) > 0 else None)
            dts = parse_duration_value(fields[1] if len(fields) > 1 else None)
            packet_duration = parse_duration_value(fields[2] if len(fields) > 2 else None)
            timestamp = pts if pts is not None else dts
            if timestamp is None:
                continue
            max_end = max(max_end, timestamp + (packet_duration or 0.0))
        _, stderr = process.communicate()
        if process.returncode:
            raise subprocess.CalledProcessError(
                process.returncode,
                cmd,
                stderr=stderr,
            )
    return max_end if max_end > 0 else None


def get_duration(input_file: str) -> float:
    duration = get_probe_duration(input_file) or get_packet_duration(input_file)
    if duration:
        return duration
    raise SystemExit(
        "无法读取视频时长。这个文件可能缺少容器索引或已损坏，"
        "请先用 FFmpeg/VLC 转码或重新导出后再上传。"
    )


def merge_keep_ranges(
    segments: Sequence[Segment], margin: float, max_duration: float
) -> List[Range]:
    ranges: List[Range] = []
    for seg in segments:
        start = max(0.0, seg.start - margin)
        end = min(max_duration, seg.end + margin)
        if end <= start:
            continue
        if ranges and start <= ranges[-1].end:
            ranges[-1].end = max(ranges[-1].end, end)
        else:
            ranges.append(Range(start=start, end=end))
    return ranges


def merge_ranges(ranges: Sequence[Range]) -> List[Range]:
    merged: List[Range] = []
    for item in sorted(ranges, key=lambda value: value.start):
        if item.end <= item.start:
            continue
        if merged and item.start <= merged[-1].end:
            merged[-1].end = max(merged[-1].end, item.end)
        else:
            merged.append(Range(start=item.start, end=item.end))
    return merged


def detect_silence_ranges(
    input_file: str, noise_threshold: str, min_duration: float
) -> List[Range]:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        input_file,
        "-af",
        f"silencedetect=noise={noise_threshold}:d={min_duration}",
        "-f",
        "null",
        "-",
    ]
    print("$", " ".join(shlex.quote(part) for part in cmd))
    result = subprocess.run(cmd, check=True, text=True, capture_output=True)
    ranges: List[Range] = []
    current_start: float | None = None
    for line in result.stderr.splitlines():
        start_match = SILENCE_START_RE.search(line)
        if start_match:
            current_start = float(start_match.group("time"))
            continue
        end_match = SILENCE_END_RE.search(line)
        if end_match and current_start is not None:
            end = float(end_match.group("time"))
            if end > current_start:
                ranges.append(Range(start=current_start, end=end))
            current_start = None
    return ranges


def compress_silence_in_ranges(
    keep_ranges: Sequence[Range],
    silence_ranges: Sequence[Range],
    keep_silence: float,
) -> List[Range]:
    if keep_silence < 0:
        raise SystemExit("--silence-keep 不能小于 0。")

    compressed: List[Range] = []
    half_keep = keep_silence / 2.0
    for keep in keep_ranges:
        cursor = keep.start
        for silence in silence_ranges:
            if silence.end <= cursor:
                continue
            if silence.start >= keep.end:
                break

            overlap_start = max(silence.start, keep.start)
            overlap_end = min(silence.end, keep.end)
            if overlap_end <= overlap_start or overlap_end - overlap_start <= keep_silence:
                continue

            cut_start = min(overlap_start + half_keep, overlap_end)
            cut_end = max(overlap_end - half_keep, overlap_start)
            if cut_end <= cut_start:
                continue

            if cut_start > cursor:
                compressed.append(Range(start=cursor, end=cut_start))
            cursor = max(cursor, cut_end)

        if cursor < keep.end:
            compressed.append(Range(start=cursor, end=keep.end))

    return merge_ranges(compressed)


def drop_short_silent_ranges(
    keep_ranges: Sequence[Range],
    speech_segments: Sequence[Segment],
    min_duration: float,
) -> List[Range]:
    if min_duration <= 0:
        return list(keep_ranges)

    filtered: List[Range] = []
    for keep in keep_ranges:
        duration = keep.end - keep.start
        overlaps_speech = any(
            segment.end > keep.start and segment.start < keep.end
            for segment in speech_segments
        )
        if duration >= min_duration or overlaps_speech:
            filtered.append(keep)
    return filtered


def clip_segment_to_ranges(
    segment: Segment, keep_ranges: Sequence[Range]
) -> List[Segment]:
    clipped: List[Segment] = []
    output_offset = 0.0
    for keep in keep_ranges:
        keep_len = keep.end - keep.start
        overlap_start = max(segment.start, keep.start)
        overlap_end = min(segment.end, keep.end)
        if overlap_end > overlap_start:
            clipped.append(
                Segment(
                    start=output_offset + (overlap_start - keep.start),
                    end=output_offset + (overlap_end - keep.start),
                    text=segment.text,
                )
            )
        output_offset += keep_len
    return clipped


def remap_segments(segments: Sequence[Segment], keep_ranges: Sequence[Range]) -> List[Segment]:
    remapped: List[Segment] = []
    for segment in segments:
        remapped.extend(clip_segment_to_ranges(segment, keep_ranges))
    return remapped


def format_srt_time(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours = total_ms // 3_600_000
    minutes = (total_ms % 3_600_000) // 60_000
    secs = (total_ms % 60_000) // 1000
    ms = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def write_srt(segments: Sequence[Segment], output_file: Path) -> None:
    lines = []
    for idx, segment in enumerate(segments, start=1):
        lines.append(str(idx))
        lines.append(f"{format_srt_time(segment.start)} --> {format_srt_time(segment.end)}")
        lines.append(segment.text)
        lines.append("")
    output_file.write_text("\n".join(lines), encoding="utf-8")


def load_blur_regions(config_path: str | None) -> list[dict]:
    if not config_path:
        return []
    data = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("马赛克配置必须是 JSON 数组。")
    required = {"start", "end", "x", "y", "w", "h"}
    for idx, item in enumerate(data):
        if not isinstance(item, dict) or not required.issubset(item):
            raise SystemExit(f"第 {idx + 1} 个马赛克配置缺字段，必须包含: {sorted(required)}")
    return data


def escape_drawtext(value: str) -> str:
    return (
        value.replace("\\", r"\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace(",", r"\,")
        .replace("[", r"\[")
        .replace("]", r"\]")
    )


def build_filter_complex(
    keep_ranges: Sequence[Range],
    title_text: str | None,
    blur_regions: Sequence[dict],
) -> tuple[str, str, str]:
    if not keep_ranges:
        raise SystemExit("没有可保留的片段，无法导出视频。")

    chains: List[str] = []
    concat_inputs: List[str] = []

    for idx, keep in enumerate(keep_ranges):
        chains.append(
            f"[0:v]trim=start={keep.start}:end={keep.end},setpts=PTS-STARTPTS[v{idx}]"
        )
        chains.append(
            f"[0:a]atrim=start={keep.start}:end={keep.end},asetpts=PTS-STARTPTS[a{idx}]"
        )
        concat_inputs.append(f"[v{idx}][a{idx}]")

    chains.append(
        "".join(concat_inputs) + f"concat=n={len(keep_ranges)}:v=1:a=1[vcat][acat]"
    )

    current_v = "vcat"
    if title_text:
        escaped = escape_drawtext(title_text)
        chains.append(
            f"[{current_v}]drawtext=text='{escaped}':"
            "x=(w-text_w)/2:y=h-(text_h*2):"
            "fontcolor=white:fontsize=42:"
            "box=1:boxcolor=black@0.55:boxborderw=18"
            "[vtitle]"
        )
        current_v = "vtitle"

    for idx, blur in enumerate(blur_regions):
        split_base = f"vblur_src_{idx}"
        crop_out = f"vblur_crop_{idx}"
        next_label = f"vblur_{idx}"
        enable = f"between(t\\,{blur['start']}\\,{blur['end']})"
        chains.append(f"[{current_v}]split=2[{current_v}_base_{idx}][{split_base}]")
        chains.append(
            f"[{split_base}]crop=w={blur['w']}:h={blur['h']}:x={blur['x']}:y={blur['y']},"
            f"boxblur=20:10[{crop_out}]"
        )
        chains.append(
            f"[{current_v}_base_{idx}][{crop_out}]overlay=x={blur['x']}:y={blur['y']}:"
            f"enable='{enable}'[{next_label}]"
        )
        current_v = next_label

    return ";".join(chains), current_v, "acat"


def export_video(
    input_file: str,
    output_file: str,
    keep_ranges: Sequence[Range],
    title_text: str | None,
    blur_regions: Sequence[dict],
) -> None:
    filter_complex, video_label, audio_label = build_filter_complex(
        keep_ranges, title_text, blur_regions
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_file,
        "-filter_complex",
        filter_complex,
        "-map",
        f"[{video_label}]",
        "-map",
        f"[{audio_label}]",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        output_file,
    ]
    run_cmd(cmd)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="按语音片段自动裁掉空白，并导出字幕。"
    )
    parser.add_argument("input_file", help="输入视频路径，例如 demo.mp4")
    parser.add_argument(
        "--margin",
        type=float,
        default=3.0,
        help="每个说话片段前后保留秒数，默认 3.0",
    )
    parser.add_argument(
        "--model",
        default="base",
        help="Whisper 模型名称，默认 base",
    )
    parser.add_argument(
        "--language",
        default="zh",
        help="Whisper 语言代码，默认 zh",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        help="Whisper 推理设备，默认 cpu，可选如 cuda",
    )
    parser.add_argument(
        "--rocm-gfx-override",
        help="可选，设置 HSA_OVERRIDE_GFX_VERSION，例如 HX 370/890M 可试 11.0.0",
    )
    parser.add_argument(
        "--disable-db-cut",
        action="store_true",
        help="关闭 dB 长静音二次压缩，只按 Whisper 片段剪切",
    )
    parser.add_argument(
        "--silence-noise",
        default="-35dB",
        help="FFmpeg silencedetect 静音阈值，默认 -35dB",
    )
    parser.add_argument(
        "--silence-min-duration",
        type=float,
        default=5.0,
        help="超过多少秒的静音才二次压缩，默认 5.0",
    )
    parser.add_argument(
        "--silence-keep",
        type=float,
        default=1.0,
        help="每段长静音最多保留多少秒过渡，默认 1.0",
    )
    parser.add_argument(
        "--min-clip-duration",
        type=float,
        default=0.75,
        help="丢弃短于该秒数且不覆盖字幕文字的碎片，默认 0.75",
    )
    parser.add_argument(
        "--output",
        help="输出视频路径，默认 processed_<原文件名>.mp4",
    )
    parser.add_argument(
        "--output-dir",
        help="输出目录；未显式指定 --output 时，视频和字幕会写到该目录",
    )
    parser.add_argument(
        "--srt-output",
        help="输出字幕路径，默认与输出视频同名 .srt",
    )
    parser.add_argument(
        "--retranscribe-after-cut",
        action="store_true",
        help="导出剪后视频后，重新对剪后成片做一次 Whisper 转写，生成新的 SRT 时间轴",
    )
    parser.add_argument(
        "--title-text",
        help="可选，给成片加一条底部标题文字",
    )
    parser.add_argument(
        "--blur-config",
        help="可选，JSON 文件路径，定义需要局部模糊的时间和区域",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_binary("ffmpeg")
    ensure_binary("ffprobe")

    input_path = Path(args.input_file)
    if not input_path.exists():
        raise SystemExit(f"输入文件不存在: {input_path}")

    output_dir = Path(args.output_dir) if args.output_dir else None
    output_path = (
        Path(args.output)
        if args.output
        else (
            output_dir / f"processed_{input_path.stem}.mp4"
            if output_dir
            else input_path.with_name(f"processed_{input_path.stem}.mp4")
        )
    )
    srt_path = (
        Path(args.srt_output)
        if args.srt_output
        else output_path.with_suffix(".srt")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    srt_path.parent.mkdir(parents=True, exist_ok=True)

    if args.rocm_gfx_override:
        os.environ["HSA_OVERRIDE_GFX_VERSION"] = args.rocm_gfx_override
        print(f"ROCm 兼容覆盖: HSA_OVERRIDE_GFX_VERSION={args.rocm_gfx_override}")

    duration = get_duration(str(input_path))
    source_segments = transcribe(str(input_path), args.model, args.language, args.device)
    keep_ranges = merge_keep_ranges(source_segments, args.margin, duration)
    whisper_keep_seconds = sum(item.end - item.start for item in keep_ranges)
    silence_ranges: List[Range] = []
    if not args.disable_db_cut:
        silence_ranges = detect_silence_ranges(
            str(input_path), args.silence_noise, args.silence_min_duration
        )
        keep_ranges = compress_silence_in_ranges(
            keep_ranges, silence_ranges, args.silence_keep
        )
        keep_ranges = drop_short_silent_ranges(
            keep_ranges, source_segments, args.min_clip_duration
        )
    edited_segments = remap_segments(source_segments, keep_ranges)
    blur_regions = load_blur_regions(args.blur_config)

    print(f"识别到 {len(source_segments)} 个语音片段。")
    print(f"Whisper 合并后保留 {whisper_keep_seconds:.2f}s。")
    if not args.disable_db_cut:
        print(
            f"dB 检测到 {len(silence_ranges)} 段长静音，"
            f"二次压缩后保留 {sum(item.end - item.start for item in keep_ranges):.2f}s。"
        )
    print(f"最终保留 {len(keep_ranges)} 段时间区间。")
    export_video(
        str(input_path),
        str(output_path),
        keep_ranges,
        args.title_text,
        blur_regions,
    )
    final_segments = edited_segments
    if args.retranscribe_after_cut:
        print("正在对剪后视频重新转写，生成新的字幕时间轴。")
        final_segments = transcribe(str(output_path), args.model, args.language, args.device)
    write_srt(final_segments, srt_path)
    print(f"视频输出: {output_path}")
    print(f"SRT 输出: {srt_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
