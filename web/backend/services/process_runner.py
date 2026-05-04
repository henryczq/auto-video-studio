import os
import shlex
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Optional


def run_cmd(
    cmd: list,
    log_file: Optional[Path] = None,
    env: Optional[dict] = None,
    cwd: Optional[Path] = None,
    check: bool = True,
    timeout: Optional[float] = None,
) -> subprocess.CompletedProcess:
    print("$", " ".join(shlex.quote(part) for part in cmd))
    command_text = "$ " + " ".join(shlex.quote(part) for part in cmd)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(command_text + "\n\n")

    run_env = os.environ.copy() if env is None else {**os.environ, **env}
    stdout_tail: deque[str] = deque(maxlen=4000)
    stderr_tail: deque[str] = deque(maxlen=4000)

    def _stream_to_log(stream, sink: deque[str], file_handle) -> None:
        try:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                sink.append(line)
                if file_handle:
                    file_handle.write(line)
        finally:
            stream.close()

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=run_env,
        cwd=cwd,
        bufsize=1,
    )
    with open(log_file, "a", encoding="utf-8") if log_file else _NullContext() as f:
        stdout_thread = threading.Thread(
            target=_stream_to_log,
            args=(process.stdout, stdout_tail, f),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_stream_to_log,
            args=(process.stderr, stderr_tail, f),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        try:
            return_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            stdout_thread.join(timeout=2)
            stderr_thread.join(timeout=2)
            exc.stdout = "".join(stdout_tail)
            exc.stderr = "".join(stderr_tail)
            if f:
                f.write("\n[timeout]\n")
                f.write("=" * 50 + "\n\n")
            raise

        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)

        stdout_text = "".join(stdout_tail)
        stderr_text = "".join(stderr_tail)
        if f:
            f.write(f"\n[exit_code] {return_code}\n")
            f.write("=" * 50 + "\n\n")

        result = subprocess.CompletedProcess(
            args=cmd,
            returncode=return_code,
            stdout=stdout_text,
            stderr=stderr_text,
        )
        if check and return_code != 0:
            raise subprocess.CalledProcessError(
                returncode=return_code,
                cmd=cmd,
                output=stdout_text,
                stderr=stderr_text,
            )
        return result


class _NullContext:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return False


def check_output_cmd(cmd: list, cwd: Optional[Path] = None) -> str:
    return subprocess.check_output(cmd, text=True, cwd=cwd).strip()
