import os
from pathlib import Path


ROOT_DIR = Path(__file__).parent.parent.parent.parent
COSYVOICE_DIR = ROOT_DIR / "core" / "third_party" / "CosyVoice"
DEFAULT_TTS_MODE = os.environ.get("AUTO_CUT_TTS_MODE", "cross_lingual")
DEFAULT_TTS_MODEL_NAME = os.environ.get(
    "AUTO_CUT_TTS_MODEL", "Fun-CosyVoice3-0.5B-2512_RL"
)
COSYVOICE3_PROMPT_PREFIX = "You are a helpful assistant.<|endofprompt|>"

AVAILABLE_MODELS = [
    "CosyVoice2-0.5B",
    "Fun-CosyVoice3-0.5B-2512",
    "Fun-CosyVoice3-0.5B-2512_RL",
]


def resolve_project_path(path: str) -> Path:
    input_path = Path(path).expanduser()
    if input_path.is_absolute():
        return input_path
    return ROOT_DIR / input_path


def get_model_dir(model_name: str | None = None, model_dir: str | None = None) -> Path:
    if model_dir:
        return resolve_project_path(model_dir)
    return COSYVOICE_DIR / "pretrained_models" / (model_name or DEFAULT_TTS_MODEL_NAME)


def is_cosyvoice3_model(model_dir: Path) -> bool:
    return (model_dir / "cosyvoice3.yaml").exists() or "CosyVoice3" in model_dir.name


def infer_model_name(model_dir: Path, model_name: str | None = None) -> str:
    if model_name:
        return model_name
    return model_dir.name


def get_llm_weights_path(model_dir: Path) -> Path:
    if model_dir.name == "Fun-CosyVoice3-0.5B-2512":
        return model_dir / "llm.pt"
    rl_path = model_dir / "llm.rl.pt"
    if rl_path.exists():
        return rl_path
    return model_dir / "llm.pt"


def ensure_cosyvoice3_prompt_prefix(text: str) -> str:
    clean = text.strip()
    if not clean:
        return COSYVOICE3_PROMPT_PREFIX
    if "<|endofprompt|>" in clean:
        return clean
    return f"{COSYVOICE3_PROMPT_PREFIX}{clean}"


def prepare_model_inputs(
    text: str,
    prompt_text: str,
    tts_mode: str,
    model_dir: Path,
) -> tuple[str, str]:
    if not is_cosyvoice3_model(model_dir):
        return text, prompt_text

    if tts_mode == "cross_lingual":
        # CosyVoice3 cross_lingual expects the control prefix in the text path.
        # The tokenizer treats <|endofprompt|> as a special token rather than
        # literal spoken content.
        return ensure_cosyvoice3_prompt_prefix(text), prompt_text
    if tts_mode == "zero_shot":
        return text, ensure_cosyvoice3_prompt_prefix(prompt_text)
    return text, prompt_text
