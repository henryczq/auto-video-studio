#!/usr/bin/env python3
"""Persistent worker for synthesizing TTS chunks via stdin/stdout pipe."""

import json
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
WEB_BACKEND = ROOT_DIR / "web" / "backend"
if str(WEB_BACKEND) not in sys.path:
    sys.path.insert(0, str(WEB_BACKEND))


def main():
    args = json.loads(sys.argv[1])

    cosyvoice_dir = args["cosyvoice_dir"]
    model_dir = args["model_dir"]
    rocm_gfx_override = args.get("rocm_gfx_override")
    threads = args.get("threads", 4)

    if rocm_gfx_override:
        os.environ["HSA_OVERRIDE_GFX_VERSION"] = rocm_gfx_override
    os.environ["OMP_NUM_THREADS"] = str(max(1, threads))

    matcha_dir = str(Path(cosyvoice_dir) / "third_party" / "Matcha-TTS")
    if cosyvoice_dir not in sys.path:
        sys.path.insert(0, cosyvoice_dir)
    if matcha_dir not in sys.path:
        sys.path.insert(0, matcha_dir)

    from services.tts_runtime import preload_tts_model, write_synthesized_chunk
    from services.tts_models import prepare_model_inputs

    preload_tts_model(
        model_dir=model_dir,
        cosyvoice_dir=cosyvoice_dir,
        rocm_gfx_override=rocm_gfx_override,
    )

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        task = json.loads(line)

        chunk = task["chunk"]
        output = task["output"]
        prompt_text = task["prompt_text"]
        prompt_wav = task["prompt_wav"]
        speed = task["speed"]
        disable_text_frontend = task.get("disable_text_frontend", False)
        tts_mode = task["tts_mode"]
        emo_text = task.get("emo_text", "")

        chunk_text, chunk_prompt_text = prepare_model_inputs(
            str(chunk["text"]), prompt_text, tts_mode, Path(model_dir)
        )
        if tts_mode == "zero_shot":
            from services.tts_runtime import validate_zero_shot
            validate_zero_shot(str(chunk["text"]), prompt_text, strict=False)

        text_for_synth = chunk_text if tts_mode == "cross_lingual" else str(chunk["text"])

        sample_rate = write_synthesized_chunk(
            output_path=Path(output),
            text=text_for_synth,
            prompt_text=chunk_prompt_text,
            prompt_wav=prompt_wav,
            model_dir=model_dir,
            cosyvoice_dir=cosyvoice_dir,
            tts_mode=tts_mode,
            speed=speed,
            rocm_gfx_override=rocm_gfx_override,
            disable_text_frontend=disable_text_frontend,
            instruct_text=emo_text,
        )
        sys.stdout.write(json.dumps({"idx": task["idx"], "sample_rate": sample_rate}) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
