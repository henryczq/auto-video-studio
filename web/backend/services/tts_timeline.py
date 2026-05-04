import shlex
from pathlib import Path

from services.process_runner import run_cmd as _run_cmd, check_output_cmd


DEFAULT_MAX_SPEEDUP = 1.10
DEFAULT_MIN_GAP_SILENCE = 0.20
DEFAULT_MAX_PAD_SECONDS = 0.15


def run_cmd(cmd: list) -> None:
    _run_cmd(cmd, check=True)


def probe_duration(path: Path) -> float:
    output = check_output_cmd(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
    )
    return float(output)


def atempo_filter(speed: float) -> str:
    if speed <= 0:
        raise ValueError("speed must be positive")
    filters = []
    remaining = speed
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.6f}")
    return ",".join(filters)


def make_silence(path: Path, duration: float, sample_rate: int = 24000) -> None:
    if duration <= 0.01:
        return
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=channel_layout=mono:sample_rate={sample_rate}",
            "-t",
            f"{duration:.3f}",
            "-c:a",
            "pcm_s16le",
            str(path),
        ]
    )


def concat_wavs(inputs: list[Path], output: Path) -> None:
    list_file = output.with_suffix(".concat.txt")
    list_file.write_text(
        "\n".join(f"file {shlex.quote(str(p.resolve()))}" for p in inputs) + "\n",
        encoding="utf-8",
    )
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c:a",
            "pcm_s16le",
            str(output),
        ]
    )


def fit_chunk_duration(
    input_path: Path, output_path: Path, max_duration: float, max_speedup: float
) -> Path:
    actual = probe_duration(input_path)
    if max_duration <= 0:
        return input_path
    ratio = actual / max_duration
    if ratio <= 1.0:
        return input_path
    if ratio <= 1.1:
        return input_path
    speed = min(max_speedup, ratio)
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-af",
            atempo_filter(speed),
            str(output_path),
        ]
    )
    return output_path


def build_audio_timeline(
    chunks: list[dict],
    chunk_paths: list[Path],
    output_audio: Path,
    sample_rate: int,
    video_duration: float,
    work_dir: Path,
    max_speedup: float = DEFAULT_MAX_SPEEDUP,
    min_gap_silence: float = DEFAULT_MIN_GAP_SILENCE,
    max_pad_seconds: float = DEFAULT_MAX_PAD_SECONDS,
    log_file: Path | None = None,
) -> None:
    timeline_inputs: list[Path] = []
    cursor = 0.0

    def log(message: str) -> None:
        if not log_file:
            return
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(message + "\n")

    for idx, (chunk, chunk_path) in enumerate(zip(chunks, chunk_paths, strict=True), start=1):
        gap = chunk["start"] - cursor
        if gap > min_gap_silence:
            silence = work_dir / f"silence_{idx:04d}.wav"
            make_silence(silence, gap, sample_rate)
            timeline_inputs.append(silence)
            log(f"  gap: insert silence={gap:.3f}s")
        elif gap > 0:
            log(f"  gap: skip tiny gap={gap:.3f}s")

        target_duration = max(0.2, chunk["end"] - chunk["start"])
        fitted = fit_chunk_duration(
            chunk_path,
            work_dir / f"chunk_{idx:04d}_fit.wav",
            target_duration,
            max_speedup,
        )
        timeline_inputs.append(fitted)
        raw_duration = probe_duration(chunk_path)
        fitted_duration = probe_duration(fitted)

        action = "keep"
        applied_ratio = 1.0
        if fitted != chunk_path and fitted_duration > 0:
            action = "speedup"
            applied_ratio = raw_duration / fitted_duration
        elif raw_duration < target_duration:
            action = "pad"
        log(
            f"  fit: raw={raw_duration:.3f}s target={target_duration:.3f}s "
            f"out={fitted_duration:.3f}s action={action} ratio={applied_ratio:.3f}"
        )
        cursor = chunk["start"] + fitted_duration

        if chunk["end"] > cursor:
            requested_pad = chunk["end"] - cursor
            pad_duration = min(requested_pad, max_pad_seconds)
            if pad_duration > 0:
                pad = work_dir / f"pad_{idx:04d}.wav"
                make_silence(pad, pad_duration, sample_rate)
                timeline_inputs.append(pad)
                cursor += pad_duration
                log(f"  pad: applied={pad_duration:.3f}s requested={requested_pad:.3f}s")

    if video_duration > cursor:
        tail = work_dir / "silence_tail.wav"
        make_silence(tail, video_duration - cursor, sample_rate)
        timeline_inputs.append(tail)

    concat_wavs(timeline_inputs, output_audio)


def replace_video_audio(video: Path, audio: Path, output_video: Path) -> None:
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video),
            "-i",
            str(audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(output_video),
        ]
    )
