#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from webapp.services.captions import read_srt
from webapp.services.process_runner import run_cmd as _run_cmd
from webapp.services.tts_chunking import DEFAULT_SEGMENT_MODE, build_tts_chunks
from webapp.services.tts_generate import (
    DEFAULT_TTS_THREADS,
    synthesize_tts_chunks,
    write_tts_plan,
)
from webapp.services.tts_timeline import (
    DEFAULT_MAX_PAD_SECONDS as TIMELINE_DEFAULT_MAX_PAD_SECONDS,
    DEFAULT_MAX_SPEEDUP as TIMELINE_DEFAULT_MAX_SPEEDUP,
    DEFAULT_MIN_GAP_SILENCE as TIMELINE_DEFAULT_MIN_GAP_SILENCE,
    build_audio_timeline,
    probe_duration,
    replace_video_audio,
)


DEFAULT_PROMPT_TEXT = (
    "各位朋友大家好，我是振振公子，今天我来演示一下利用 OpenClaw 加 Agent 飞书的机器人"
    "来帮我们管理我们的待办任务。为什么用它来管理呢？主要还是可以设置定时任务，"
    "每天上午提醒我们，最后我会演示。当然大家可以自己设置它的提醒时间，在什么时间点。"
)
DEFAULT_TTS_MODE = "cross_lingual"
DEFAULT_MODEL_DIR = "third_party/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B-2512_RL"
DEFAULT_MAX_SECONDS = 10.0
DEFAULT_MAX_SPEEDUP = TIMELINE_DEFAULT_MAX_SPEEDUP
DEFAULT_MIN_GAP_SILENCE = TIMELINE_DEFAULT_MIN_GAP_SILENCE
DEFAULT_MAX_PAD_SECONDS = TIMELINE_DEFAULT_MAX_PAD_SECONDS


def run_cmd(cmd: list[str], cwd: Path | None = None) -> None:
    _run_cmd(cmd, cwd=cwd, check=True)


def load_prompt_text(args: argparse.Namespace) -> str:
    if args.prompt_text_file:
        return Path(args.prompt_text_file).read_text(encoding="utf-8").strip()
    default_prompt_file = Path("config/cosyvoice_prompt_text.txt")
    if default_prompt_file.exists():
        return default_prompt_file.read_text(encoding="utf-8").strip()
    if args.prompt_text:
        return args.prompt_text.strip()
    return DEFAULT_PROMPT_TEXT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="用 CosyVoice 根据 SRT 生成克隆旁白，并替换视频音轨。")
    parser.add_argument("--video", required=True, help="剪辑后的视频文件")
    parser.add_argument("--srt", required=True, help="校对后的 SRT 字幕文件")
    parser.add_argument("--prompt-wav", default="videos/output/voice_reference_clean_26s.wav", help="你的参考音频")
    parser.add_argument("--prompt-text", help="参考音频对应的文字")
    parser.add_argument("--prompt-text-file", help="参考音频对应文字的文件")
    parser.add_argument("--cosyvoice-dir", default="third_party/CosyVoice", help="CosyVoice 仓库目录")
    parser.add_argument("--tts-mode", choices=["cross_lingual", "zero_shot"], default=DEFAULT_TTS_MODE, help="TTS 模式")
    parser.add_argument("--segment-mode", choices=["ai", "rule"], default=DEFAULT_SEGMENT_MODE, help="TTS 分段模式")
    parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR, help="CosyVoice 模型目录")
    parser.add_argument("--output-audio", help="输出旁白 wav，默认跟 SRT 同名")
    parser.add_argument("--output-video", help="输出替换音轨后的视频，默认跟视频同名加 _cosyvoice")
    parser.add_argument("--work-dir", help="中间分段音频目录")
    parser.add_argument("--max-chars", type=int, default=90, help="每个 TTS 分块最多字数")
    parser.add_argument("--max-seconds", type=float, default=DEFAULT_MAX_SECONDS, help="每个 TTS 分块最多覆盖秒数")
    parser.add_argument("--max-gap", type=float, default=1.5, help="字幕间隔超过多少秒时断块")
    parser.add_argument("--speed", type=float, default=1.0, help="CosyVoice 语速参数")
    parser.add_argument("--max-speedup", type=float, default=DEFAULT_MAX_SPEEDUP, help="生成音频超长时最多加速倍数")
    parser.add_argument("--min-gap-silence", type=float, default=DEFAULT_MIN_GAP_SILENCE, help="小于该值的 chunk 间隔不插静音")
    parser.add_argument("--max-pad-seconds", type=float, default=DEFAULT_MAX_PAD_SECONDS, help="每段结尾最多补多少秒静音")
    parser.add_argument("--threads", type=int, default=DEFAULT_TTS_THREADS, help="每个 TTS 进程使用的 CPU 线程数")
    parser.add_argument("--parallel", type=int, default=1, help="并行生成 N 个分块，需要足够内存")
    parser.add_argument("--rocm-gfx-override", help="可选，设置 HSA_OVERRIDE_GFX_VERSION，例如 11.0.0")
    parser.add_argument("--disable-text-frontend", action="store_true", help="关闭 CosyVoice 文本前端")
    parser.add_argument("--reuse-chunks", action="store_true", help="复用已生成的 chunk_*.wav")
    parser.add_argument("--limit-chunks", type=int, help="只生成前 N 个分块，适合测试")
    parser.add_argument("--plan-only", action="store_true", help="只生成分块计划，不跑 CosyVoice")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    video = Path(args.video)
    srt = Path(args.srt)
    if not video.exists():
        raise SystemExit(f"视频不存在: {video}")
    if not srt.exists():
        raise SystemExit(f"SRT 不存在: {srt}")
    if not Path(args.prompt_wav).exists():
        raise SystemExit(f"参考音频不存在: {args.prompt_wav}")

    output_audio = Path(args.output_audio) if args.output_audio else srt.with_name(f"{srt.stem}_cosyvoice.wav")
    output_video = Path(args.output_video) if args.output_video else video.with_name(f"{video.stem}_cosyvoice.mp4")
    work_dir = Path(args.work_dir) if args.work_dir else output_audio.with_suffix("")
    work_dir.mkdir(parents=True, exist_ok=True)

    captions = read_srt(srt)
    if not captions:
        raise SystemExit(f"没有从 SRT 里读到字幕: {srt}")
    tts_chunks, segment_mode_used = build_tts_chunks(
        captions,
        segment_mode=args.segment_mode,
        max_chars=args.max_chars,
        max_seconds=args.max_seconds,
        max_gap=args.max_gap,
    )
    chunks = [
        {
            "start": item.start,
            "end": item.end,
            "text": item.text,
            "source_ids": item.source_ids,
        }
        for item in tts_chunks
    ]
    if args.limit_chunks is not None:
        chunks = chunks[: args.limit_chunks]
    write_tts_plan(chunks, work_dir / "chunks.tsv")
    print(
        f"字幕 {len(captions)} 条，合并为 {len(chunks)} 个 TTS 分块 "
        f"(segment_mode={args.segment_mode}, used={segment_mode_used}): {work_dir / 'chunks.tsv'}"
    )
    if args.plan_only:
        return 0

    chunk_paths, sample_rate = synthesize_tts_chunks(
        chunks=chunks,
        work_dir=work_dir,
        prompt_text=load_prompt_text(args),
        prompt_wav=Path(args.prompt_wav),
        tts_mode=args.tts_mode,
        model_dir=Path(args.model_dir),
        cosyvoice_dir=Path(args.cosyvoice_dir),
        speed=args.speed,
        disable_text_frontend=args.disable_text_frontend,
        rocm_gfx_override=args.rocm_gfx_override,
        threads=args.threads,
        parallel=args.parallel,
        reuse_chunks=args.reuse_chunks,
    )
    video_duration = probe_duration(video)
    build_audio_timeline(
        chunks=[
            {"start": chunk.start, "end": chunk.end, "text": chunk.text, "source_ids": chunk.source_ids}
            for chunk in chunks
        ],
        chunk_paths=chunk_paths,
        output_audio=output_audio,
        sample_rate=sample_rate,
        video_duration=video_duration,
        work_dir=work_dir,
        max_speedup=args.max_speedup,
        min_gap_silence=args.min_gap_silence,
        max_pad_seconds=args.max_pad_seconds,
    )
    replace_video_audio(video, output_audio, output_video)
    print(f"旁白输出: {output_audio}")
    print(f"视频输出: {output_video}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
