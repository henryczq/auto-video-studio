#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from webapp.services.captions import read_srt
from webapp.services.tts_chunking import DEFAULT_SEGMENT_MODE, build_tts_chunks
from webapp.services.tts_generate import write_tts_plan
from webapp.services.tts_timeline import (
    DEFAULT_MAX_PAD_SECONDS,
    DEFAULT_MAX_SPEEDUP,
    DEFAULT_MIN_GAP_SILENCE,
    build_audio_timeline,
    probe_duration,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate voiceover with IndexTTS2 from SRT.")
    parser.add_argument("--video", required=True)
    parser.add_argument("--srt", required=True)
    parser.add_argument("--prompt-wav", required=True)
    parser.add_argument("--output-audio", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--model-dir", default="third_party/index-tts/checkpoints")
    parser.add_argument("--segment-mode", choices=["ai", "rule"], default=DEFAULT_SEGMENT_MODE)
    parser.add_argument("--max-speedup", type=float, default=DEFAULT_MAX_SPEEDUP)
    parser.add_argument("--min-gap-silence", type=float, default=DEFAULT_MIN_GAP_SILENCE)
    parser.add_argument("--max-pad-seconds", type=float, default=DEFAULT_MAX_PAD_SECONDS)
    parser.add_argument("--emo-text", default="")
    parser.add_argument("--emo-alpha", type=float, default=0.6)
    parser.add_argument("--reuse-chunks", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    video = Path(args.video)
    srt = Path(args.srt)
    prompt_wav = Path(args.prompt_wav)
    output_audio = Path(args.output_audio)
    work_dir = Path(args.work_dir)
    model_dir = Path(args.model_dir)

    if not video.exists():
        raise SystemExit(f"video not found: {video}")
    if not srt.exists():
        raise SystemExit(f"srt not found: {srt}")
    if not prompt_wav.exists():
        raise SystemExit(f"prompt wav not found: {prompt_wav}")
    if not model_dir.exists():
        raise SystemExit(f"model dir not found: {model_dir}")

    sys.path.insert(0, str((Path(__file__).resolve().parent.parent / "third_party" / "index-tts").resolve()))
    from indextts.infer_v2 import IndexTTS2

    captions = read_srt(srt)
    if not captions:
        raise SystemExit(f"no captions from srt: {srt}")

    tts_chunks, segment_mode_used = build_tts_chunks(captions, segment_mode=args.segment_mode)
    chunks = [
        {
            "start": item.start,
            "end": item.end,
            "text": item.text,
            "source_ids": item.source_ids,
        }
        for item in tts_chunks
    ]

    work_dir.mkdir(parents=True, exist_ok=True)
    write_tts_plan(chunks, work_dir / "chunks.tsv")
    print(
        f"captions={len(captions)} chunks={len(chunks)} "
        f"segment_mode={args.segment_mode} used={segment_mode_used}"
    , flush=True)

    tts = IndexTTS2(
        cfg_path=str((model_dir / "config.yaml").resolve()),
        model_dir=str(model_dir.resolve()),
        use_fp16=False,
        use_cuda_kernel=False,
        use_deepspeed=False,
    )

    chunk_paths: list[Path] = []
    sample_rate = 22050
    for idx, chunk in enumerate(chunks, start=1):
        output_path = work_dir / f"chunk_{idx:04d}.raw.wav"
        if args.reuse_chunks and output_path.exists():
            chunk_paths.append(output_path)
            print(f"[Chunk {idx}/{len(chunks)}] reuse: {output_path}", flush=True)
            continue
        print(
            f"[Chunk {idx}/{len(chunks)}] ids={chunk.get('source_ids') or []} {chunk['text'][:60]}...",
            flush=True,
        )
        kwargs = {
            "spk_audio_prompt": str(prompt_wav.resolve()),
            "text": str(chunk["text"]),
            "output_path": None,
            "verbose": True,
        }
        if args.emo_text.strip():
            kwargs["use_emo_text"] = True
            kwargs["emo_text"] = args.emo_text.strip()
            kwargs["emo_alpha"] = args.emo_alpha
        result = tts.infer(**kwargs)
        sample_rate, wav = result
        sf.write(str(output_path), wav, sample_rate)
        chunk_paths.append(output_path)
        print(f"  saved: {output_path}", flush=True)

    build_audio_timeline(
        chunks=chunks,
        chunk_paths=chunk_paths,
        output_audio=output_audio,
        sample_rate=sample_rate,
        video_duration=probe_duration(video),
        work_dir=work_dir,
        max_speedup=args.max_speedup,
        min_gap_silence=args.min_gap_silence,
        max_pad_seconds=args.max_pad_seconds,
    )
    print(f"voiceover: {output_audio}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
