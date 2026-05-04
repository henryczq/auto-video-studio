import json
import subprocess
from pathlib import Path
from typing import Any

from services.job_store import get_job_dir, load_job, save_job
from services.process_runner import run_cmd
from services.video_pipeline import load_captions


def merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not intervals:
        return []
    sorted_intervals = sorted(intervals, key=lambda x: x[0])
    merged = [sorted_intervals[0]]
    for start, end in sorted_intervals[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def offset_before(time_value: float, cut_segments: list[tuple[float, float]]) -> float:
    offset = 0.0
    for start, end in cut_segments:
        if end <= time_value:
            offset += end - start
        elif start < time_value:
            offset += time_value - start
    return offset


def adjust_caption_after_cuts(
    cap: dict[str, Any], cut_segments: list[tuple[float, float]]
) -> dict[str, Any] | None:
    cap_start = float(cap["start"])
    cap_end = float(cap["end"])
    if cap_end <= cap_start:
        return None

    removed_inside = 0.0
    for start, end in cut_segments:
        overlap_start = max(cap_start, start)
        overlap_end = min(cap_end, end)
        if overlap_end > overlap_start:
            removed_inside += overlap_end - overlap_start

    remaining_duration = (cap_end - cap_start) - removed_inside
    if remaining_duration <= 0.01:
        return None

    adjusted_start = cap_start - offset_before(cap_start, cut_segments)
    adjusted_end = adjusted_start + remaining_duration
    return {
        "start": adjusted_start,
        "end": adjusted_end,
        "text": cap["text"],
    }


def get_source_video_path(job_id: str) -> Path | None:
    job = load_job(job_id)
    if not job:
        return None
    job_dir = get_job_dir(job_id)
    if job.processed_video:
        return job_dir / job.processed_video
    return job_dir / "processed.mp4"


def get_source_captions(job_id: str) -> list[dict[str, Any]]:
    for stage in ["working", "final", "source"]:
        caps = load_captions(job_id, stage)
        if caps:
            return [{"start": c.start, "end": c.end, "text": c.text} for c in caps]
    return []


def preview_trim(job_id: str) -> dict[str, Any]:
    job_dir = get_job_dir(job_id)
    cut_marks_file = job_dir / "captions.cut_marks.json"
    cut_indices = []
    manual_segments = []
    if cut_marks_file.exists():
        data = json.loads(cut_marks_file.read_text(encoding="utf-8"))
        if isinstance(data, list):
            cut_indices = [item["index"] for item in data if isinstance(item, dict) and "index" in item]
            manual_segments = [
                item for item in data if isinstance(item, dict) and "start" in item and "end" in item
            ]
        elif isinstance(data, dict):
            cut_indices = data.get("cut_indices", [])
            manual_segments = data.get("manual_segments", [])

    captions = get_source_captions(job_id)
    if not captions:
        return {"error": "没有找到字幕文件"}

    video_path = get_source_video_path(job_id)
    if not video_path or not video_path.exists():
        return {"error": "没有找到视频文件"}

    try:
        result = run_cmd(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(video_path),
            ],
            check=True,
            timeout=30,
        )
        info = json.loads(result.stdout)
        duration = float(info["format"].get("duration", 0))
    except Exception:
        duration = 0

    if duration <= 0:
        return {"error": "无法读取视频时长，已停止裁剪以避免只保留前半段"}

    cut_segments = []
    for idx in cut_indices:
        if 0 <= idx < len(captions):
            cap = captions[idx]
            cut_segments.append((cap["start"], cap["end"]))
    for segment in manual_segments:
        start = float(segment.get("start", 0))
        end = float(segment.get("end", 0))
        if end > start:
            normalized_start = max(0.0, start)
            normalized_end = min(end, duration) if duration else end
            if normalized_end > normalized_start:
                cut_segments.append((normalized_start, normalized_end))

    cut_segments = merge_intervals(cut_segments)

    total_cut_duration = sum(end - start for start, end in cut_segments)
    remaining_duration = duration - total_cut_duration

    keep_segments = []
    cut_index_set = set(cut_indices)
    for idx in range(len(captions)):
        cap = captions[idx]
        if idx in cut_index_set:
            continue
        adjusted_cap = adjust_caption_after_cuts(cap, cut_segments)
        if not adjusted_cap:
            continue
        keep_segments.append(
            {
                "index": idx,
                "start": adjusted_cap["start"],
                "end": adjusted_cap["end"],
                "text": adjusted_cap["text"],
            }
        )

    return {
        "total_captions": len(captions),
        "cut_captions_count": len(cut_indices),
        "manual_cut_count": len(manual_segments),
        "duration": duration,
        "cut_duration": total_cut_duration,
        "remaining_duration": remaining_duration,
        "cut_segments": [
            {"start": s, "end": e, "duration": e - s} for s, e in cut_segments
        ],
        "cut_caption_indices": sorted(cut_indices),
        "manual_segments": manual_segments,
        "keep_captions": keep_segments,
    }


def execute_trim(job_id: str) -> dict[str, Any]:
    job_dir = get_job_dir(job_id)
    preview = preview_trim(job_id)

    if "error" in preview:
        return preview

    if not preview["cut_segments"]:
        return {"error": "没有需要裁剪的片段"}

    video_path = get_source_video_path(job_id)
    if not video_path or not video_path.exists():
        return {"error": "视频文件不存在"}

    trimmed_video = job_dir / "processed.trimmed.mp4"
    merged_video = job_dir / "processed.trimmed.merged.mp4"

    cut_segments = preview["cut_segments"]

    keep_video_segments = []
    current = 0.0
    for seg in cut_segments:
        start = max(0.0, float(seg["start"]))
        end = min(float(seg["end"]), float(preview["duration"]))
        if start > current:
            keep_video_segments.append((current, start))
        current = max(current, end)
    if current < float(preview["duration"]):
        keep_video_segments.append((current, float(preview["duration"])))

    if not keep_video_segments:
        return {"error": "裁剪范围覆盖了整个视频，没有可保留片段"}

    filter_complex = []
    inputs = []
    for _ in keep_video_segments:
        inputs.extend(["-i", str(video_path)])

    concat_parts = []
    for i, (start_time, end_time) in enumerate(keep_video_segments):
        filter_complex.append(
            f"[{i}:v]trim=start={start_time}:end={end_time},setpts=PTS-STARTPTS[{i}v];"
            f"[{i}:a]atrim=start={start_time}:end={end_time},asetpts=PTS-STARTPTS[{i}a];"
        )
        concat_parts.append(f"[{i}v][{i}a]")

    filter_str = (
        "".join(filter_complex)
        + f"{''.join(concat_parts)}concat=n={len(keep_video_segments)}:v=1:a=1[outv][outa]"
    )

    cmd = (
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
        ]
        + inputs
        + [
            "-filter_complex",
            filter_str,
            "-map",
            f"[outv]",
            "-map",
            f"[outa]",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            str(trimmed_video),
        ]
    )

    try:
        result = run_cmd(cmd, check=False, timeout=3600)
        if result.returncode != 0:
            return {"error": f"裁剪失败: {result.stderr[:500]}"}
    except subprocess.TimeoutExpired:
        return {"error": "裁剪超时"}
    except Exception as e:
        return {"error": f"裁剪异常: {str(e)}"}

    captions = get_source_captions(job_id)
    cut_segments_tuple = [(seg["start"], seg["end"]) for seg in preview["cut_segments"]]

    new_captions = []
    for idx, cap in enumerate(captions):
        if idx in set(preview["cut_caption_indices"]):
            continue
        adjusted_cap = adjust_caption_after_cuts(cap, cut_segments_tuple)
        if adjusted_cap:
            new_captions.append(adjusted_cap)

    trimmed_captions_json = job_dir / "captions.trimmed.json"
    trimmed_captions_json.write_text(
        json.dumps(new_captions, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    from services.captions import captions_to_srt

    trimmed_captions_srt = job_dir / "captions.trimmed.srt"
    trimmed_captions_srt.write_text(captions_to_srt(new_captions), encoding="utf-8")

    job = load_job(job_id)
    if job:
        job.video_trimmed = "processed.trimmed.mp4"
        job.captions_trimmed_json = "captions.trimmed.json"
        job.captions_trimmed = "captions.trimmed.srt"
        job.trim_version = job.captions_version
        job.compose_version = 0
        job.tts_version = 0
        job.status = "video_trimmed"
        save_job(job)

    invalidate_tts(job_id)

    return {
        "status": "trimmed",
        "video_path": "processed.trimmed.mp4",
        "captions_json": "captions.trimmed.json",
        "captions_srt": "captions.trimmed.srt",
        "captions_count": len(new_captions),
        "cut_count": len(preview["cut_caption_indices"]),
        "manual_cut_count": preview.get("manual_cut_count", 0),
        "duration_saved": preview["cut_duration"],
    }


def invalidate_tts(job_id: str) -> None:
    job = load_job(job_id)
    if not job:
        return
    job_dir = get_job_dir(job_id)
    fields_to_clear = [
        ("tts_segments_json", "tts.segments.json"),
        ("voiceover", "voiceover.wav"),
        ("optimized_audio", "optimized.audio.wav"),
        ("video_audio_optimized", "video.audio.optimized.mp4"),
        ("final_replace_audio", "final.replace.audio.mp4"),
        ("final_subtitles_only", "final.subtitles.only.mp4"),
        ("final_subtitles_video", "final.subtitles.video.mp4"),
    ]
    for field_name, file_name in fields_to_clear:
        file_path = job_dir / file_name
        if file_path.exists():
            try:
                file_path.unlink()
            except Exception:
                pass
        setattr(job, field_name, None)
    compose_ass = job_dir / "captions.compose.ass"
    if compose_ass.exists():
        try:
            compose_ass.unlink()
        except Exception:
            pass
    job.compose_error = None
    save_job(job)


def get_trim_result(job_id: str) -> dict[str, Any]:
    job = load_job(job_id)
    if not job:
        return {"error": "任务不存在"}

    return {
        "video_trimmed": job.video_trimmed,
        "captions_trimmed_json": job.captions_trimmed_json,
        "captions_trimmed": job.captions_trimmed,
        "status": job.status,
    }
