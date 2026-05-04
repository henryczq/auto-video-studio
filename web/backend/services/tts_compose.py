from pathlib import Path

from services.job_store import get_job_dir, get_logs_dir, load_job, save_job
from services.process_runner import run_cmd
from services.compose_service import (
    convert_srt_to_ass,
    get_compose_captions_path,
    get_compose_video_path,
    get_video_dimensions,
    scale_srt_timing,
    validate_playback_rate,
)


def _prepare_subtitle_filter(job_dir: Path, final_srt: Path, video_path: Path, playback_rate: float) -> str:
    if abs(playback_rate - 1.0) <= 1e-6:
        return f"subtitles={str(final_srt.resolve())}"

    srt_content = final_srt.read_text(encoding="utf-8")
    scaled_srt = scale_srt_timing(srt_content, playback_rate)
    video_width, video_height = get_video_dimensions(video_path)
    ass_content = convert_srt_to_ass(scaled_srt, video_width, video_height)
    ass_path = job_dir / "captions.tts.compose.ass"
    ass_path.write_text(ass_content, encoding="utf-8")
    return f"ass={ass_path}"


def _playback_filters(playback_rate: float) -> tuple[list[str], list[str]]:
    if abs(playback_rate - 1.0) <= 1e-6:
        return [], []
    return [f"setpts=PTS/{playback_rate:.6f}"], [f"atempo={playback_rate:.6f}"]


def compose_final_video(job_id: str, mode: str = "replace_audio", playback_rate: float = 1.0) -> str:
    job = load_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    job_dir = get_job_dir(job_id)
    log_file = get_logs_dir(job_id) / "compose.log"

    video_path, video_label = get_compose_video_path(job_id)
    if not video_path or not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_label}")
    final_srt, captions_label = get_compose_captions_path(job_id)
    if not final_srt or not final_srt.exists():
        raise FileNotFoundError(f"Captions not found: {captions_label}")

    try:
        processed = video_path
        playback_rate = validate_playback_rate(playback_rate)
        video_filters, audio_filters = _playback_filters(playback_rate)
        subtitle_filter = _prepare_subtitle_filter(job_dir, final_srt, processed, playback_rate)
        vf_filter = ",".join([*video_filters, subtitle_filter])

        if mode == "replace_audio":
            if not job.voiceover:
                raise FileNotFoundError("Voiceover not found. Please generate TTS first.")

            voiceover = Path(job.voiceover)
            output_video = job_dir / "final_replace_audio_subtitled.mp4"
            cmd = [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-i",
                str(processed),
                "-i",
                str(voiceover),
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
                "-shortest",
                str(output_video),
            ])
            run_cmd(cmd, log_file=log_file)

            job.final_replace_audio = str(output_video)
            job.compose_version = job.captions_version
            job.status = "composed_replace_audio"
            job.compose_error = None
            save_job(job)
            return job.final_replace_audio

        if mode == "subtitles_only":
            output_video = job_dir / "final_subtitles_only.mp4"

            run_cmd(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-i",
                    str(processed),
                    "-vf",
                    vf_filter,
                    *(
                        ["-af", ",".join(audio_filters), "-c:a", "aac"]
                        if audio_filters
                        else ["-c:a", "copy"]
                    ),
                    str(output_video),
                ],
                log_file=log_file,
            )

            job.final_subtitles_only = str(output_video)
            job.compose_version = job.captions_version
            job.status = "composed_subtitles_only"
            job.compose_error = None
            save_job(job)
            return job.final_subtitles_only

        raise ValueError(f"Unknown mode: {mode}")

    except Exception as exc:
        job.status = "error"
        job.compose_error = str(exc)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"ERROR: {exc}\n")
        save_job(job)
        raise
