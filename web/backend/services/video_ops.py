from pathlib import Path


def build_video_factory_command(
    original_video: Path,
    processed_video: Path,
    initial_srt: Path,
    margin: float,
    silence_noise: str,
    silence_min_duration: float,
    silence_keep: float,
    model: str,
    device: str,
    rocm_gfx_override: str | None = None,
) -> list[str]:
    root_dir = Path(__file__).parent.parent.parent.parent
    venv_python = root_dir / ".venv-cosyvoice-rocm" / "bin" / "python"
    cmd = [
        str(venv_python),
        str(root_dir / "core" / "video" / "video_factory.py"),
        str(original_video),
        "--output",
        str(processed_video),
        "--srt-output",
        str(initial_srt),
        "--margin",
        str(margin),
        f"--silence-noise={silence_noise}",
        "--silence-min-duration",
        str(silence_min_duration),
        "--silence-keep",
        str(silence_keep),
        "--model",
        model,
        "--device",
        device,
        "--retranscribe-after-cut",
    ]
    if rocm_gfx_override:
        cmd.extend(["--rocm-gfx-override", rocm_gfx_override])
    return cmd


def build_video_factory_env(rocm_gfx_override: str | None = None) -> dict | None:
    if not rocm_gfx_override:
        return None
    return {"HSA_OVERRIDE_GFX_VERSION": rocm_gfx_override}
