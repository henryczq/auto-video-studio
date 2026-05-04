"""AI 封面图生成服务 - 支持 Gemini 和 ChatGPT，使用用户已登录的 Chrome profile"""

import json
import logging
import os
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from services.job_store import get_job_dir
from services.social_ai_cover_prompt import build_ai_cover_prompt
from services.publish_drafts import save_publish_draft

logger = logging.getLogger(__name__)

# 用户 Chrome profile 路径
CHROME_PROFILE_PATH = Path.home() / ".config" / "google-chrome" / "Default"

# 下载目录
AI_COVER_DOWNLOAD_DIR = Path.home() / "Downloads"


_build_prompt = build_ai_cover_prompt


def _convert_and_save_image(src_path: Path, dest_path: Path) -> bool:
    """转换并保存图片为 JPEG 格式"""
    try:
        from PIL import Image

        with Image.open(src_path) as img:
            if img.mode in ("RGBA", "P", "LA"):
                background = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "RGBA":
                    background.paste(img, mask=img.split()[3])
                else:
                    background.paste(img.convert("RGBA"))
                img = background
            elif img.mode != "RGB":
                img = img.convert("RGB")

            img.save(dest_path, "JPEG", quality=92, optimize=True)
        return True
    except Exception as exc:
        logger.error(f"图片转换失败: {exc}")
        shutil.copy2(src_path, dest_path)
        return True


def _wait_for_download(
    download_dir: Path, timeout: float = 180, min_size: int = 5000
) -> list[Path]:
    """等待下载完成，返回下载的文件路径列表"""
    start_time = time.time()
    last_sizes: dict[str, int] = {}
    completed_files: list[Path] = []

    while time.time() - start_time < timeout:
        for f in download_dir.iterdir():
            if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                try:
                    size = f.stat().st_size
                    key = str(f)
                    if size > min_size and size == last_sizes.get(key):
                        if f not in completed_files:
                            completed_files.append(f)
                    last_sizes[key] = size
                except OSError:
                    continue
            elif f.suffix == ".crdownload":
                try:
                    last_sizes[str(f)] = f.stat().st_size
                except OSError:
                    continue

        if len(completed_files) >= 2:
            break

        time.sleep(0.5)

    # 超时后检查是否有任何完成的文件
    if len(completed_files) < 2:
        for f in download_dir.iterdir():
            if (
                f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
                and f not in completed_files
            ):
                try:
                    if f.stat().st_size > min_size:
                        completed_files.append(f)
                except OSError:
                    continue

    return completed_files[:2]


def _execute_browser_script(
    script: str, args: list[str], job_id: str, platform: str
) -> dict:
    """执行浏览器脚本的通用方法"""
    log_dir = Path.home() / ".auto-video-studio" / "logs" / "ai_cover"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{job_id}_{platform}_{int(time.time())}.log"

    log_handle = open(log_file, "a", encoding="utf-8")
    log_handle.write(f"\n{'=' * 50}\n")
    log_handle.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {platform} AI Cover\n")
    log_handle.write(f"Args: {args}\n")
    log_handle.flush()

    env = os.environ.copy()
    env["DISPLAY"] = env.get("DISPLAY", ":0")

    process = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-c",
            script,
            *args,
        ],
        stdout=subprocess.PIPE,
        stderr=log_handle,
        text=True,
        cwd=str(Path(__file__).parent.parent.parent.parent),
        env=env,
    )

    deadline = time.time() + 600  # 10 分钟超时（用于等待登录）
    downloaded_files: list[str] = []
    login_detected = False

    try:
        while time.time() < deadline:
            if process.poll() is not None:
                break

            if process.stdout:
                readable, _, _ = select.select([process.stdout], [], [], 0.5)
                if readable:
                    line = process.stdout.readline().strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                        status = payload.get("status")
                        msg = payload.get("message", "")

                        if status == "completed":
                            downloaded_files = payload.get("downloaded_files", [])
                            log_handle.write(f"Completed: {downloaded_files}\n")
                            log_handle.flush()
                            break
                        elif status == "error":
                            error_msg = payload.get("message", "未知错误")
                            log_handle.write(f"Error: {error_msg}\n")
                            log_handle.flush()
                            raise RuntimeError(error_msg)
                        elif status == "downloading":
                            log_handle.write(f"Progress: {payload.get('count', 0)} images\n")
                            log_handle.flush()
                        elif status == "need_login":
                            log_handle.write(f"Need login: {msg}\n")
                            log_handle.flush()
                            login_detected = True
                        elif status == "logged_in":
                            log_handle.write(f"Login detected: {msg}\n")
                            log_handle.flush()
                            login_detected = False
                        else:
                            log_handle.write(f"Status: {status} - {msg}\n")
                            log_handle.flush()
                    except json.JSONDecodeError:
                        continue

            # 如果检测到需要登录，延长等待时间
            if login_detected:
                deadline = time.time() + 600  # 再等 10 分钟

    finally:
        log_handle.write(f"Exiting loop, downloaded_files: {downloaded_files}\n")
        log_handle.flush()

    return {
        "success": len(downloaded_files) >= 1,
        "downloaded_files": [Path(f) for f in downloaded_files],
        "log_file": str(log_file),
        "login_detected": login_detected,
    }


def _get_gemini_script() -> str:
    """获取 Gemini 自动化脚本 - 使用临时 profile"""
    return r"""
import json, os, sys, time, traceback
from pathlib import Path
from playwright.sync_api import sync_playwright

def click_element(page, selectors, timeout=30000):
    for selector in selectors:
        try:
            elem = page.locator(selector)
            if elem.count() > 0:
                elem.first.click(timeout=timeout)
                return True
        except Exception:
            continue
    raise TimeoutError("Cannot click element: " + str(selectors))

def fill_input(page, selectors, text, timeout=30000):
    for selector in selectors:
        try:
            elem = page.locator(selector)
            if elem.count() > 0:
                elem.first.clear()
                elem.first.fill(text, timeout=timeout)
                return True
        except Exception:
            continue
    raise TimeoutError("Cannot fill input: " + str(selectors))

try:
    download_dir = Path(sys.argv[1])
    prompt_text = sys.argv[2]

    download_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        # 使用普通浏览器模式
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        page = context.new_page()

        # 打开 Gemini
        print(json.dumps({"status": "opening_url"}, ensure_ascii=False), flush=True)
        page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)

        # 等待用户登录
        print(json.dumps({"status": "waiting_login", "message": "Please login to Gemini in the browser"}, ensure_ascii=False), flush=True)

        logged_in = False
        start_time = time.time()
        login_timeout = 300  # 5 分钟等待登录

        while time.time() - start_time < login_timeout:
            try:
                # 检查是否已登录（出现输入框）
                if page.locator('textarea[placeholder*="与 Gemini"]').count() > 0 or \
                   page.locator('textarea[aria-label*="Gemini"]').count() > 0:
                    logged_in = True
                    print(json.dumps({"status": "logged_in"}, ensure_ascii=False), flush=True)
                    break
            except Exception:
                pass
            page.wait_for_timeout(2)

        if not logged_in:
            print(json.dumps({"status": "login_wait_done"}, ensure_ascii=False), flush=True)
            page.wait_for_timeout(1000)

        # 点击"制作图片"按钮
        print(json.dumps({"status": "clicking_create_image"}, ensure_ascii=False), flush=True)
        create_image_selectors = [
            'button:has-text("制作图片")',
            'div.card-label',
            '[class*="create"]',
        ]
        try:
            click_element(page, create_image_selectors)
        except Exception:
            # 如果找不到按钮，可能在侧边栏
            print(json.dumps({"status": "try_sidebar"}, ensure_ascii=False), flush=True)
            try:
                sidebar_selectors = ['[class*="sidebar"] button', '[class*="nav"] button']
                click_element(page, sidebar_selectors)
            except Exception:
                pass

        page.wait_for_timeout(2000)

        # 输入提示词
        print(json.dumps({"status": "filling_prompt"}, ensure_ascii=False), flush=True)
        input_selectors = [
            'textarea[placeholder*="与 Gemini"]',
            'textarea[aria-label*="Gemini"]',
            'textarea',
            'div[contenteditable="true"]',
        ]
        try:
            fill_input(page, input_selectors, prompt_text)
        except Exception as e:
            print(json.dumps({"status": "fill_error", "message": str(e)}, ensure_ascii=False), flush=True)

        page.wait_for_timeout(500)

        # 点击发送
        print(json.dumps({"status": "clicking_send"}, ensure_ascii=False), flush=True)
        send_selectors = [
            'button[type="submit"]',
            'button:has-text("发送")',
            'button:has-text("Submit")',
        ]
        try:
            click_element(page, send_selectors)
        except Exception:
            pass

        # 等待图片生成
        print(json.dumps({"status": "waiting_for_images"}, ensure_ascii=False), flush=True)
        max_wait = 120
        start_time = time.time()
        downloaded_files = []

        while time.time() - start_time < max_wait:
            for f in download_dir.iterdir():
                if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                    try:
                        size = f.stat().st_size
                        if size > 5000:
                            downloaded_files.append(str(f))
                            print(json.dumps({"status": "downloading", "count": len(downloaded_files)}, ensure_ascii=False), flush=True)
                    except OSError:
                        pass
            if len(downloaded_files) >= 2:
                break
            page.wait_for_timeout(2)

        print(json.dumps({
            "status": "completed",
            "downloaded_files": downloaded_files[:2],
        }, ensure_ascii=False), flush=True)

        # 保持浏览器打开
        print(json.dumps({"status": "done", "message": "Browser will stay open"}, ensure_ascii=False), flush=True)
        while True:
            page.wait_for_timeout(10)

except Exception as exc:
    print(json.dumps({
        "status": "error",
        "message": f"{type(exc).__name__}: {exc}",
        "traceback": traceback.format_exc(),
    }, ensure_ascii=False), flush=True)
    sys.exit(1)
"""


def _get_chatgpt_script() -> str:
    """获取 ChatGPT 自动化脚本 - 使用临时 profile"""
    return r"""
import json, os, sys, time, traceback
from pathlib import Path
from playwright.sync_api import sync_playwright

def click_element(page, selectors, timeout=30000):
    for selector in selectors:
        try:
            elem = page.locator(selector)
            if elem.count() > 0:
                elem.first.click(timeout=timeout)
                return True
        except Exception:
            continue
    raise TimeoutError("Cannot click element: " + str(selectors))

def fill_input(page, selectors, text, timeout=30000):
    for selector in selectors:
        try:
            elem = page.locator(selector)
            if elem.count() > 0:
                elem.first.clear()
                elem.first.fill(text, timeout=timeout)
                return True
        except Exception:
            continue
    raise TimeoutError("Cannot fill input: " + str(selectors))

try:
    download_dir = Path(sys.argv[1])
    prompt_text = sys.argv[2]

    download_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        # 使用普通浏览器模式
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        page = context.new_page()

        # 打开 ChatGPT
        print(json.dumps({"status": "opening_chatgpt"}, ensure_ascii=False), flush=True)
        page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)

        # 等待用户登录
        print(json.dumps({"status": "waiting_login", "message": "Please login to ChatGPT in the browser"}, ensure_ascii=False), flush=True)

        logged_in = False
        start_time = time.time()
        login_timeout = 300  # 5 分钟等待登录

        while time.time() - start_time < login_timeout:
            try:
                # 检查是否已登录（出现输入框）
                if page.locator('div.ProseMirror').count() > 0 or \
                   page.locator('textarea').count() > 0:
                    logged_in = True
                    print(json.dumps({"status": "logged_in"}, ensure_ascii=False), flush=True)
                    break
            except Exception:
                pass
            page.wait_for_timeout(2)

        if not logged_in:
            print(json.dumps({"status": "login_wait_done"}, ensure_ascii=False), flush=True)
            page.wait_for_timeout(1000)

        # 选择图片生成模式
        print(json.dumps({"status": "selecting_image_mode"}, ensure_ascii=False), flush=True)
        mode_selectors = [
            'button:has-text("生成图片")',
            'span:has-text("生成图片")',
            '[data-testid="image-mode"]',
        ]
        try:
            click_element(page, mode_selectors)
        except Exception:
            print(json.dumps({"status": "mode_select_error"}, ensure_ascii=False), flush=True)

        page.wait_for_timeout(1000)

        # 输入提示词
        print(json.dumps({"status": "filling_prompt"}, ensure_ascii=False), flush=True)
        input_selectors = [
            'div.ProseMirror',
            'textarea',
            'textarea#prompt-textarea',
        ]
        try:
            fill_input(page, input_selectors, prompt_text)
        except Exception as e:
            print(json.dumps({"status": "fill_error", "message": str(e)}, ensure_ascii=False), flush=True)

        page.wait_for_timeout(500)

        # 点击生成按钮
        print(json.dumps({"status": "clicking_generate"}, ensure_ascii=False), flush=True)
        generate_selectors = [
            'button[type="submit"]',
            'button[id*="submit"]',
            'button[aria-label*="send"]',
        ]
        try:
            click_element(page, generate_selectors)
        except Exception:
            pass

        # 等待图片生成
        print(json.dumps({"status": "waiting_for_images"}, ensure_ascii=False), flush=True)
        max_wait = 120
        start_time = time.time()
        downloaded_files = []

        while time.time() - start_time < max_wait:
            for f in download_dir.iterdir():
                if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                    try:
                        size = f.stat().st_size
                        if size > 5000:
                            downloaded_files.append(str(f))
                            print(json.dumps({"status": "downloading", "count": len(downloaded_files)}, ensure_ascii=False), flush=True)
                    except OSError:
                        pass
            if len(downloaded_files) >= 2:
                break
            page.wait_for_timeout(2)

        print(json.dumps({
            "status": "completed",
            "downloaded_files": downloaded_files[:2],
        }, ensure_ascii=False), flush=True)

        # 保持浏览器打开
        print(json.dumps({"status": "done", "message": "Browser will stay open"}, ensure_ascii=False), flush=True)
        while True:
            page.wait_for_timeout(10)

except Exception as exc:
    print(json.dumps({
        "status": "error",
        "message": f"{type(exc).__name__}: {exc}",
        "traceback": traceback.format_exc(),
    }, ensure_ascii=False), flush=True)
    sys.exit(1)
"""


def _generate_with_platform(
    job_id: str,
    platform: str,
    prompt: str,
    output_dir: Path,
) -> list[str]:
    """使用指定平台生成图片"""
    output_dir.mkdir(parents=True, exist_ok=True)
    download_dir = output_dir / f"{platform}_downloads"
    download_dir.mkdir(parents=True, exist_ok=True)

    # 清理旧下载文件
    for f in download_dir.iterdir():
        if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            try:
                f.unlink()
            except OSError:
                pass

    script = _get_gemini_script() if platform == "gemini" else _get_chatgpt_script()

    result = _execute_browser_script(
        script=script,
        args=[str(download_dir), prompt],
        job_id=job_id,
        platform=platform,
    )

    if not result.get("success"):
        if result.get("login_detected"):
            raise RuntimeError(f"{platform} 需要登录，请先在浏览器中登录后再试")
        raise RuntimeError(f"{platform} 生成失败")

    # 移动下载的图片到输出目录
    saved_files: list[str] = []
    for i, src_path in enumerate(result.get("downloaded_files", [])):
        if src_path and src_path.exists():
            dest_name = f"ai_cover_{platform}_{i + 1}.jpg"
            dest_path = output_dir / dest_name
            if _convert_and_save_image(src_path, dest_path):
                saved_files.append(dest_name)
                logger.info(f"[AI Cover] Saved {dest_name}")

    return saved_files


def generate_ai_cover(
    job_id: str,
    title: str,
    description: str = "",
    platforms: Optional[list[str]] = None,
) -> dict:
    """
    AI 封面图生成主入口

    Args:
        job_id: 任务 ID
        title: 视频标题
        description: 视频简介（可选）
        platforms: 要使用的 AI 平台列表，默认 ["gemini", "chatgpt"]

    Returns:
        {
            "status": "success",
            "images": [...],
            "prompt": "..."
        }
    """
    if platforms is None:
        platforms = ["gemini", "chatgpt"]

    job_dir = get_job_dir(job_id).resolve()
    ai_covers_dir = job_dir / "ai_covers"
    ai_covers_dir.mkdir(parents=True, exist_ok=True)

    # 构建提示词
    prompt = _build_prompt(title, description)
    logger.info(f"[AI Cover] job_id={job_id}, platforms={platforms}")
    logger.info(f"[AI Cover] prompt={prompt[:200]}...")

    results: dict[str, list[str]] = {"gemini": [], "chatgpt": []}

    # 生成封面
    for platform in platforms:
        if platform not in ["gemini", "chatgpt"]:
            continue

        try:
            platform_files = _generate_with_platform(
                job_id=job_id,
                platform=platform,
                prompt=prompt,
                output_dir=ai_covers_dir,
            )
            results[platform] = platform_files
        except Exception as exc:
            logger.error(f"[AI Cover] {platform} 生成失败: {exc}")
            results[platform] = []

    # 汇总结果
    all_images = []
    for platform, files in results.items():
        for filename in files:
            all_images.append({
                "platform": platform,
                "filename": filename,
                "path": str(ai_covers_dir / filename),
            })

    has_gemini = len(results.get("gemini", [])) > 0
    has_chatgpt = len(results.get("chatgpt", [])) > 0

    if has_gemini and has_chatgpt:
        status = "success"
    elif has_gemini or has_chatgpt:
        status = "partial"
    else:
        status = "failed"

    return {
        "status": status,
        "images": all_images,
        "prompt": prompt,
    }


def select_ai_cover(job_id: str, filename: str) -> dict:
    """
    选择 AI 封面图

    Args:
        job_id: 任务 ID
        filename: 用户选择的文件名

    Returns:
        {
            "status": "success",
            "thumbnail": "publish_cover.jpg"
        }
    """
    job_dir = get_job_dir(job_id).resolve()
    ai_covers_dir = job_dir / "ai_covers"
    source_path = ai_covers_dir / filename

    if not source_path.exists():
        raise FileNotFoundError(f"文件不存在: {filename}")

    # 复制到 publish_cover.jpg
    output_path = job_dir / "publish_cover.jpg"
    shutil.copy2(source_path, output_path)

    # 更新草稿
    draft = save_publish_draft(job_id, {"thumbnail": "publish_cover.jpg"})

    logger.info(f"[AI Cover] Selected {filename} as cover for job {job_id}")

    return {
        "status": "success",
        "thumbnail": "publish_cover.jpg",
        "source": filename,
    }


def list_ai_cover_images(job_id: str) -> dict:
    """
    列出当前任务的 AI 封面图

    Args:
        job_id: 任务 ID

    Returns:
        {"images": [...]}
    """
    job_dir = get_job_dir(job_id).resolve()
    ai_covers_dir = job_dir / "ai_covers"

    if not ai_covers_dir.exists():
        return {"images": []}

    images = []
    for f in ai_covers_dir.iterdir():
        if f.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            images.append({
                "filename": f.name,
                "platform": "gemini" if "gemini" in f.name else "chatgpt" if "chatgpt" in f.name else "unknown",
                "path": str(f),
                "mtime": f.stat().st_mtime,
            })

    # 按修改时间倒序排列（最新的在前）
    images.sort(key=lambda x: x["mtime"], reverse=True)

    return {"images": images}
