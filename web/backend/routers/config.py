import os
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException

from routers.auth import verify_token
from services.tts_generate import DEFAULT_TTS_PARALLEL, DEFAULT_TTS_THREADS
from services.tts import AVAILABLE_MODELS, COSYVOICE_DIR
from services.tts_profiles import get_runtime_envs, get_tts_defaults, get_tts_prompt_presets

router = APIRouter(prefix="/api/config", tags=["config"])

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large"]
INDEXTTS2_MODEL_DIR = Path(__file__).parent.parent.parent.parent / "core" / "third_party" / "index-tts" / "checkpoints"
TTS_PROVIDERS = ["cosyvoice", "indextts2"]


def get_whisper_cache_dir() -> Path:
    cache_root = os.environ.get("XDG_CACHE_HOME")
    if cache_root:
        return Path(cache_root) / "whisper"
    return Path.home() / ".cache" / "whisper"


def get_downloaded_whisper_models() -> list[str]:
    cache_dir = get_whisper_cache_dir()
    return [model for model in WHISPER_MODELS if (cache_dir / f"{model}.pt").exists()]


@router.get("")
async def get_config():
    defaults = get_tts_defaults()
    model_dirs = {
        model_name: str(COSYVOICE_DIR / "pretrained_models" / model_name)
        for model_name in AVAILABLE_MODELS
    }
    model_dirs["IndexTTS2"] = str(INDEXTTS2_MODEL_DIR)
    default_model = defaults.get("tts_model") or AVAILABLE_MODELS[-1]
    cosyvoice_envs = get_runtime_envs("cosyvoice")
    indextts2_envs = get_runtime_envs("indextts2")
    runtime_env_labels = {key: value.get("label", key) for key, value in indextts2_envs.items()}
    return {
        "defaults": {
            "device": defaults.get("device", os.environ.get("AUTO_CUT_DEFAULT_DEVICE", "rocm")),
            "rocm_gfx_override": defaults.get("rocm_gfx_override", ""),
            "tts_provider": defaults.get("tts_provider", "cosyvoice"),
            "tts_runtime_env": defaults.get("tts_runtime_env", "rocm6.3"),
            "tts_mode": defaults.get("tts_mode", "instruct2"),
            "tts_model": default_model,
            "tts_model_dir": model_dirs.get(default_model, model_dirs[AVAILABLE_MODELS[-1]]),
            "tts_prompt_text": defaults.get("tts_prompt_text", ""),
            "tts_cosyvoice_style_text": defaults.get("tts_cosyvoice_style_text", ""),
            "tts_indextts2_emo_text": defaults.get("tts_indextts2_emo_text", ""),
            "tts_threads": defaults.get("tts_threads", DEFAULT_TTS_THREADS),
            "tts_parallel": defaults.get("tts_parallel", DEFAULT_TTS_PARALLEL),
            "tts_executor": defaults.get("tts_executor", "workers"),
            "tts_serial_chunk_timeout": defaults.get("tts_serial_chunk_timeout", 1200),
        },
        "tts": {
            "providers": TTS_PROVIDERS,
            "available_models": AVAILABLE_MODELS,
            "model_dirs": model_dirs,
            "runtime_envs": runtime_env_labels,
            "runtime_envs_by_provider": {
                "cosyvoice": cosyvoice_envs,
                "indextts2": indextts2_envs,
            },
            "prompt_presets": get_tts_prompt_presets(),
        },
        "whisper": {
            "models": WHISPER_MODELS,
            "downloaded": get_downloaded_whisper_models(),
            "cache_dir": str(get_whisper_cache_dir()),
        },
        "auth": {
            "token_required": bool(os.environ.get("AUTO_CUT_TOKEN")),
        },
    }
