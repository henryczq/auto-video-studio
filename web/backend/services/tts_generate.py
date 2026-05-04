import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from services.tts_models import prepare_model_inputs
from services.tts_runtime import (
    preload_tts_model,
    validate_zero_shot,
    write_synthesized_chunk,
)

# Try to import BatchedTTSExecutor (CosyVoice batched inference)
BATCHED_EXECUTOR_AVAILABLE = False
try:
    # Add cosyvoice to path
    _cosyvoice_dir = str(Path(__file__).resolve().parents[3] / "core" / "third_party" / "CosyVoice")
    if _cosyvoice_dir not in sys.path:
        sys.path.insert(0, _cosyvoice_dir)
    from cosyvoice.cli.batched_tts_executor import BatchedTTSExecutor, get_batched_executor
    BATCHED_EXECUTOR_AVAILABLE = True
except ImportError:
    BatchedTTSExecutor = None
    get_batched_executor = None


DEFAULT_TTS_THREADS = max(1, int(os.environ.get("AUTO_CUT_TTS_THREADS", "4")))
DEFAULT_TTS_PARALLEL = 2
SERIAL_CHUNK_TIMEOUT = max(30, int(os.environ.get("AUTO_CUT_TTS_SERIAL_CHUNK_TIMEOUT", "1200")))


def _get_venv_python() -> Path:
    """Return the venv Python that has torch/cosyvoice installed."""
    root = Path(__file__).resolve().parents[3]
    venv_python = root / ".venv-cosyvoice-rocm" / "bin" / "python"
    if venv_python.exists():
        return venv_python
    return Path(os.environ.get("AUTO_CUT_VENV_PYTHON", str(root / ".venv-cosyvoice-rocm" / "bin" / "python")))


def write_tts_plan(chunks: list[dict[str, Any]], path: Path) -> None:
    lines = []
    for idx, chunk in enumerate(chunks, start=1):
        source_ids = chunk.get("source_ids") or []
        lines.append(
            f"{idx}\t{float(chunk['start']):.3f}\t{float(chunk['end']):.3f}\t"
            f"{','.join(map(str, source_ids))}\t{chunk['text']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_tts_plan(path: Path) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 4)
        if len(parts) < 5:
            continue
        _idx, start, end, source_ids_raw, text = parts
        source_ids = [
            int(item)
            for item in source_ids_raw.split(",")
            if item.strip().isdigit()
        ]
        chunks.append(
            {
                "start": float(start),
                "end": float(end),
                "source_ids": source_ids,
                "text": text,
            }
        )
    return chunks


def _chunk_output_path(work_dir: Path, idx: int) -> Path:
    return work_dir / f"chunk_{idx:04d}.raw.wav"


def _synthesize_single_chunk(
    idx: int,
    chunk: dict[str, Any],
    output_path: str,
    model_dir: str,
    prompt_text: str,
    prompt_wav: str,
    speed: float,
    disable_text_frontend: bool,
    tts_mode: str,
    emo_text: str,
    cosyvoice_dir: str,
    rocm_gfx_override: str | None,
    threads: int,
) -> tuple[int, str, int]:
    if rocm_gfx_override:
        os.environ["HSA_OVERRIDE_GFX_VERSION"] = rocm_gfx_override
    os.environ["OMP_NUM_THREADS"] = str(max(1, threads))

    chunk_text, chunk_prompt_text = prepare_model_inputs(
        str(chunk["text"]), prompt_text, tts_mode, Path(model_dir)
    )
    if tts_mode == "zero_shot":
        validate_zero_shot(str(chunk["text"]), prompt_text, strict=False)

    sample_rate = write_synthesized_chunk(
        output_path=Path(output_path),
        text=chunk_text if tts_mode == "cross_lingual" else str(chunk["text"]),
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
    return idx, output_path, sample_rate


def _init_tts_worker(
    model_dir: str,
    cosyvoice_dir: str,
    rocm_gfx_override: str | None,
    threads: int,
) -> None:
    if rocm_gfx_override:
        os.environ["HSA_OVERRIDE_GFX_VERSION"] = rocm_gfx_override
    os.environ["OMP_NUM_THREADS"] = str(max(1, threads))
    preload_tts_model(
        model_dir=model_dir,
        cosyvoice_dir=cosyvoice_dir,
        rocm_gfx_override=rocm_gfx_override,
    )


def _run_chunks_via_batched_executor(
    *,
    pending: list[tuple[int, dict[str, Any], Path]],
    abs_model_dir: str,
    prompt_text: str,
    abs_prompt_wav: str,
    speed: float,
    disable_text_frontend: bool,
    emo_text: str,
    abs_cosyvoice_dir: str,
    rocm_gfx_override: str | None,
    threads: int,
    timeout_seconds: int,
    batch_size: int,
    log,
) -> tuple[int, list[int]]:
    """Run chunks using BatchedTTSExecutor (single process + dynamic batching)."""
    if not BATCHED_EXECUTOR_AVAILABLE:
        raise RuntimeError("BatchedTTSExecutor not available")

    # Ensure comfyvoice path is set
    _ensure_cosyvoice_path(abs_cosyvoice_dir)

    # Prepare chunks for batched executor
    chunks_data = [
        {"text": chunk["text"], "idx": idx}
        for idx, chunk, path in pending
    ]

    try:
        # Create batched executor
        executor = get_batched_executor(
            model_dir=abs_model_dir,
            cosyvoice_dir=abs_cosyvoice_dir,
            batch_size=batch_size,
            timeout_ms=15,
            rocm_gfx_override=rocm_gfx_override,
            threads=threads,
        )

        # Run batched synthesis
        results = executor.synthesize_chunks(
            chunks=chunks_data,
            prompt_text=prompt_text,
            prompt_wav=abs_prompt_wav,
            instruct_text=emo_text,
            speed=speed,
            disable_text_frontend=disable_text_frontend,
            timeout_seconds=timeout_seconds,
        )

        # Write results to files
        sample_rate = 24000
        failed: list[int] = []
        for i, ((idx, chunk, path), (audio, sr)) in enumerate(zip(pending, results)):
            if audio is not None and len(audio) > 0:
                import soundfile as sf
                sf.write(str(path), audio, sr)
                sample_rate = sr
                log(f"  chunk {idx} done, saved: {path.name}")
            else:
                log(f"  WARNING: chunk {idx} synthesis failed")
                failed.append(idx)

        # NOTE: Do NOT stop executor - it's cached globally and reused
        return sample_rate, failed

    except Exception as exc:
        raise RuntimeError(f"BatchedTTSExecutor failed: {exc}")


def _ensure_cosyvoice_path(cosyvoice_dir: str) -> None:
    """Ensure CosyVoice path is in sys.path."""
    if cosyvoice_dir not in sys.path:
        sys.path.insert(0, cosyvoice_dir)
    matcha_dir = str(Path(cosyvoice_dir) / "third_party" / "Matcha-TTS")
    if matcha_dir not in sys.path:
        sys.path.insert(0, matcha_dir)


def _run_chunks_via_persistent_workers(
    *,
    pending: list[tuple[int, dict[str, Any], Path]],
    abs_model_dir: str,
    prompt_text: str,
    abs_prompt_wav: str,
    speed: float,
    disable_text_frontend: bool,
    tts_mode: str,
    emo_text: str,
    abs_cosyvoice_dir: str,
    rocm_gfx_override: str | None,
    threads: int,
    timeout_seconds: int,
    worker_count: int,
    log,
) -> int:
    """Run chunks using multiple persistent worker processes.

    This is the fast/high-memory mode: each worker process loads its own model copy.
    """
    venv_python = _get_venv_python()
    worker_script = Path(__file__).resolve().parents[3] / "core" / "tools" / "tts_chunk_worker.py"
    worker_count = max(1, int(worker_count or 1))

    worker_args = {
        "cosyvoice_dir": abs_cosyvoice_dir,
        "model_dir": abs_model_dir,
        "rocm_gfx_override": rocm_gfx_override,
        "threads": threads,
    }

    env = os.environ.copy()
    if rocm_gfx_override:
        env["HSA_OVERRIDE_GFX_VERSION"] = rocm_gfx_override
    env["OMP_NUM_THREADS"] = str(max(1, threads))

    pending_queue: Queue = Queue()
    result_queue: Queue = Queue()
    worker_procs: list[subprocess.Popen] = []
    stop_event = threading.Event()

    for idx, chunk, path in pending:
        pending_queue.put((idx, chunk, path))

    def worker_loop(worker_id: int) -> None:
        proc = subprocess.Popen(
            [str(venv_python), str(worker_script), json.dumps(worker_args)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        worker_procs.append(proc)

        while not stop_event.is_set():
            try:
                item = pending_queue.get(timeout=0.5)
            except Empty:
                break

            idx, chunk, path = item
            task = {
                "idx": idx,
                "chunk": chunk,
                "output": str(path.resolve()),
                "prompt_text": prompt_text,
                "prompt_wav": abs_prompt_wav,
                "speed": speed,
                "disable_text_frontend": disable_text_frontend,
                "tts_mode": tts_mode,
                "emo_text": emo_text,
            }

            try:
                proc.stdin.write(json.dumps(task, ensure_ascii=False) + "\n")
                proc.stdin.flush()
                output_line = proc.stdout.readline()
            except Exception as exc:
                result_queue.put(("error", f"worker {worker_id} failed: {exc}"))
                stop_event.set()
                break

            if not output_line:
                err = proc.stderr.read()
                result_queue.put(("error", f"worker {worker_id} died: {err}"))
                stop_event.set()
                break

            result = json.loads(output_line.strip())
            result_queue.put(("success", idx, result, path))
            pending_queue.task_done()

        if proc.poll() is None:
            try:
                proc.stdin.close()
            except Exception:
                pass
            proc.wait()

    threads_list = [
        threading.Thread(target=worker_loop, args=(i + 1,), daemon=True)
        for i in range(min(worker_count, len(pending)))
    ]
    for thread in threads_list:
        thread.start()

    sample_rate = 24000
    completed = 0
    deadline = time.time() + max(30, timeout_seconds) * len(pending)
    try:
        while completed < len(pending) and not stop_event.is_set():
            if time.time() > deadline:
                raise TimeoutError(f"worker mode timed out after {timeout_seconds}s per chunk budget")
            try:
                result = result_queue.get(timeout=0.5)
            except Empty:
                if all(not thread.is_alive() for thread in threads_list):
                    break
                continue

            if result[0] == "error":
                raise RuntimeError(result[1])

            _, idx, res, path = result
            if not res.get("ok", True):
                raise RuntimeError(f"chunk {idx} failed: {res.get('error') or res}")
            sample_rate = int(res.get("sample_rate") or sample_rate)
            log(f"  chunk {idx} done, saved: {path.name}")
            completed += 1

        if completed < len(pending):
            raise RuntimeError(f"worker mode only finished {completed}/{len(pending)} chunk(s)")
    finally:
        stop_event.set()
        for proc in worker_procs:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        for thread in threads_list:
            thread.join(timeout=2)

    return sample_rate


def _run_chunks_via_persistent_worker(
    *,
    pending: list[tuple[int, dict[str, Any], Path]],
    abs_model_dir: str,
    prompt_text: str,
    abs_prompt_wav: str,
    speed: float,
    disable_text_frontend: bool,
    tts_mode: str,
    emo_text: str,
    abs_cosyvoice_dir: str,
    rocm_gfx_override: str | None,
    threads: int,
    timeout_seconds: int,
    log,
) -> int:
    """Send all pending chunks to a single persistent worker process.
    Model is loaded once, then all chunks are synthesized sequentially.
    """
    venv_python = _get_venv_python()
    worker_script = Path(__file__).resolve().parents[3] / "core" / "tools" / "tts_chunk_worker.py"

    worker_args = {
        "cosyvoice_dir": abs_cosyvoice_dir,
        "model_dir": abs_model_dir,
        "rocm_gfx_override": rocm_gfx_override,
        "threads": threads,
    }

    env = os.environ.copy()
    if rocm_gfx_override:
        env["HSA_OVERRIDE_GFX_VERSION"] = rocm_gfx_override
    env["OMP_NUM_THREADS"] = str(max(1, threads))

    proc = subprocess.Popen(
        [str(venv_python), str(worker_script), json.dumps(worker_args)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    sample_rate = 24000
    try:
        for idx, chunk, path in pending:
            task = {
                "idx": idx,
                "chunk": chunk,
                "output": str(path.resolve()),
                "prompt_text": prompt_text,
                "prompt_wav": abs_prompt_wav,
                "speed": speed,
                "disable_text_frontend": disable_text_frontend,
                "tts_mode": tts_mode,
                "emo_text": emo_text,
            }
            proc.stdin.write(json.dumps(task, ensure_ascii=False) + "\n")
            proc.stdin.flush()

            output_line = proc.stdout.readline()
            if not output_line:
                err = proc.stderr.read()
                raise RuntimeError(f"worker process died: {err}")

            result = json.loads(output_line.strip())
            sample_rate = result.get("sample_rate", sample_rate)
            log(f"  chunk {idx} done, saved: {path.name}")

    except Exception:
        proc.kill()
        proc.wait()
        raise

    proc.stdin.close()
    proc.wait()

    if proc.returncode != 0:
        err = proc.stderr.read()
        raise RuntimeError(f"worker exited with code {proc.returncode}: {err}")

    return sample_rate


def synthesize_tts_chunks(
    *,
    chunks: list[dict[str, Any]],
    work_dir: Path,
    prompt_text: str,
    prompt_wav: Path,
    tts_mode: str,
    model_dir: Path,
    cosyvoice_dir: Path,
    speed: float,
    disable_text_frontend: bool = False,
    rocm_gfx_override: str | None = None,
    threads: int = DEFAULT_TTS_THREADS,
    parallel: int = DEFAULT_TTS_PARALLEL,
    tts_executor: str = "workers",
    emo_text: str = "",
    reuse_chunks: bool = False,
    serial_chunk_timeout: int = SERIAL_CHUNK_TIMEOUT,
    log_file: Path | None = None,
) -> tuple[list[Path], int]:
    def log(message: str) -> None:
        if not log_file:
            return
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(message + "\n")

    work_dir.mkdir(parents=True, exist_ok=True)
    raw_paths = [_chunk_output_path(work_dir, idx) for idx in range(1, len(chunks) + 1)]
    sample_rate = 24000

    if reuse_chunks:
        existing = [path.exists() for path in raw_paths]
        existing_count = sum(1 for item in existing if item)
        if existing_count:
            log(f"  reuse_chunks: found {existing_count}/{len(raw_paths)} existing raw chunks")
        if all(existing):
            log("  reuse_chunks: all raw chunks exist, skip synthesis")
            return raw_paths, sample_rate
    else:
        log("  reuse_chunks: disabled, removing existing raw chunks")
        for path in raw_paths:
            if path.exists():
                path.unlink()

    pending = [
        (idx, chunk, path)
        for idx, (chunk, path) in enumerate(zip(chunks, raw_paths, strict=True), start=1)
        if not (reuse_chunks and path.exists())
    ]
    if not pending:
        return raw_paths, sample_rate

    abs_model_dir = str(model_dir.resolve())
    abs_cosyvoice_dir = str(cosyvoice_dir.resolve())
    abs_prompt_wav = str(prompt_wav.resolve())
    serial_chunk_timeout = max(30, int(serial_chunk_timeout or SERIAL_CHUNK_TIMEOUT))
    log(f"  serial_chunk_timeout: {serial_chunk_timeout}s")
    tts_executor = (tts_executor or "workers").strip().lower()
    if tts_executor not in {"batched", "workers"}:
        log(f"WARNING: unknown tts_executor={tts_executor}, using batched")
        tts_executor = "batched"
    log(f"  tts_executor: {tts_executor}")

    batch_size = max(1, int(parallel or 1))
    can_use_batched = tts_mode == "instruct2" and BATCHED_EXECUTOR_AVAILABLE

    # BatchedTTSExecutor loads one model instance and processes multiple chunks as a batch.
    if tts_executor == "batched" and can_use_batched:
        log(f"  using BatchedTTSExecutor for {len(pending)} chunk(s), batch_size={batch_size}")
        try:
            sample_rate, failed = _run_chunks_via_batched_executor(
                pending=pending,
                abs_model_dir=abs_model_dir,
                prompt_text=prompt_text,
                abs_prompt_wav=abs_prompt_wav,
                speed=speed,
                disable_text_frontend=disable_text_frontend,
                emo_text=emo_text,
                abs_cosyvoice_dir=abs_cosyvoice_dir,
                rocm_gfx_override=rocm_gfx_override,
                threads=threads,
                timeout_seconds=serial_chunk_timeout,
                batch_size=batch_size,
                log=log,
            )
            if not failed:
                return raw_paths, sample_rate
            pending = [
                item for item in pending
                if item[0] in set(failed) or not item[2].exists()
            ]
            raise RuntimeError(
                f"BatchedTTSExecutor did not finish {len(pending)} chunk(s); "
                "increase serial_chunk_timeout or reduce batch size"
            )
        except Exception as exc:
            raise RuntimeError(f"BatchedTTSExecutor failed: {exc}") from exc

    if tts_executor == "workers" and batch_size > 1:
        log(f"  using {batch_size} persistent workers for {len(pending)} chunk(s)")
        return raw_paths, _run_chunks_via_persistent_workers(
            pending=pending,
            abs_model_dir=abs_model_dir,
            prompt_text=prompt_text,
            abs_prompt_wav=abs_prompt_wav,
            speed=speed,
            disable_text_frontend=disable_text_frontend,
            tts_mode=tts_mode,
            emo_text=emo_text,
            abs_cosyvoice_dir=abs_cosyvoice_dir,
            rocm_gfx_override=rocm_gfx_override,
            threads=threads,
            timeout_seconds=serial_chunk_timeout,
            worker_count=batch_size,
            log=log,
        )

    # Non-instruct2 modes do not support the batched executor here. Use one worker unless
    # the user explicitly selected multi-worker mode above.
    active_mode = tts_mode
    if tts_executor == "batched":
        log(f"  BatchedTTSExecutor unavailable for mode={active_mode}; using one persistent worker")
    else:
        log(f"  using one persistent worker for {len(pending)} chunk(s)")
    sample_rate = _run_chunks_via_persistent_worker(
        pending=pending,
        abs_model_dir=abs_model_dir,
        prompt_text=prompt_text,
        abs_prompt_wav=abs_prompt_wav,
        speed=speed,
        disable_text_frontend=disable_text_frontend,
        tts_mode=active_mode,
        emo_text=emo_text,
        abs_cosyvoice_dir=abs_cosyvoice_dir,
        rocm_gfx_override=rocm_gfx_override,
        threads=threads,
        timeout_seconds=serial_chunk_timeout,
        log=log,
    )

    return raw_paths, sample_rate
