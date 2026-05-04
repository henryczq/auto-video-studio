"""Open creator platform pages with authentication using playwright."""

import atexit
import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from services.social_config import get_sau_root
from services.social_accounts import get_account


# Platform creator URLs
CREATOR_URLS = {
    "douyin": "https://creator.douyin.com",
    "kuaishou": "https://cp.kuaishou.com/article/publish/video",
    "xiaohongshu": "https://creator.xiaohongshu.com",
    "bilibili": "https://member.bilibili.com",
    "weixin": "https://channels.weixin.qq.com/platform/post/create",
    "baijiahao": "https://baijiahao.baidu.com",
    "tiktok": "https://www.tiktok.com/tiktokstudio/upload?lang=en",
}

_OPEN_PROCESSES: list[subprocess.Popen] = []


def _cleanup_open_browsers() -> None:
    for process in list(_OPEN_PROCESSES):
        try:
            if process.poll() is None:
                process.terminate()
        except Exception:
            pass
    _OPEN_PROCESSES.clear()


atexit.register(_cleanup_open_browsers)


def _spawn_creator_browser(
    url: str,
    cookie_file: Path,
    domain: str,
    profile_dir: Path,
    log_file: Path,
) -> dict:
    """Start a separate local browser process so FastAPI threads never own Playwright."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    runner_code = r"""
import json, os, sys, time, traceback
from pathlib import Path
from playwright.sync_api import sync_playwright

browser_pref = sys.argv[1].lower()
url = sys.argv[2]
cookie_file = Path(sys.argv[3])
domain = sys.argv[4]
profile_dir = Path(sys.argv[5])

def load_storage_state(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("cookies"), list):
        raw_cookies = data.get("cookies") or []
        origins = data.get("origins") or []
    else:
        raw_cookies = []
        origins = []
        for name, value in data.items():
            if isinstance(value, dict):
                raw_cookies.append({"name": name, **value})
            else:
                raw_cookies.append({
                    "name": name,
                    "value": str(value),
                    "domain": domain,
                    "path": "/",
                })

    cookies = []
    for raw in raw_cookies:
        if not isinstance(raw, dict):
            continue
        name = raw.get("name")
        value = raw.get("value")
        cookie_domain = raw.get("domain") or domain
        path_value = raw.get("path") or "/"
        if not name or value is None or not cookie_domain:
            continue
        cookie = {
            "name": str(name),
            "value": str(value),
            "domain": str(cookie_domain),
            "path": str(path_value),
        }
        expires = raw.get("expires")
        if isinstance(expires, (int, float)) and expires > 0:
            cookie["expires"] = float(expires)
        if "httpOnly" in raw:
            cookie["httpOnly"] = bool(raw["httpOnly"])
        if "secure" in raw:
            cookie["secure"] = bool(raw["secure"])
        if raw.get("sameSite") in {"Strict", "Lax", "None"}:
            cookie["sameSite"] = raw["sameSite"]
        cookies.append(cookie)
    return cookies, origins

def launch_context(playwright, name):
    common = {
        "headless": False,
        "viewport": {"width": 1440, "height": 1000},
        "screen": {"width": 1440, "height": 1000},
        "device_scale_factor": 1,
        "locale": "zh-CN",
        "args": [
            "--window-size=1440,1000",
            "--force-device-scale-factor=1",
            "--disable-dev-shm-usage",
        ],
    }
    if name == "chrome":
        return playwright.chromium.launch_persistent_context(
            str(profile_dir / "chrome"),
            channel="chrome",
            chromium_sandbox=False,
            **common,
        )
    if name == "chromium":
        return playwright.chromium.launch_persistent_context(
            str(profile_dir / "chromium"),
            chromium_sandbox=False,
            **{
                **common,
                "args": common["args"] + [
                    "--disable-gpu",
                    "--disable-gpu-compositing",
                    "--disable-accelerated-2d-canvas",
                    "--disable-features=UseOzonePlatform,VizDisplayCompositor,WebRTCPipeWireCapturer",
                    "--disable-vulkan",
                    "--ozone-platform=x11",
                    "--use-gl=swiftshader",
                ],
            },
        )
    return playwright.firefox.launch_persistent_context(
        str(profile_dir / "firefox"),
        headless=False,
        viewport=common["viewport"],
        screen=common["screen"],
        device_scale_factor=1,
        locale="zh-CN",
        env={**os.environ, "MOZ_ENABLE_WAYLAND": "0"},
    )

try:
    order = [browser_pref] + [name for name in ["chrome", "chromium", "firefox"] if name != browser_pref]
    errors = []
    with sync_playwright() as playwright:
        context = None
        browser_name = None
        for name in order:
            try:
                context = launch_context(playwright, name)
                browser_name = name
                break
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        if context is None:
            raise RuntimeError(" | ".join(errors))

        cookies, origins = load_storage_state(cookie_file)
        if cookies:
            context.add_cookies(cookies)

        for origin_state in origins:
            origin = origin_state.get("origin")
            local_storage = origin_state.get("localStorage") or []
            if not origin or not local_storage:
                continue
            setup_page = context.new_page()
            try:
                setup_page.goto(origin, wait_until="domcontentloaded", timeout=30000)
                for item in local_storage:
                    key = item.get("name")
                    value = item.get("value")
                    if key is not None and value is not None:
                        setup_page.evaluate(
                            "(entry) => localStorage.setItem(entry.key, entry.value)",
                            {"key": str(key), "value": str(value)},
                        )
            except Exception:
                pass
            finally:
                setup_page.close()

        page = context.pages[0] if context.pages else context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        print(json.dumps({"status": "opened", "browser": browser_name}, ensure_ascii=False), flush=True)

        while context.pages:
            time.sleep(1)
except Exception as exc:
    print(json.dumps({
        "status": "error",
        "message": f"{type(exc).__name__}: {exc}",
        "traceback": traceback.format_exc(),
    }, ensure_ascii=False), flush=True)
    sys.exit(1)
"""

    log_handle = open(log_file, "a", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-c",
            runner_code,
            os.environ.get("AUTO_CUT_CREATOR_BROWSER", "chrome"),
            url,
            str(cookie_file),
            domain,
            str(profile_dir),
        ],
        stdout=subprocess.PIPE,
        stderr=log_handle,
        text=True,
        cwd=str(Path(__file__).parent.parent.parent.parent),
        env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
    )
    _OPEN_PROCESSES.append(process)

    deadline = time.time() + 10
    while time.time() < deadline:
        if process.poll() is not None:
            break
        if process.stdout:
            readable, _, _ = select.select([process.stdout], [], [], 0.2)
            if readable:
                line = process.stdout.readline().strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if payload.get("status") == "opened":
                    return {"browser": payload.get("browser", "chrome"), "profile_dir": str(profile_dir)}
                if payload.get("status") == "error":
                    raise RuntimeError(payload.get("message") or "浏览器启动失败")

    if process.poll() is not None:
        raise RuntimeError(f"浏览器进程异常退出: {process.returncode}，日志: {log_file}")

    return {"browser": os.environ.get("AUTO_CUT_CREATOR_BROWSER", "chrome"), "profile_dir": str(profile_dir)}


def _load_cookie_file(platform: str, account_name: str, explicit_cookie_path: str = "") -> Optional[Path]:
    """Find cookie file for account."""
    if explicit_cookie_path:
        cookie_file = Path(explicit_cookie_path).expanduser().resolve()
        if cookie_file.exists():
            return cookie_file

    sau_root = get_sau_root()
    cookies_dir = sau_root / "cookies"
    platform_dirs = {
        "weixin": "tencent_uploader",
        "baijiahao": "baijiahao_uploader",
        "tiktok": "tk_uploader",
    }

    search_dirs = [cookies_dir]
    platform_dir = platform_dirs.get(platform)
    if platform_dir:
        search_dirs.insert(0, cookies_dir / platform_dir)

    patterns = [
        f"{platform}_{account_name}.json",
        f"{platform}_{account_name}",
        f"{account_name}.json",
        account_name,
        account_name if account_name.startswith("tmp_") else None,
    ]

    for base_dir in search_dirs:
        for pattern in patterns:
            if not pattern:
                continue
            cookie_file = base_dir / pattern
            if cookie_file.exists():
                return cookie_file
            if not pattern.endswith(".json"):
                cookie_file = base_dir / f"{pattern}.json"
                if cookie_file.exists():
                    return cookie_file

    return None


def _convert_cookies_for_playwright(cookie_file: Path) -> list:
    """Convert sau cookie format to playwright format."""
    with open(cookie_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and isinstance(data.get("cookies"), list):
        source_cookies = data["cookies"]
    else:
        source_cookies = []
        for name, value in data.items():
            if isinstance(value, dict):
                source_cookies.append({"name": name, **value})
            else:
                source_cookies.append(
                    {"name": name, "value": str(value), "domain": "", "path": "/"}
                )
    
    cookies = []
    for source in source_cookies:
        if not isinstance(source, dict):
            continue
        name = source.get("name")
        value = source.get("value")
        if not name or value is None:
            continue
        cookie = {
            "name": str(name),
            "value": str(value),
            "domain": source.get("domain", ""),
            "path": source.get("path", "/") or "/",
        }
        expires = source.get("expires")
        if isinstance(expires, (int, float)) and expires > 0:
            cookie["expires"] = float(expires)
        if "httpOnly" in source:
            cookie["httpOnly"] = bool(source["httpOnly"])
        if "secure" in source:
            cookie["secure"] = bool(source["secure"])
        if source.get("sameSite") in {"Strict", "Lax", "None"}:
            cookie["sameSite"] = source["sameSite"]
        cookies.append(cookie)
    
    return cookies


def _get_domain_for_platform(platform: str) -> str:
    """Get cookie domain for platform."""
    domains = {
        "douyin": ".douyin.com",
        "kuaishou": ".kuaishou.com",
        "xiaohongshu": ".xiaohongshu.com",
        "bilibili": ".bilibili.com",
        "weixin": ".qq.com",
        "baijiahao": ".baidu.com",
        "tiktok": ".tiktok.com",
    }
    return domains.get(platform, "")


def open_creator_page(account_id: str) -> dict:
    """Open creator page in browser with authentication.
    
    Returns:
        {"status": "opened", "url": str, "account": str}
        {"status": "error", "message": str}
    """
    account = get_account(account_id)
    if not account:
        raise ValueError(f"账号不存在: {account_id}")
    
    platform = account["platform"]
    account_name = account["account"]
    
    url = CREATOR_URLS.get(platform)
    if not url:
        raise ValueError(f"平台 {platform} 不支持打开创作者后台")
    
    cookie_file = _load_cookie_file(platform, account_name, account.get("cookie_path", ""))
    if not cookie_file:
        raise ValueError(f"未找到账号 {account_name} 的登录信息，请先登录")
    
    try:
        domain = _get_domain_for_platform(platform)
        sau_root = get_sau_root()
        profile_dir = sau_root / "browser_profiles" / f"{platform}_{account_name}"
        log_file = sau_root / "logs" / "creator_browser.log"
        launch_result = _spawn_creator_browser(url, cookie_file, domain, profile_dir, log_file)
            
        return {
            "status": "opened",
            "url": url,
            "account": account_name,
            "platform": platform,
            **launch_result,
        }
            
    except Exception as exc:
        raise RuntimeError(f"打开创作者后台失败: {exc}")
