import datetime
import subprocess
import asyncio
import shlex
import shutil

from services.process_runner import run_cmd
from services.social_accounts import get_account, update_account
from services.social_config import (
    CLI_PLATFORMS,
    get_sau_cli,
    get_sau_python,
    get_sau_root,
)
from services.social_logs import LOGS_DIR, ensure_logs_dir
from services.social_common import get_sau_cookie_path, prepare_sau_imports


def check_cli_available() -> dict:
    sau_root = get_sau_root()
    sau_python = get_sau_python()
    sau_cli = get_sau_cli()

    result = {
        "root_exists": sau_root.exists(),
        "python_exists": sau_python.exists(),
        "cli_exists": sau_cli.exists(),
        "cli_help_works": False,
        "platforms": {},
    }

    if not all([result["root_exists"], result["python_exists"], result["cli_exists"]]):
        return result

    try:
        run_cmd([str(sau_python), str(sau_cli), "--help"], check=True, timeout=10)
        result["cli_help_works"] = True
    except Exception:
        return result

    for platform in CLI_PLATFORMS:
        try:
            run_cmd([str(sau_python), str(sau_cli), platform, "--help"], check=True, timeout=10)
            result["platforms"][platform] = "available"
        except Exception:
            result["platforms"][platform] = "unavailable"

    return result


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    import re
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)


def _strict_cookie_check(platform: str, account_name: str) -> dict | None:
    cookie_path = get_sau_cookie_path(platform, account_name)
    if not cookie_path.exists():
        return {
            "status": "invalid",
            "output": "",
            "error": f"cookie文件不存在，请先完成登录: {cookie_path}",
        }

    try:
        prepare_sau_imports()
        if platform == "douyin":
            from uploader.douyin_uploader.main import douyin_setup

            result = asyncio.run(douyin_setup(str(cookie_path), handle=False, return_detail=True))
        elif platform == "kuaishou":
            from uploader.ks_uploader.main import ks_setup

            result = asyncio.run(ks_setup(str(cookie_path), handle=False, return_detail=True))
        elif platform == "xiaohongshu":
            from uploader.xiaohongshu_uploader.main import xiaohongshu_setup

            result = asyncio.run(xiaohongshu_setup(str(cookie_path), handle=False, return_detail=True))
        else:
            return None

        success = bool(result.get("success"))
        message = str(result.get("message") or "").strip()
        return {
            "status": "valid" if success else "invalid",
            "output": message if success else "",
            "error": "" if success else message,
        }
    except Exception as exc:
        return {
            "status": "error",
            "output": "",
            "error": f"严格校验失败: {exc}",
        }


def check_account_status(account_id: str) -> dict:
    account = get_account(account_id)
    if not account:
        raise ValueError(f"账号不存在: {account_id}")

    sau_root = get_sau_root()
    sau_python = get_sau_python()
    sau_cli = get_sau_cli()

    ensure_logs_dir()
    log_file = LOGS_DIR / f"{account_id}.log"
    cmd = [
        str(sau_python),
        str(sau_cli),
        account["platform"],
        "check",
        "--account",
        account["account"],
    ]

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"\n{'=' * 50}\n")
        f.write(f"[{datetime.datetime.now().isoformat()}] 检查登录状态\n")
        f.write(f"$ {' '.join(cmd)}\n\n")

    try:
        strict_result = _strict_cookie_check(account["platform"], account["account"])
        if strict_result is not None:
            output = _strip_ansi(strict_result.get("output", ""))
            error = _strip_ansi(strict_result.get("error", ""))
            status = strict_result.get("status", "unknown")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write("Mode: strict-cookie-check\n")
                f.write(f"Status: {status}\n")
                if output:
                    f.write(f"Output: {output}\n")
                if error:
                    f.write(f"Error: {error}\n")

            update_account(
                account_id,
                {
                    "last_check_status": status,
                    "last_check_at": datetime.datetime.now().isoformat(),
                    "last_error": error[:500],
                },
            )
            return {
                "status": status,
                "output": output,
                "error": error[:500],
            }

        result = run_cmd(cmd, cwd=sau_root, check=False, timeout=120)
        output = _strip_ansi(result.stdout.strip())

        stderr_clean = _strip_ansi(result.stderr) if result.stderr else ""
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"Exit code: {result.returncode}\n")
            f.write(f"Output: {output}\n")
            if stderr_clean:
                f.write(f"Error: {stderr_clean}\n")

        status = "unknown"
        if "valid" in output.lower():
            status = "valid"
        elif "invalid" in output.lower() or result.returncode != 0:
            status = "invalid"

        update_account(
            account_id,
            {
                "last_check_status": status,
                "last_check_at": datetime.datetime.now().isoformat(),
                "last_error": stderr_clean[:500],
            },
        )
        return {
            "status": status,
            "output": output,
            "error": stderr_clean[:500],
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "output": "", "error": "检查超时"}
    except Exception as exc:
        return {"status": "error", "output": "", "error": str(exc)}


def get_login_command(account_id: str, headed: bool = True) -> str:
    account = get_account(account_id)
    if not account:
        raise ValueError(f"账号不存在: {account_id}")

    sau_root = get_sau_root()
    sau_python = str(get_sau_python())
    sau_cli = str(get_sau_cli())
    platform = account["platform"]

    if platform == "bilibili":
        return " && ".join(
            [
                f"cd {shlex.quote(str(sau_root))}",
                f"{shlex.quote(sau_python)} {shlex.quote(sau_cli)} {platform} login --account {shlex.quote(account['account'])}",
            ]
        )

    cmd = f"{shlex.quote(sau_python)} {shlex.quote(sau_cli)} {platform} login --account {shlex.quote(account['account'])}"
    return cmd + (" --headed" if headed else " --headless")


def launch_login_terminal(account_id: str, headed: bool = True) -> dict:
    account = get_account(account_id)
    if not account:
        raise ValueError(f"账号不存在: {account_id}")

    sau_root = get_sau_root()
    sau_python = str(get_sau_python())
    sau_cli = str(get_sau_cli())
    platform = account["platform"]
    account_name = account["account"]

    cmd = [
        shlex.quote(sau_python),
        shlex.quote(sau_cli),
        shlex.quote(platform),
        "login",
        "--account",
        shlex.quote(account_name),
    ]
    if platform != "bilibili":
        cmd.append("--headed" if headed else "--headless")

    login_cmd = " ".join(cmd)
    script = (
        f"cd {shlex.quote(str(sau_root))}\n"
        f"echo '正在启动 {platform} 账号 {account_name} 登录...'\n"
        f"{login_cmd}\n"
        "status=$?\n"
        "echo\n"
        "if [ $status -eq 0 ]; then echo '登录命令已结束，可以回到网页点击检查账号。'; "
        "else echo \"登录命令失败，退出码: $status\"; fi\n"
        "echo '按回车关闭窗口...'\n"
        "read _\n"
    )

    terminal_candidates = [
        ("gnome-terminal", ["gnome-terminal", "--", "bash", "-lc", script]),
        ("x-terminal-emulator", ["x-terminal-emulator", "-e", "bash", "-lc", script]),
        ("konsole", ["konsole", "-e", "bash", "-lc", script]),
        ("xfce4-terminal", ["xfce4-terminal", "--command", f"bash -lc {shlex.quote(script)}"]),
        ("xterm", ["xterm", "-e", "bash", "-lc", script]),
    ]

    for terminal_name, command in terminal_candidates:
        if shutil.which(terminal_name):
            subprocess.Popen(command, cwd=sau_root)
            return {
                "status": "started",
                "terminal": terminal_name,
                "command": login_cmd,
            }

    raise RuntimeError("未找到可用终端程序，请安装 gnome-terminal 或 x-terminal-emulator")
