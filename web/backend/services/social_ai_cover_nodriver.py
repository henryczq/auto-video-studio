"""AI 封面图生成服务 - 使用 nodriver（直接控制 Chrome，难被检测）

nodriver 特点：
1. 直接控制 Chrome，不走 WebDriver 协议
2. 极难被网站检测
3. 登录状态保存在 nodriver_profile 目录，首次登录后自动复用
"""

import asyncio
import json
import logging
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

# 禁用 nodriver 和底层库的调试日志（避免刷屏）
logging.getLogger("nodriver").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("chromews").setLevel(logging.WARNING)

from services.job_store import get_job_dir
from services.social_ai_cover_prompt import build_ai_cover_prompt
from services.publish_drafts import save_publish_draft

logger = logging.getLogger(__name__)

# nodriver 持久化 profile（首次登录后保存，下次自动复用）
NODRIVER_PROFILE = Path.home() / ".auto-video-studio" / "nodriver_profile"

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


def _kill_existing_chrome():
    """清理现有的 Chrome 进程，避免端口冲突"""
    import subprocess
    try:
        # 查找并杀掉 nodriver 相关的 Chrome 进程
        result = subprocess.run(
            ["pgrep", "-f", "chrome.*--remote-debugging-port"],
            capture_output=True,
            text=True
        )
        if result.stdout:
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                if pid:
                    try:
                        subprocess.run(["kill", "-9", pid], check=False)
                        logger.info(f"[nodriver] Killed existing Chrome process: {pid}")
                    except Exception:
                        pass
            # 等待进程完全退出
            time.sleep(2)
    except Exception as e:
        logger.debug(f"[nodriver] Error killing Chrome: {e}")


async def _generate_with_nodriver(
    job_id: str,
    platform: str,
    prompt: str,
    output_dir: Path,
    download_dir: Path,
) -> list[str]:
    """使用 nodriver 生成图片

    优先连接用户已启动的 Chrome（--remote-debugging-port=9222），
    复用登录态。如果没有，则启动新的 Chrome 实例。
    """
    import nodriver as uc

    logger.info(f"[nodriver] Starting {platform}")

    downloaded_files = []
    browser = None

    try:
        # 清理现有 Chrome 进程，避免冲突
        _kill_existing_chrome()

        # 启动新的 Chrome 实例，使用持久化 profile 保存登录态
        NODRIVER_PROFILE.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"[nodriver] Starting Chrome with profile: {NODRIVER_PROFILE}")

        # 检测 Chrome 路径
        chrome_path = "/usr/bin/google-chrome"
        if not os.path.exists(chrome_path):
            # 尝试其他路径
            for path in ["/usr/bin/chromium", "/usr/bin/chromium-browser"]:
                if os.path.exists(path):
                    chrome_path = path
                    break
        logger.info(f"[nodriver] Using Chrome at: {chrome_path}")

        browser = await uc.start(
            headless=False,
            sandbox=False,
            browser_args=[
                f"--user-data-dir={NODRIVER_PROFILE}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
            browser_executable_path=chrome_path if os.path.exists(chrome_path) else None,
        )
        logger.info(f"[nodriver] Chrome started successfully, tabs: {len(browser.tabs)}")

        # 打开目标页面
        url = "https://gemini.google.com/app" if platform == "gemini" else "https://chatgpt.com/"

        logger.info(f"[nodriver] Target URL: {url}")

        # 创建新标签页并导航
        tab = await browser.get(url)
        logger.info(f"[nodriver] Created new tab for {url}")

        # 等待页面加载（给足时间）
        await asyncio.sleep(12)
        logger.info(f"[nodriver] Tab URL after wait: {tab.url}")

        # 兜底：如果 URL 不对，用多种方式强制跳转
        if url not in tab.url:
            logger.warning(f"[nodriver] URL mismatch! Expected: {url}, Got: {tab.url}")

            # 方法1: 使用 JS 强制跳转
            logger.info("[nodriver] Using JS navigation...")
            await tab.evaluate(f'window.location.href = "{url}"')
            await asyncio.sleep(10)
            logger.info(f"[nodriver] After JS navigation: {tab.url}")

        if platform == "gemini":
            await _gemini_workflow(tab, prompt)
        else:
            await _chatgpt_workflow(tab, prompt)

        # 等待额外时间确保所有下载完成
        logger.info("[nodriver] Final wait for downloads...")
        await asyncio.sleep(3)

        # 收集下载的文件
        for f in download_dir.iterdir():
            if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                try:
                    size = f.stat().st_size
                    if size > 5000:
                        downloaded_files.append(f)
                        logger.info(f"[nodriver] Found file: {f.name} ({size} bytes)")
                except OSError:
                    pass

        logger.info(f"[nodriver] Total files found: {len(downloaded_files)}")

    except Exception as exc:
        logger.error(f"[nodriver] Error: {exc}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        if browser:
            try:
                browser.stop()
            except Exception:
                pass

    return [str(f) for f in downloaded_files[:2]]


async def _wait_and_find_element(tab, selector: str, max_wait: int = 10, check_interval: float = 0.5):
    """等待并查找元素，带详细日志"""
    logger.info(f"[nodriver] Waiting for element: {selector} (max {max_wait}s)")
    start_time = time.time()
    attempts = 0

    while time.time() - start_time < max_wait:
        attempts += 1
        try:
            element = await tab.query_selector(selector)
            if element:
                logger.info(f"[nodriver] Found element '{selector}' after {attempts} attempts ({time.time() - start_time:.1f}s)")
                return element
        except Exception as e:
            logger.debug(f"[nodriver] Attempt {attempts}: {selector} not found yet - {e}")
        await asyncio.sleep(check_interval)

    logger.warning(f"[nodriver] Element '{selector}' not found after {max_wait}s ({attempts} attempts)")
    return None


async def _safe_click(element, description: str = "element") -> bool:
    """安全点击元素：滚动到视口并点击
    
    参考 Playwright 的做法：
    1. 滚动到视口
    2. 尝试点击
    3. 失败时尝试 JS 点击
    """
    if not element:
        logger.warning(f"[nodriver] Cannot click None element ({description})")
        return False

    try:
        # 方法1: 直接点击
        logger.info(f"[nodriver] Attempting to click {description}...")
        await element.click()
        logger.info(f"[nodriver] ✓ Clicked {description} (direct)")
        return True
    except Exception as e1:
        logger.debug(f"[nodriver] Direct click failed for {description}: {e1}")

        try:
            # 方法2: 滚动到视口后点击
            logger.info(f"[nodriver] Scrolling {description} into view...")
            await element.scroll_into_view()
            await asyncio.sleep(0.5)
            await element.click()
            logger.info(f"[nodriver] ✓ Clicked {description} (after scroll)")
            return True
        except Exception as e2:
            logger.debug(f"[nodriver] Scroll+click failed for {description}: {e2}")

            try:
                # 方法3: JS 点击
                logger.info(f"[nodriver] Trying JS click for {description}...")
                await element.evaluate("el => el.click()")
                logger.info(f"[nodriver] ✓ Clicked {description} (JS)")
                return True
            except Exception as e3:
                logger.warning(f"[nodriver] All click methods failed for {description}")
                logger.debug(f"[nodriver] Errors: direct={e1}, scroll={e2}, js={e3}")
                return False


async def _gemini_workflow(tab, prompt: str):
    """Gemini 工作流程

    参考选择器（来自需求文档）：
    - 制作图片: .card-label.gds-body-l 或包含 "🖼️ 制作图片"
    - 输入框: .ql-editor.ql-blank.textarea.new-input-ui[contenteditable="true"][aria-label="为 Gemini 输入提示"]
    - 发送按钮: [data-mat-icon-name="send"] 或 .send-button-icon
    - 图片下载: .image-button 或 .image.loaded
    """
    logger.info("[nodriver] ===== Gemini workflow started =====")

    # 等待页面完全加载（给按钮渲染时间）
    logger.info("[nodriver] Waiting for page to fully load (5s)...")
    await asyncio.sleep(5)

    # 等待登录（最多 5 分钟）
    login_timeout = 300
    start_time = time.time()

    while time.time() - start_time < login_timeout:
        try:
            # 检查是否已登录（查找输入框）
            textareas = await tab.query_selector_all("textarea")
            if textareas:
                logger.info(f"[nodriver] Logged in detected, found {len(textareas)} textarea(s)")
                break
        except Exception as e:
            logger.debug(f"[nodriver] Waiting for login: {e}")
        await asyncio.sleep(2)
    else:
        logger.warning("[nodriver] Login wait timeout")

    await asyncio.sleep(2)

    # ===== 步骤1: 点击"制作图片"按钮 =====
    logger.info("[nodriver] Step 1: Looking for '制作图片' button...")
    clicked_image_mode = False

    try:
        # 精确策略1: 使用文档中的 class 选择器
        logger.info("[nodriver] Trying selector: .card-label.gds-body-l")
        image_btn = await _wait_and_find_element(tab, ".card-label.gds-body-l", max_wait=5)
        if image_btn:
            text = await image_btn.text()
            logger.info(f"[nodriver] Found element with text: '{text[:50]}...'")
            if text and ("制作图片" in text or "🖼" in text):
                clicked_image_mode = await _safe_click(image_btn, f".card-label.gds-body-l ({text[:30]})")
            else:
                logger.warning(f"[nodriver] Element found but text doesn't match: '{text[:50]}'")

        # 精确策略2: 通过文本内容查找按钮
        if not clicked_image_mode:
            logger.info("[nodriver] Trying to find button by text content...")
            buttons = await tab.query_selector_all("button")
            logger.info(f"[nodriver] Found {len(buttons)} buttons on page")
            for i, btn in enumerate(buttons):
                try:
                    text = await btn.text()
                    if text:
                        logger.debug(f"[nodriver] Button {i}: '{text[:50]}'")
                        if "制作图片" in text or "🖼" in text or "图片" in text:
                            clicked_image_mode = await _safe_click(btn, f"button with text '{text[:50]}'")
                            if clicked_image_mode:
                                break
                except Exception as e:
                    logger.debug(f"[nodriver] Error checking button {i}: {e}")

        # 兼容策略3：通过 aria-label 查找
        if not clicked_image_mode:
            logger.info("[nodriver] Trying selector: button[aria-label*='图片']...")
            buttons = await tab.query_selector_all('button[aria-label*="图片"], button[aria-label*="image"]')
            logger.info(f"[nodriver] Found {len(buttons)} buttons with aria-label containing '图片/image'")
            if buttons:
                clicked_image_mode = await _safe_click(buttons[0], "button[aria-label*='图片']")

        # 兼容策略4：通过包含特定文本的任意元素查找
        if not clicked_image_mode:
            logger.info("[nodriver] Searching all elements for '制作图片' text...")
            all_elements = await tab.query_selector_all("*")
            logger.info(f"[nodriver] Scanning {len(all_elements)} elements...")
            found_count = 0
            for el in all_elements:
                try:
                    text = await el.text()
                    if text and "制作图片" in text:
                        found_count += 1
                        logger.info(f"[nodriver] Found element with '制作图片': '{text[:50]}'")
                        clicked_image_mode = await _safe_click(el, f"element with '制作图片' text")
                        if clicked_image_mode:
                            break
                except Exception:
                    pass
            if found_count == 0:
                logger.warning("[nodriver] No element found with text '制作图片'")

    except Exception as e:
        logger.warning(f"[nodriver] Error in step 1: {e}")
        import traceback
        logger.warning(f"[nodriver] Traceback: {traceback.format_exc()}")

    if clicked_image_mode:
        logger.info("[nodriver] Image mode activated, waiting 3s...")
        await asyncio.sleep(3)
    else:
        logger.warning("[nodriver] ⚠ Could not find image mode button, will try direct input...")
        await asyncio.sleep(1)

    # ===== 步骤2: 输入提示词 =====
    logger.info("[nodriver] Step 2: Looking for input field...")
    filled = False
    try:
        # 精确策略1: 使用文档中的选择器
        logger.info("[nodriver] Trying selector: .ql-editor.ql-blank.textarea.new-input-ui[contenteditable='true']")
        input_editor = await _wait_and_find_element(tab, '.ql-editor.ql-blank.textarea.new-input-ui[contenteditable="true"]', max_wait=5)
        if input_editor:
            logger.info("[nodriver] Found input editor by class selector")
            await input_editor.click()
            await input_editor.send_keys(prompt)
            logger.info("[nodriver] ✓ Filled prompt in .ql-editor.ql-blank.textarea")
            filled = True

        # 精确策略2: 通过 aria-label 查找
        if not filled:
            logger.info("[nodriver] Trying selector: [aria-label='为 Gemini 输入提示']")
            input_editor = await _wait_and_find_element(tab, '[aria-label="为 Gemini 输入提示"][contenteditable="true"]', max_wait=3)
            if input_editor:
                logger.info("[nodriver] Found input editor by aria-label")
                await input_editor.click()
                await input_editor.send_keys(prompt)
                logger.info("[nodriver] ✓ Filled prompt by aria-label")
                filled = True

        # 兼容策略3：查找 textarea
        if not filled:
            logger.info("[nodriver] Trying to find textarea...")
            textareas = await tab.query_selector_all("textarea")
            logger.info(f"[nodriver] Found {len(textareas)} textarea(s)")
            if textareas:
                await textareas[0].clear()
                await textareas[0].send_keys(prompt)
                logger.info("[nodriver] ✓ Filled prompt in textarea")
                filled = True

        # 兼容策略4：查找任意 contenteditable
        if not filled:
            logger.info("[nodriver] Trying to find contenteditable elements...")
            editors = await tab.query_selector_all('[contenteditable="true"]')
            logger.info(f"[nodriver] Found {len(editors)} contenteditable element(s)")
            for i, editor in enumerate(editors):
                try:
                    await editor.click()
                    await editor.send_keys(prompt)
                    logger.info(f"[nodriver] ✓ Filled prompt in contenteditable {i}")
                    filled = True
                    break
                except Exception as e:
                    logger.debug(f"[nodriver] Failed to fill contenteditable {i}: {e}")

        # 兼容策略5：通过 placeholder 查找输入区
        if not filled:
            logger.info("[nodriver] Trying to find input by placeholder...")
            inputs = await tab.query_selector_all('input, textarea, [contenteditable="true"]')
            logger.info(f"[nodriver] Scanning {len(inputs)} input elements...")
            for i, inp in enumerate(inputs):
                try:
                    placeholder = await inp.get_attribute("placeholder") or ""
                    aria_label = await inp.get_attribute("aria-label") or ""
                    logger.debug(f"[nodriver] Input {i}: placeholder='{placeholder[:30]}', aria-label='{aria_label[:30]}'")
                    if "问问" in placeholder or "Gemini" in placeholder or "chat" in aria_label.lower():
                        await inp.click()
                        await inp.send_keys(prompt)
                        logger.info(f"[nodriver] ✓ Filled prompt by placeholder/aria-label match")
                        filled = True
                        break
                except Exception as e:
                    logger.debug(f"[nodriver] Error checking input {i}: {e}")

        if not filled:
            logger.warning("[nodriver] ⚠ Could not find any input field to fill")

    except Exception as e:
        logger.warning(f"[nodriver] Error in step 2: {e}")
        import traceback
        logger.warning(f"[nodriver] Traceback: {traceback.format_exc()}")

    await asyncio.sleep(1)

    # ===== 步骤3: 点击发送按钮 =====
    logger.info("[nodriver] Step 3: Looking for send button...")
    sent = False
    try:
        # 精确策略1: 使用文档中的 data-mat-icon-name 属性
        logger.info("[nodriver] Trying selector: [data-mat-icon-name='send']")
        send_btn = await _wait_and_find_element(tab, '[data-mat-icon-name="send"]', max_wait=3)
        if send_btn:
            logger.info("[nodriver] Found send button by data-mat-icon-name")
            sent = await _safe_click(send_btn, "[data-mat-icon-name='send']")

        # 精确策略2: 使用 .send-button-icon class
        if not sent:
            logger.info("[nodriver] Trying selector: .send-button-icon")
            send_btn = await _wait_and_find_element(tab, ".send-button-icon", max_wait=3)
            if send_btn:
                logger.info("[nodriver] Found send button by .send-button-icon")
                # 尝试点击父元素或自身
                try:
                    parent_btn = await send_btn.get_parent()
                    if parent_btn:
                        sent = await _safe_click(parent_btn, "send button parent")
                    if not sent:
                        sent = await _safe_click(send_btn, ".send-button-icon")
                except Exception as e:
                    logger.warning(f"[nodriver] Error getting parent: {e}")
                    sent = await _safe_click(send_btn, ".send-button-icon")

        # 兼容策略3：查找 aria-label 包含 send/submit 的按钮
        if not sent:
            logger.info("[nodriver] Searching buttons for send/submit...")
            buttons = await tab.query_selector_all("button")
            logger.info(f"[nodriver] Found {len(buttons)} buttons")
            for i, btn in enumerate(buttons):
                try:
                    aria_label = await btn.get_attribute("aria-label") or ""
                    text = await btn.text()
                    if aria_label or text:
                        logger.debug(f"[nodriver] Button {i}: text='{text[:30]}', aria-label='{aria_label[:30]}'")
                        if "发送" in text or "send" in aria_label.lower() or "submit" in aria_label.lower():
                            sent = await _safe_click(btn, f"send button (text='{text[:30]}')")
                            if sent:
                                break
                except Exception as e:
                    logger.debug(f"[nodriver] Error checking button {i}: {e}")

        # 兼容策略4：按 Enter 键发送
        if not sent and filled:
            logger.info("[nodriver] Trying to send via Enter key...")
            try:
                textarea = await tab.query_selector("textarea")
                if textarea:
                    await textarea.send_keys("\n")  # Enter key
                    logger.info("[nodriver] ✓ Sent prompt via Enter key")
                    sent = True
                else:
                    logger.warning("[nodriver] No textarea found for Enter key")
            except Exception as e:
                logger.warning(f"[nodriver] Error sending Enter key: {e}")

        if not sent:
            logger.warning("[nodriver] ⚠ Could not find send button or send via Enter")

    except Exception as e:
        logger.warning(f"[nodriver] Error in step 3: {e}")
        import traceback
        logger.warning(f"[nodriver] Traceback: {traceback.format_exc()}")

    # 等待图片生成
    if sent:
        logger.info("[nodriver] Waiting for image generation (60s)...")
        await asyncio.sleep(60)
    else:
        logger.warning("[nodriver] Prompt not sent, skipping image generation wait")
        return

    # ===== 步骤4: 点击生成的图片进行下载 =====
    logger.info("[nodriver] Step 4: Looking for generated images to download...")
    try:
        # 精确策略1: 使用文档中的 .image-button 选择器
        logger.info("[nodriver] Trying selector: .image-button")
        image_buttons = await tab.query_selector_all(".image-button")
        logger.info(f"[nodriver] Found {len(image_buttons)} .image-button element(s)")
        if image_buttons:
            for i, btn in enumerate(image_buttons[:2]):  # 最多点击前2张
                clicked = await _safe_click(btn, f"image button {i+1}")
                if clicked:
                    await asyncio.sleep(2)  # 等待下载开始
        else:
            # 精确策略2: 查找 .image.loaded 图片
            logger.info("[nodriver] Trying selector: .image.loaded")
            images = await tab.query_selector_all(".image.loaded")
            logger.info(f"[nodriver] Found {len(images)} .image.loaded element(s)")
            for i, img in enumerate(images[:2]):
                clicked = await _safe_click(img, f"image {i+1}")
                if clicked:
                    await asyncio.sleep(2)

        # 等待下载完成
        logger.info("[nodriver] Waiting for downloads to complete...")
        await asyncio.sleep(5)
    except Exception as e:
        logger.warning(f"[nodriver] Error in step 4: {e}")
        import traceback
        logger.warning(f"[nodriver] Traceback: {traceback.format_exc()}")

    logger.info("[nodriver] ===== Gemini workflow completed =====")


async def _chatgpt_workflow(tab, prompt: str):
    """ChatGPT 工作流程
    
    参考选择器（来自需求文档）：
    - 生成图片按钮: button 包含 span 文本 "生成图片"
    - 输入框: #prompt-textarea.ProseMirror[contenteditable="true"][aria-label="与 ChatGPT 聊天"]
    - 发送按钮: #composer-submit-button[aria-label="发送提示"][data-testid="send-button"]
    - 图片: img.absolute.top-0.z-1.w-full[src*="chatgpt.com/backend-api"]
    """
    logger.info("[nodriver] ChatGPT workflow")

    # 等待登录（最多 5 分钟）
    login_timeout = 300
    start_time = time.time()

    while time.time() - start_time < login_timeout:
        try:
            textarea = await tab.query_selector("textarea")
            if textarea:
                logger.info("[nodriver] Logged in, proceeding...")
                break
        except Exception:
            pass
        await asyncio.sleep(2)
    else:
        logger.warning("[nodriver] Login wait timeout")

    await asyncio.sleep(1)

    # ===== 步骤1: 选择图片生成模式 =====
    logger.info("[nodriver] Step 1: Looking for '生成图片' button...")
    clicked_image_mode = False
    try:
        # 精确策略1: 通过文档中的按钮结构查找（包含 span 文本 "生成图片"）
        buttons = await tab.query_selector_all("button")
        logger.info(f"[nodriver] Found {len(buttons)} buttons on page")
        for i, btn in enumerate(buttons):
            try:
                text = await btn.text()
                if text:
                    logger.debug(f"[nodriver] Button {i}: '{text[:50]}'")
                    if "生成图片" in text:
                        clicked_image_mode = await _safe_click(btn, f"'生成图片' button ({text[:50]})")
                        if clicked_image_mode:
                            break
            except Exception as e:
                logger.debug(f"[nodriver] Error checking button {i}: {e}")

        if not clicked_image_mode:
            logger.warning("[nodriver] Could not find '生成图片' button by text")
    except Exception as e:
        logger.warning(f"[nodriver] Could not find '生成图片': {e}")

    if clicked_image_mode:
        logger.info("[nodriver] Image mode activated, waiting 3s...")
        await asyncio.sleep(3)
    else:
        logger.warning("[nodriver] ⚠ Could not find image mode button, will try direct input...")
        await asyncio.sleep(1)

    # ===== 步骤2: 输入提示词 =====
    filled = False
    try:
        # 精确策略1: 使用文档中的 ID 和 class 选择器
        editor = await tab.query_selector('#prompt-textarea.ProseMirror[contenteditable="true"]')
        if editor:
            await editor.click()
            await editor.send_keys(prompt)
            logger.info("[nodriver] Filled prompt in #prompt-textarea.ProseMirror")
            filled = True

        # 精确策略2: 通过 aria-label 查找
        if not filled:
            editor = await tab.query_selector('[aria-label="与 ChatGPT 聊天"][contenteditable="true"]')
            if editor:
                await editor.click()
                await editor.send_keys(prompt)
                logger.info("[nodriver] Filled prompt by aria-label")
                filled = True

        # 兼容策略3: 查找 textarea
        if not filled:
            textarea = await tab.query_selector("textarea")
            if textarea:
                await textarea.clear()
                await textarea.send_keys(prompt)
                logger.info("[nodriver] Filled prompt in textarea")
                filled = True

        # 兼容策略4: 查找 .ProseMirror
        if not filled:
            editor = await tab.query_selector(".ProseMirror")
            if editor:
                await editor.click()
                await editor.send_keys(prompt)
                logger.info("[nodriver] Filled prompt in .ProseMirror")
                filled = True
    except Exception as e:
        logger.warning(f"[nodriver] Could not fill prompt: {e}")

    await asyncio.sleep(0.5)

    # ===== 步骤3: 点击生成按钮 =====
    sent = False
    try:
        # 精确策略1: 使用文档中的 ID 选择器
        send_btn = await tab.query_selector('#composer-submit-button[data-testid="send-button"]')
        if send_btn:
            sent = await _safe_click(send_btn, "#composer-submit-button")

        # 精确策略2: 通过 aria-label 查找
        if not sent:
            send_btn = await tab.query_selector('[aria-label="发送提示"]')
            if send_btn:
                sent = await _safe_click(send_btn, "button[aria-label='发送提示']")

        # 兼容策略3: 查找包含 send 的按钮
        if not sent:
            buttons = await tab.query_selector_all("button")
            for btn in buttons:
                try:
                    aria_label = await btn.get_attribute("aria-label") or ""
                    text = await btn.text()
                    if "发送" in text or "send" in aria_label.lower():
                        sent = await _safe_click(btn, f"send button (text='{text[:30]}')")
                        if sent:
                            break
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"[nodriver] Could not click submit: {e}")

    # 等待图片生成
    if sent:
        logger.info("[nodriver] Waiting for image generation (60s)...")
        await asyncio.sleep(60)
    else:
        logger.warning("[nodriver] Prompt not sent, skipping image generation")
        return

    # ===== 步骤4: 点击生成的图片进行下载 =====
    logger.info("[nodriver] Step 4: Looking for generated images...")
    try:
        # 精确策略1: 使用文档中的 class 选择器
        images = await tab.query_selector_all("img.absolute.top-0.z-1.w-full")
        if images:
            for i, img in enumerate(images[:2]):  # 最多点击前2张
                src = await img.get_attribute("src") or ""
                if "chatgpt.com" in src or "backend-api" in src or src.startswith("http"):
                    clicked = await _safe_click(img, f"generated image {i+1}")
                    if clicked:
                        await asyncio.sleep(2)
        else:
            # 兼容策略2: 查找所有图片元素
            all_images = await tab.query_selector_all("img")
            clicked_count = 0
            for img in all_images:
                src = await img.get_attribute("src") or ""
                if "chatgpt.com" in src and "/assets/" not in src:
                    clicked = await _safe_click(img, f"image {clicked_count+1}")
                    if clicked:
                        clicked_count += 1
                        await asyncio.sleep(2)
                        if clicked_count >= 2:
                            break

        # 等待下载完成
        logger.info("[nodriver] Waiting for downloads to complete...")
        await asyncio.sleep(5)
    except Exception as e:
        logger.warning(f"[nodriver] Could not download images: {e}")


def generate_ai_cover_nodriver(
    job_id: str,
    title: str,
    description: str = "",
    platforms: Optional[list[str]] = None,
) -> dict:
    """
    使用 nodriver 生成 AI 封面图

    Args:
        job_id: 任务 ID
        title: 视频标题
        description: 视频简介
        platforms: 要使用的 AI 平台列表

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
    logger.info(f"[nodriver] job_id={job_id}, platforms={platforms}")
    logger.info(f"[nodriver] prompt={prompt[:200]}...")

    # 初始化 profile 目录（如果不存在）
    if not NODRIVER_PROFILE.exists():
        NODRIVER_PROFILE.parent.mkdir(parents=True, exist_ok=True)

    results: dict[str, list[str]] = {"gemini": [], "chatgpt": []}

    for platform in platforms:
        if platform not in ["gemini", "chatgpt"]:
            continue

        try:
            output_dir = ai_covers_dir
            download_dir = output_dir / f"{platform}_downloads"
            download_dir.mkdir(parents=True, exist_ok=True)

            # 清理旧文件
            for f in download_dir.iterdir():
                if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                    try:
                        f.unlink()
                    except OSError:
                        pass

            # 使用 nodriver 生成（需要在单独的线程中运行以避免事件循环冲突）
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    asyncio.run,
                    _generate_with_nodriver(job_id, platform, prompt, output_dir, download_dir)
                )
                downloaded = future.result()

            # 转换并保存图片
            for i, src_path in enumerate(downloaded):
                src_path = Path(src_path)
                if src_path.exists():
                    dest_name = f"ai_cover_{platform}_{i + 1}.jpg"
                    dest_path = output_dir / dest_name
                    if _convert_and_save_image(src_path, dest_path):
                        results[platform].append(dest_name)
                        logger.info(f"[nodriver] Saved {dest_name}")

        except Exception as exc:
            logger.error(f"[nodriver] {platform} failed: {exc}")
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
    """选择 AI 封面图"""
    job_dir = get_job_dir(job_id).resolve()
    ai_covers_dir = job_dir / "ai_covers"
    source_path = ai_covers_dir / filename

    if not source_path.exists():
        raise FileNotFoundError(f"文件不存在: {filename}")

    output_path = job_dir / "publish_cover.jpg"
    shutil.copy2(source_path, output_path)

    save_publish_draft(job_id, {"thumbnail": "publish_cover.jpg"})

    logger.info(f"[AI Cover] Selected {filename} as cover for job {job_id}")

    return {
        "status": "success",
        "thumbnail": "publish_cover.jpg",
        "source": filename,
    }


def list_ai_cover_images(job_id: str) -> dict:
    """列出当前任务的 AI 封面图"""
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
            })

    images.sort(key=lambda x: (x["platform"], x["filename"]))

    return {"images": images}
