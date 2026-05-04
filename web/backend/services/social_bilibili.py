import asyncio
import os
import pty
import re
import select
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

from services.social_common import build_temp_account_alias, get_sau_cookie_path, prepare_sau_imports
from services.social_qr import get_qr_session_meta, update_qr_session


ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
BILIBILI_LOGIN_TIMEOUT = 180
BILIBILI_LOGIN_MODES = {
    "account_password": {
        "label": "账号密码",
        "arrow_sequence": b"\x1b[A",
        "requires_credentials": True,
    },
    "sms": {
        "label": "短信登录",
        "arrow_sequence": b"",
        "requires_credentials": True,
    },
    "browser": {
        "label": "浏览器登录",
        "arrow_sequence": b"\x1b[B\x1b[B",
        "requires_credentials": False,
        "requires_cookie_fields": False,
    },
    "web_cookie1": {
        "label": "网页Cookie登录1",
        "arrow_sequence": b"\x1b[B\x1b[B\x1b[B",
        "requires_credentials": False,
        "requires_cookie_fields": True,
    },
    "web_cookie2": {
        "label": "网页Cookie登录2",
        "arrow_sequence": b"\x1b[B\x1b[B\x1b[B\x1b[B",
        "requires_credentials": False,
        "requires_cookie_fields": True,
    },
}
BILIBILI_COOKIE_NAMES = {"SESSDATA", "bili_jct"}
BILIBILI_COOKIE_HOST_PATTERNS = ("%bilibili.com", "%bilibili.cn")
BILIBILI_LOGIN_URL_RE = re.compile(r"https?://[^\s\"'<>]+")
BROWSER_COOKIE_FILES = (
    "~/.config/google-chrome/Default/Cookies",
    "~/.config/google-chrome/Profile */Cookies",
    "~/.config/chromium/Default/Cookies",
    "~/.config/chromium/Profile */Cookies",
    "~/.config/microsoft-edge/Default/Cookies",
    "~/.config/microsoft-edge/Profile */Cookies",
    "~/.config/BraveSoftware/Brave-Browser/Default/Cookies",
    "~/.config/BraveSoftware/Brave-Browser/Profile */Cookies",
)
BROWSER_EXECUTABLE_CANDIDATES = (
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/snap/bin/chromium",
    "/usr/bin/firefox",
)


def _clean_terminal_output(text: str) -> str:
    cleaned = ANSI_RE.sub("", text)
    cleaned = cleaned.replace("\r", "\n")
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    return "\n".join(lines[-30:])


def _mask_secrets(text: str, secrets: list[str]) -> str:
    masked = text
    for secret in [item for item in secrets if item]:
        masked = masked.replace(secret, "******")
        # Some terminal prompts can briefly echo a prefix or suffix of a secret.
        for length in range(min(len(secret), 12), 3, -1):
            masked = masked.replace(secret[:length], "******")
            masked = masked.replace(secret[-length:], "******")
    masked = re.sub(r"(请输入(?:密码|SESSDATA|bili_jct)\s*›\s*)\S+", r"\1******", masked)
    masked = re.sub(r"(✔\s*请输入(?:密码|SESSDATA|bili_jct)\s*·\s*)\S+", r"\1******", masked)
    return masked


def _safe_terminal_output(output_parts: list[str], secrets: list[str]) -> str:
    return _mask_secrets(_clean_terminal_output("".join(output_parts)), secrets)


def _find_browser_executable() -> str:
    for candidate in BROWSER_EXECUTABLE_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    found = shutil.which("xdg-open")
    return found or ""


def _build_desktop_env() -> dict[str, str]:
    env = os.environ.copy()
    uid = os.getuid()
    runtime_dir = env.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"
    session_bus = env.get("DBUS_SESSION_BUS_ADDRESS") or f"unix:path={runtime_dir}/bus"

    env.setdefault("DISPLAY", ":0")
    env.setdefault("XDG_RUNTIME_DIR", runtime_dir)
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", session_bus)
    if not env.get("WAYLAND_DISPLAY") and Path(runtime_dir, "wayland-0").exists():
        env["WAYLAND_DISPLAY"] = "wayland-0"
    if not env.get("XAUTHORITY") and Path.home().joinpath(".Xauthority").exists():
        env["XAUTHORITY"] = str(Path.home() / ".Xauthority")

    browser = _find_browser_executable()
    if browser:
        env.setdefault("BROWSER", browser)
    return env


def _open_url_in_browser(url: str) -> bool:
    command = []
    if shutil.which("xdg-open"):
        command = ["xdg-open", url]
    else:
        browser = _find_browser_executable()
        if browser:
            command = [browser, url]
    if not command:
        return False
    try:
        subprocess.Popen(
            command,
            env=_build_desktop_env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except Exception:
        return False


def _open_login_url_from_output(text: str, opened_urls: set[str]) -> bool:
    opened = False
    for url in BILIBILI_LOGIN_URL_RE.findall(text):
        clean_url = url.rstrip(".,;，。；)")
        if clean_url in opened_urls:
            continue
        if not any(host in clean_url for host in ("bilibili.com", "localhost", "127.0.0.1")):
            continue
        opened_urls.add(clean_url)
        opened = _open_url_in_browser(clean_url) or opened
    return opened


def _candidate_browser_cookie_files() -> list[Path]:
    cookie_files: list[Path] = []
    seen: set[str] = set()
    for pattern in BROWSER_COOKIE_FILES:
        for path in Path.home().glob(pattern.replace("~/", "")):
            if not path.is_file():
                continue
            resolved = str(path)
            if resolved in seen:
                continue
            seen.add(resolved)
            cookie_files.append(path)
    return cookie_files


def _decrypt_chrome_linux_cookie(encrypted_value: bytes) -> str:
    if not encrypted_value:
        return ""
    if not encrypted_value.startswith((b"v10", b"v11")):
        return encrypted_value.decode("utf-8", errors="ignore")

    try:
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes
    except Exception:
        return ""

    ciphertext = encrypted_value[3:]
    salt = b"saltysalt"
    iv = b" " * 16
    # Older Linux Chrome/Chromium used the hard-coded "peanuts" password when
    # no desktop keyring was available. Newer profiles often need the system
    # keyring, so this is a best-effort path rather than a guarantee.
    for password in (b"peanuts", b"Chrome Safe Storage"):
        try:
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA1(),
                length=16,
                salt=salt,
                iterations=1,
                backend=default_backend(),
            )
            key = kdf.derive(password)
            decryptor = Cipher(
                algorithms.AES(key),
                modes.CBC(iv),
                backend=default_backend(),
            ).decryptor()
            plaintext = decryptor.update(ciphertext) + decryptor.finalize()
            padding = plaintext[-1]
            if padding < 1 or padding > 16:
                continue
            plaintext = plaintext[:-padding]
            for candidate in (plaintext, plaintext[32:]):
                try:
                    value = candidate.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                if value:
                    return value
        except Exception:
            continue
    return ""


def _read_cookie_db(cookie_path: Path) -> tuple[dict[str, str], bool]:
    found: dict[str, str] = {}
    found_encrypted = False
    with tempfile.NamedTemporaryFile(prefix="bili-cookies-", suffix=".sqlite") as tmp:
        shutil.copy2(cookie_path, tmp.name)
        conn = sqlite3.connect(tmp.name)
        try:
            where_host = " OR ".join("host_key LIKE ?" for _ in BILIBILI_COOKIE_HOST_PATTERNS)
            rows = conn.execute(
                f"""
                SELECT host_key, name, value, encrypted_value, expires_utc, last_access_utc
                FROM cookies
                WHERE name IN (?, ?) AND ({where_host})
                ORDER BY last_access_utc DESC, expires_utc DESC
                """,
                (
                    "SESSDATA",
                    "bili_jct",
                    *BILIBILI_COOKIE_HOST_PATTERNS,
                ),
            ).fetchall()
        finally:
            conn.close()

    for _, name, value, encrypted_value, _, _ in rows:
        if name in found:
            continue
        cookie_value = value or ""
        if not cookie_value and encrypted_value:
            found_encrypted = True
            cookie_value = _decrypt_chrome_linux_cookie(encrypted_value)
        if cookie_value:
            found[name] = cookie_value
    return found, found_encrypted


def read_bilibili_browser_cookies() -> dict:
    cookie_files = _candidate_browser_cookie_files()
    if not cookie_files:
        return {
            "success": False,
            "message": "没有找到 Chrome/Chromium/Edge/Brave 的本地 Cookie 数据库。",
        }

    saw_bilibili_cookies = False
    decrypt_blocked_sources: list[str] = []
    errors: list[str] = []
    for cookie_path in cookie_files:
        try:
            cookies, found_encrypted = _read_cookie_db(cookie_path)
        except Exception as exc:
            errors.append(f"{cookie_path}: {exc}")
            continue

        if cookies:
            saw_bilibili_cookies = True
        if found_encrypted:
            decrypt_blocked_sources.append(str(cookie_path))
        if cookies.get("SESSDATA") and cookies.get("bili_jct"):
            return {
                "success": True,
                "sessdata": cookies["SESSDATA"],
                "bili_jct": cookies["bili_jct"],
                "source": str(cookie_path),
                "message": "已从本机浏览器读取并回填 B 站 Cookie。",
            }

    if decrypt_blocked_sources or saw_bilibili_cookies:
        return {
            "success": False,
            "message": (
                "找到了 B 站 Cookie，但浏览器把 Cookie 加密保存了，当前进程无法解密。"
                "请改用“浏览器登录”，或在浏览器开发者工具里手动复制 SESSDATA 和 bili_jct。"
            ),
            "sources": decrypt_blocked_sources,
        }

    return {
        "success": False,
        "message": "找到了浏览器 Cookie 数据库，但里面没有当前已登录的 B 站 SESSDATA/bili_jct。",
        "errors": errors[-3:],
    }


def _read_pty(master_fd: int, timeout: float = 0.2) -> str:
    chunks = []
    while True:
        ready, _, _ = select.select([master_fd], [], [], timeout)
        if not ready:
            break
        try:
            data = os.read(master_fd, 4096)
        except OSError:
            break
        if not data:
            break
        chunks.append(data.decode("utf-8", errors="replace"))
        timeout = 0
    return "".join(chunks)


def _wait_for_output(
    master_fd: int,
    proc: subprocess.Popen,
    patterns: list[str],
    deadline: float,
    output_parts: list[str],
) -> str | None:
    while time.time() < deadline:
        output = _read_pty(master_fd, timeout=0.5)
        if output:
            output_parts.append(output)
            cleaned = _clean_terminal_output("".join(output_parts))
            if any(pattern in cleaned for pattern in patterns):
                return cleaned
        if proc.poll() is not None:
            output = _read_pty(master_fd, timeout=0)
            if output:
                output_parts.append(output)
            return None
    return None


def _run_bilibili_interactive_login(
    account_name: str,
    username: str,
    password: str,
    mode: str,
    sessdata: str = "",
    bili_jct: str = "",
) -> dict:
    prepare_sau_imports()
    from uploader.bilibili_uploader.runtime import ensure_biliup_binary

    mode_config = BILIBILI_LOGIN_MODES.get(mode) or BILIBILI_LOGIN_MODES["account_password"]
    mode_label = mode_config["label"]
    secrets = [password, sessdata, bili_jct]
    account_file = get_sau_cookie_path("bilibili", account_name)
    account_file.parent.mkdir(parents=True, exist_ok=True)
    biliup_binary = ensure_biliup_binary(force_check=False)
    command = [str(biliup_binary), "-u", str(account_file), "login"]

    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        command,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=str(account_file.parent),
        env=_build_desktop_env(),
        text=False,
        close_fds=True,
    )
    os.close(slave_fd)
    output_parts: list[str] = []
    deadline = time.time() + BILIBILI_LOGIN_TIMEOUT

    try:
        selected = _wait_for_output(master_fd, proc, ["选择一种登录方式"], deadline, output_parts)
        if not selected:
            return {
                "success": False,
                "message": "B 站登录启动失败或未出现登录方式选择。",
                "terminal_output": _safe_terminal_output(output_parts, secrets),
                "account_file": str(account_file),
            }

        os.write(master_fd, mode_config["arrow_sequence"] + b"\r")
        if mode_config.get("requires_cookie_fields"):
            if not sessdata or not bili_jct:
                return {
                    "success": False,
                    "message": "网页 Cookie 登录需要填写 SESSDATA 和 bili_jct。",
                    "terminal_output": _safe_terminal_output(output_parts, secrets),
                    "account_file": str(account_file),
                    "login_mode": mode,
                }
            if not _wait_for_output(master_fd, proc, ["请输入SESSDATA"], deadline, output_parts):
                return {
                    "success": False,
                    "message": "未进入 SESSDATA 输入步骤，可能 B 站登录流程已变化。",
                    "terminal_output": _safe_terminal_output(output_parts, secrets),
                    "account_file": str(account_file),
                    "login_mode": mode,
                }
            os.write(master_fd, (sessdata + "\r").encode("utf-8"))
            if not _wait_for_output(master_fd, proc, ["请输入bili_jct"], deadline, output_parts):
                return {
                    "success": False,
                    "message": "未进入 bili_jct 输入步骤，可能 B 站登录流程已变化。",
                    "terminal_output": _safe_terminal_output(output_parts, secrets),
                    "account_file": str(account_file),
                    "login_mode": mode,
                }
            os.write(master_fd, (bili_jct + "\r").encode("utf-8"))

            while time.time() < deadline:
                output = _read_pty(master_fd, timeout=0.5)
                if output:
                    output_parts.append(output)
                if proc.poll() is not None:
                    break

            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return {
                    "success": False,
                    "message": f"B 站{mode_label}等待超时，请确认 Cookie 是否完整有效。",
                    "terminal_output": _safe_terminal_output(output_parts, secrets),
                    "account_file": str(account_file),
                    "login_mode": mode,
                }

            output = _read_pty(master_fd, timeout=0)
            if output:
                output_parts.append(output)
            terminal_output = _safe_terminal_output(output_parts, secrets)
            success = proc.returncode == 0 and account_file.exists()
            return {
                "success": success,
                "message": f"B 站{mode_label}成功" if success else (terminal_output or f"B 站{mode_label}失败"),
                "terminal_output": terminal_output,
                "account_file": str(account_file),
                "login_mode": mode,
            }

        if not mode_config["requires_credentials"]:
            opened_urls: set[str] = set()
            browser_opened = False
            while time.time() < deadline:
                output = _read_pty(master_fd, timeout=0.5)
                if output:
                    output_parts.append(output)
                    browser_opened = _open_login_url_from_output(output, opened_urls) or browser_opened
                if proc.poll() is not None:
                    break

            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return {
                    "success": False,
                    "message": (
                        f"B 站{mode_label}等待超时，请确认浏览器授权或稍后重试。"
                        if browser_opened
                        else f"B 站{mode_label}等待超时，且未捕获到可打开的登录链接；请尝试网页 Cookie 登录。"
                    ),
                    "terminal_output": _safe_terminal_output(output_parts, secrets),
                    "account_file": str(account_file),
                    "login_mode": mode,
                    "browser_opened": browser_opened,
                }

            output = _read_pty(master_fd, timeout=0)
            if output:
                output_parts.append(output)
                browser_opened = _open_login_url_from_output(output, opened_urls) or browser_opened
            terminal_output = _safe_terminal_output(output_parts, secrets)
            success = proc.returncode == 0 and account_file.exists()
            return {
                "success": success,
                "message": f"B 站{mode_label}成功" if success else (terminal_output or f"B 站{mode_label}失败"),
                "terminal_output": terminal_output,
                "account_file": str(account_file),
                "login_mode": mode,
                "browser_opened": browser_opened,
            }

        if not _wait_for_output(master_fd, proc, ["请输入账号"], deadline, output_parts):
            return {
                "success": False,
                "message": "未进入账号输入步骤，可能 B 站登录流程已变化。",
                "terminal_output": _safe_terminal_output(output_parts, secrets),
                "account_file": str(account_file),
                "login_mode": mode,
            }

        os.write(master_fd, (username + "\r").encode("utf-8"))
        if not _wait_for_output(master_fd, proc, ["请输入密码"], deadline, output_parts):
            return {
                "success": False,
                "message": "未进入密码输入步骤，可能账号格式不被接受或登录流程已变化。",
                "terminal_output": _safe_terminal_output(output_parts, secrets),
                "account_file": str(account_file),
                "login_mode": mode,
            }

        os.write(master_fd, (password + "\r").encode("utf-8"))

        while time.time() < deadline:
            output = _read_pty(master_fd, timeout=0.5)
            if output:
                output_parts.append(output)
            if proc.poll() is not None:
                break
            cleaned = _clean_terminal_output("".join(output_parts))
            if any(keyword in cleaned for keyword in ["验证码", "验证", "captcha", "短信", "二维码"]):
                try:
                    proc.terminate()
                except Exception:
                    pass
                return {
                    "success": False,
                    "requires_verification": True,
                    "message": "B 站还需要验证码、短信或二次验证，当前页面暂未接入该交互步骤。",
                    "terminal_output": _mask_secrets(cleaned, secrets),
                    "account_file": str(account_file),
                    "login_mode": mode,
                }

        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
            return {
                "success": False,
                "message": "B 站登录等待超时，请确认账号密码或稍后重试。",
                "terminal_output": _safe_terminal_output(output_parts, secrets),
                "account_file": str(account_file),
                "login_mode": mode,
            }

        output = _read_pty(master_fd, timeout=0)
        if output:
            output_parts.append(output)
        terminal_output = _safe_terminal_output(output_parts, secrets)
        success = proc.returncode == 0 and account_file.exists()
        return {
            "success": success,
            "message": "B 站账号密码登录成功" if success else (terminal_output or "B 站账号密码登录失败"),
            "terminal_output": terminal_output,
            "account_file": str(account_file),
            "login_mode": mode,
        }
    finally:
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:
            pass
        try:
            os.close(master_fd)
        except OSError:
            pass


async def login_bilibili(
    session_id: str,
    username: str,
    password: str,
    mode: str = "account_password",
    sessdata: str = "",
    bili_jct: str = "",
) -> dict:
    from services.social_bilibili_web import (
        is_bilibili_web_provider,
        login_bilibili_web_browser,
    )

    if is_bilibili_web_provider():
        if mode == "browser":
            return await login_bilibili_web_browser(session_id)
        return {
            "success": False,
            "message": "bilibili-web-upload 模式请使用“浏览器登录”保存网页投稿 Cookie。",
        }

    meta = get_qr_session_meta(session_id)
    temp_account = meta.get("temp_account") or build_temp_account_alias("bilibili")
    mode_config = BILIBILI_LOGIN_MODES.get(mode) or BILIBILI_LOGIN_MODES["account_password"]
    mode = mode if mode in BILIBILI_LOGIN_MODES else "account_password"
    update_qr_session(
        session_id,
        platform="bilibili",
        status="pending",
        temp_account=temp_account,
        current_account=temp_account,
        last_status=f"正在后台执行 B 站{mode_config['label']}...",
    )

    result = await asyncio.to_thread(
        _run_bilibili_interactive_login,
        temp_account,
        username,
        password,
        mode,
        sessdata,
        bili_jct,
    )
    result["account"] = temp_account

    if result.get("success"):
        update_qr_session(
            session_id,
            status="success",
            current_account=temp_account,
            last_message=result.get("message") or "登录成功",
            account_file=result.get("account_file"),
        )
    else:
        update_qr_session(
            session_id,
            status="error",
            current_account=temp_account,
            last_error=result.get("message") or "登录失败",
            account_file=result.get("account_file"),
            terminal_output=result.get("terminal_output"),
        )

    return result
