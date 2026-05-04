import json
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).parent.parent.parent.parent
TTS_PROFILES_PATH = ROOT_DIR / "data" / "tts_runtime_profiles.json"
DEFAULT_TTS_PROFILES = {
    "defaults": {
        "device": "rocm",
        "rocm_gfx_override": "",
        "tts_provider": "cosyvoice",
        "tts_runtime_env": "rocm6.3",
        "tts_mode": "instruct2",
        "tts_model": "Fun-CosyVoice3-0.5B-2512_RL",
        "tts_prompt_text": "",
        "tts_cosyvoice_style_text": "",
        "tts_indextts2_emo_text": "",
        "tts_threads": 4,
        "tts_parallel": 2,
        "tts_executor": "workers",
        "tts_serial_chunk_timeout": 1200,
    },
    "prompt_presets": {},
    "provider_defaults": {},
    "mode_defaults": {},
    "runtime_envs": {},
}


def load_tts_profiles() -> dict[str, Any]:
    if not TTS_PROFILES_PATH.exists():
        raise FileNotFoundError(f"TTS profiles config not found: {TTS_PROFILES_PATH}")
    with open(TTS_PROFILES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def validate_tts_profiles(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("TTS 配置必须是 JSON 对象")

    normalized = dict(DEFAULT_TTS_PROFILES)
    normalized.update(data)

    for key in ("defaults", "prompt_presets", "provider_defaults", "mode_defaults", "runtime_envs"):
        value = normalized.get(key)
        if not isinstance(value, dict):
            raise ValueError(f"`{key}` 必须是对象")

    defaults = dict(DEFAULT_TTS_PROFILES["defaults"])
    defaults.update(normalized.get("defaults") or {})
    defaults["tts_threads"] = int(defaults.get("tts_threads", 4))
    defaults["tts_parallel"] = int(defaults.get("tts_parallel", 2))
    defaults["tts_executor"] = str(defaults.get("tts_executor") or "workers")
    defaults["tts_serial_chunk_timeout"] = int(defaults.get("tts_serial_chunk_timeout", 1200))

    normalized["defaults"] = defaults
    normalized["prompt_presets"] = {
        str(k): str(v) for k, v in (normalized.get("prompt_presets") or {}).items()
    }

    runtime_envs = normalized.get("runtime_envs") or {}
    for provider, envs in runtime_envs.items():
        if not isinstance(envs, dict):
            raise ValueError(f"`runtime_envs.{provider}` 必须是对象")
        for env_name, profile in envs.items():
            if not isinstance(profile, dict):
                raise ValueError(f"`runtime_envs.{provider}.{env_name}` 必须是对象")
            python_path = str(profile.get("python") or "").strip()
            if not python_path:
                raise ValueError(f"`runtime_envs.{provider}.{env_name}.python` 不能为空")

    return normalized


def save_tts_profiles(data: dict[str, Any]) -> dict[str, Any]:
    normalized = validate_tts_profiles(data)
    TTS_PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TTS_PROFILES_PATH, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return normalized


def get_tts_defaults() -> dict[str, Any]:
    return dict(load_tts_profiles().get("defaults") or {})


def get_tts_prompt_presets() -> dict[str, str]:
    presets = load_tts_profiles().get("prompt_presets") or {}
    return {str(k): str(v) for k, v in presets.items()}


def get_runtime_envs(provider: str | None = None) -> dict[str, Any]:
    all_envs = load_tts_profiles().get("runtime_envs") or {}
    if provider:
        return dict((all_envs.get(provider) or {}))
    return dict(all_envs)


def resolve_runtime_profile(
    *,
    provider: str,
    mode: str,
    runtime_env: str | None,
    rocm_gfx_override: str | None,
) -> dict[str, Any]:
    profiles = load_tts_profiles()
    provider_defaults = ((profiles.get("provider_defaults") or {}).get(provider) or {})
    mode_defaults = (((profiles.get("mode_defaults") or {}).get(provider) or {}).get(mode) or {})
    runtime_envs = ((profiles.get("runtime_envs") or {}).get(provider) or {})

    resolved_env = (runtime_env or mode_defaults.get("runtime_env") or provider_defaults.get("runtime_env") or "").strip()
    runtime_profile = dict(runtime_envs.get(resolved_env) or {})
    resolved_gfx = rocm_gfx_override
    if isinstance(resolved_gfx, str):
        resolved_gfx = resolved_gfx.strip() or None
    if resolved_gfx is None:
        resolved_gfx = (
            mode_defaults.get("rocm_gfx_override")
            if "rocm_gfx_override" in mode_defaults
            else provider_defaults.get("rocm_gfx_override")
        )
    if resolved_gfx is None:
        resolved_gfx = runtime_profile.get("rocm_gfx_override")

    return {
        "runtime_env": resolved_env,
        "rocm_gfx_override": resolved_gfx,
        "runtime_profile": runtime_profile,
    }
