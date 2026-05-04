import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

from services.tts_models import get_llm_weights_path


def tts_manifest(
    chunks: list[dict],
    prompt_wav: Path,
    prompt_text: str,
    tts_mode: str,
    model_dir: Path,
    speed: float,
    max_speedup: float,
    segment_mode: str,
    emo_text: str = "",
    disable_text_frontend: bool = False,
    include_style_metadata: bool = True,
) -> str:
    llm_weights_path = get_llm_weights_path(model_dir)
    payload = {
        "chunks": [
            {"text": chunk["text"], "source_ids": chunk.get("source_ids") or []}
            for chunk in chunks
        ],
        "prompt_wav": str(prompt_wav.resolve()),
        "prompt_mtime": prompt_wav.stat().st_mtime if prompt_wav.exists() else None,
        "prompt_text": prompt_text if tts_mode == "zero_shot" else None,
        "tts_mode": tts_mode,
        "segment_mode": segment_mode,
        "model_dir": str(model_dir.resolve()),
        "llm_weights": str(llm_weights_path.resolve()) if llm_weights_path.exists() else None,
        "speed": speed,
        "max_speedup": max_speedup,
    }
    if include_style_metadata:
        payload["emo_text"] = emo_text if tts_mode == "instruct2" else None
        payload["disable_text_frontend"] = disable_text_frontend
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def prepare_tts_work_dir(work_dir: Path, manifest: str, compatible_manifests: list[str] | None = None) -> None:
    manifest_file = work_dir / "manifest.sha256"
    accepted = {manifest, *(compatible_manifests or [])}
    if work_dir.exists() and manifest_file.exists():
        if manifest_file.read_text(encoding="utf-8").strip() in accepted:
            manifest_file.write_text(manifest + "\n", encoding="utf-8")
            return
    if work_dir.exists():
        backup_dir = work_dir.with_name(
            f"{work_dir.name}.backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )
        shutil.move(str(work_dir), str(backup_dir))
    work_dir.mkdir(parents=True, exist_ok=True)
    manifest_file.write_text(manifest + "\n", encoding="utf-8")
