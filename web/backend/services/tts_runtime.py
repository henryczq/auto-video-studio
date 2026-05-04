import os
import sys
from pathlib import Path
from typing import Optional

from services.tts_models import prepare_model_inputs


_CACHED_MODEL = None
_CACHED_MODEL_KEY: tuple[str, str, str | None] | None = None


def _ensure_cosyvoice_import_path(cosyvoice_dir: str) -> None:
    matcha_dir = str(Path(cosyvoice_dir) / "third_party" / "Matcha-TTS")
    if cosyvoice_dir not in sys.path:
        sys.path.insert(0, cosyvoice_dir)
    if matcha_dir not in sys.path:
        sys.path.insert(0, matcha_dir)


def preload_tts_model(
    *,
    model_dir: str,
    cosyvoice_dir: str,
    rocm_gfx_override: Optional[str] = None,
) -> object:
    global _CACHED_MODEL, _CACHED_MODEL_KEY

    cache_key = (model_dir, cosyvoice_dir, rocm_gfx_override)
    if _CACHED_MODEL is not None and _CACHED_MODEL_KEY == cache_key:
        return _CACHED_MODEL

    if rocm_gfx_override:
        os.environ["HSA_OVERRIDE_GFX_VERSION"] = rocm_gfx_override

    _ensure_cosyvoice_import_path(cosyvoice_dir)

    from cosyvoice.cli.cosyvoice import AutoModel

    _CACHED_MODEL = AutoModel(model_dir=model_dir)
    _CACHED_MODEL_KEY = cache_key
    return _CACHED_MODEL


def validate_zero_shot(text: str, prompt_text: str, strict: bool = True) -> None:
    if not prompt_text:
        raise ValueError("zero_shot 模式必须提供参考文本 (prompt_text)")

    text_len = len(text)
    prompt_len = len(prompt_text)

    if prompt_len > 0 and text_len < 0.35 * prompt_len:
        error_msg = (
            f"[严格校验] zero_shot 模式拒绝生成：\n"
            f"  待合成文本长度: {text_len} 字\n"
            f"  参考文本长度: {prompt_len} 字\n"
            f"  比例: {text_len / prompt_len:.1%} (要求 >= 35%)\n\n"
            f"原因：当待合成文本远短于参考文本时，容易串入 prompt 内容。\n"
            f"建议：\n"
            f"  1. 改用 cross_lingual 模式（不需要参考文本）\n"
            f"  2. 或缩短参考音频/参考文本长度"
        )
        if strict:
            raise ValueError(error_msg)
        print(f"WARNING: {error_msg}")


def ensure_instruct_prompt(text: str) -> str:
    clean = (text or "").strip()
    if not clean:
        return "You are a helpful assistant.<|endofprompt|>"
    if "<|endofprompt|>" in clean:
        return clean
    return f"You are a helpful assistant. {clean}<|endofprompt|>"


def synthesize_chunk(
    text: str,
    prompt_text: str,
    prompt_wav: str,
    model_dir: str,
    cosyvoice_dir: str,
    tts_mode: str = "cross_lingual",
    speed: float = 1.0,
    rocm_gfx_override: Optional[str] = None,
    disable_text_frontend: bool = False,
    instruct_text: str = "",
) -> tuple:
    cosyvoice = preload_tts_model(
        model_dir=model_dir,
        cosyvoice_dir=cosyvoice_dir,
        rocm_gfx_override=rocm_gfx_override,
    )
    return synthesize_chunk_with_model(
        cosyvoice=cosyvoice,
        text=text,
        prompt_text=prompt_text,
        prompt_wav=prompt_wav,
        model_dir=model_dir,
        tts_mode=tts_mode,
        speed=speed,
        disable_text_frontend=disable_text_frontend,
        instruct_text=instruct_text,
    )


def synthesize_chunk_with_model(
    cosyvoice,
    text: str,
    prompt_text: str,
    prompt_wav: str,
    model_dir: str,
    tts_mode: str = "cross_lingual",
    speed: float = 1.0,
    disable_text_frontend: bool = False,
    instruct_text: str = "",
) -> tuple:
    import torch

    sample_rate = int(cosyvoice.sample_rate)
    resolved_model_dir = Path(model_dir)
    text, prompt_text = prepare_model_inputs(text, prompt_text, tts_mode, resolved_model_dir)

    pieces = []
    if tts_mode == "cross_lingual":
        for item in cosyvoice.inference_cross_lingual(
            text,
            prompt_wav,
            stream=False,
            speed=speed,
            text_frontend=not disable_text_frontend,
        ):
            pieces.append(item["tts_speech"].cpu())
    elif tts_mode == "instruct2":
        instruct_text = ensure_instruct_prompt(instruct_text)
        for item in cosyvoice.inference_instruct2(
            str(text),
            instruct_text,
            prompt_wav,
            stream=False,
            speed=speed,
            text_frontend=not disable_text_frontend,
        ):
            pieces.append(item["tts_speech"].cpu())
    else:
        validate_zero_shot(text, prompt_text, strict=False)
        for item in cosyvoice.inference_zero_shot(
            text,
            prompt_text,
            prompt_wav,
            stream=False,
            speed=speed,
            text_frontend=not disable_text_frontend,
        ):
            pieces.append(item["tts_speech"].cpu())

    speech = torch.cat(pieces, dim=1)
    return speech.squeeze(0).numpy(), sample_rate


def write_synthesized_chunk(
    output_path: Path,
    text: str,
    prompt_text: str,
    prompt_wav: str,
    model_dir: str,
    cosyvoice_dir: str,
    tts_mode: str = "cross_lingual",
    speed: float = 1.0,
    rocm_gfx_override: Optional[str] = None,
    disable_text_frontend: bool = False,
    instruct_text: str = "",
) -> int:
    import soundfile as sf

    audio, sample_rate = synthesize_chunk(
        text=text,
        prompt_text=prompt_text,
        prompt_wav=prompt_wav,
        model_dir=model_dir,
        cosyvoice_dir=cosyvoice_dir,
        tts_mode=tts_mode,
        speed=speed,
        rocm_gfx_override=rocm_gfx_override,
        disable_text_frontend=disable_text_frontend,
        instruct_text=instruct_text,
    )
    sf.write(str(output_path), audio, sample_rate)
    return sample_rate
