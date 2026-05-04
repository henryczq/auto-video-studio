#!/usr/bin/env python3
"""
使用 Playwright 生成 AI 封面图
复用 nodriver 的登录状态
"""

import asyncio
import base64
import logging
import os
import glob
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright

from services.job_store import get_job_dir
from services.social_ai_cover_prompt import build_ai_cover_prompt
from services.publish_drafts import save_publish_draft

logger = logging.getLogger(__name__)

# Chrome 配置
CHROME_PATH = "/usr/bin/google-chrome"
NODRIVER_PROFILE = Path.home() / ".auto-video-studio" / "nodriver_profile"
AI_COVER_DOWNLOAD_DIR = Path.home() / "Downloads"


_build_prompt = build_ai_cover_prompt


def _convert_and_save_image(src_path: Path, dest_path: Path) -> bool:
    """转换并保存图片"""
    try:
        from PIL import Image

        with Image.open(src_path) as img:
            # 转换为 RGB (去除 alpha 通道)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.save(dest_path, "JPEG", quality=95)
        return True
    except Exception as exc:
        logger.error(f"[playwright] Failed to convert image: {exc}")
        return False


async def _generate_with_playwright(
    job_id: str,
    platform: str,
    prompt: str,
    output_dir: Path,
    download_dir: Path,
) -> list[str]:
    """使用 Playwright 生成封面"""
    
    downloaded_files = []

    # 启动前清理锁文件，避免 "profile already in use" 错误
    for lock_file in glob.glob(str(NODRIVER_PROFILE / "**/LOCK"), recursive=True):
        try:
            os.remove(lock_file)
        except OSError:
            pass
    for singleton_file in ["SingletonLock", "SingletonSocket", "SingletonCookie"]:
        try:
            os.remove(NODRIVER_PROFILE / singleton_file)
        except OSError:
            pass

    async with async_playwright() as p:
        # 启动 Chrome，复用 nodriver 的 profile
        chrome_path = CHROME_PATH if os.path.exists(CHROME_PATH) else None

        print(f"[playwright] Launching Chrome with profile: {NODRIVER_PROFILE}")
        logger.info(f"[playwright] Launching Chrome with profile: {NODRIVER_PROFILE}")

        # 使用 persistent context 复用登录状态
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(NODRIVER_PROFILE),
            headless=False,
            executable_path=chrome_path,
            args=[
                "--lang=zh-CN",
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ],
            viewport={"width": 1280, "height": 800},
            no_viewport=False,
        )

        # 获取或创建页面
        pages = context.pages
        if pages:
            page = pages[0]
            print(f"[playwright] Using existing page: {page.url}")
            logger.info(f"[playwright] Using existing page: {page.url}")
        else:
            page = await context.new_page()
            print("[playwright] Created new page")
            logger.info("[playwright] Created new page")

        try:
            # 打开目标页面
            url = "https://gemini.google.com/app" if platform == "gemini" else "https://chatgpt.com/"
            print(f"[playwright] Navigating to {url}")
            logger.info(f"[playwright] Navigating to {url}")

            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(5000)  # 等待页面完全加载

            print(f"[playwright] Page loaded: {page.url}")
            logger.info(f"[playwright] Page loaded: {page.url}")

            # 检查是否需要登录
            if "accounts.google.com" in page.url or "signin" in page.url.lower():
                print("[playwright] Login required! Waiting for 120 seconds...")
                logger.warning("[playwright] Login required! Waiting for 120 seconds for manual login...")
                print("\n" + "="*60)
                print("请在新打开的浏览器窗口中登录 Gemini")
                print("登录完成后，程序会继续执行")
                print("="*60 + "\n")
                await page.wait_for_timeout(120000)  # 等待2分钟让用户登录

            downloaded_files = []
            
            print(f"[playwright] Starting workflow for {platform}")
            
            if platform == "gemini":
                downloaded_files = await _gemini_workflow(page, prompt, download_dir)
                if downloaded_files is None:
                    downloaded_files = []
            else:
                downloaded_files = await _chatgpt_workflow(page, prompt, download_dir)
                if downloaded_files is None:
                    downloaded_files = []

            print(f"[playwright] Workflow completed, files: {len(downloaded_files)}")
            logger.info(f"[playwright] Total files found: {len(downloaded_files)}")

        except Exception as exc:
            print(f"[playwright] Error: {exc}")
            logger.error(f"[playwright] Error: {exc}")
            import traceback
            traceback.print_exc()
            raise
        finally:
            print("[playwright] Closing browser context")
            await context.close()

    return [str(f) for f in downloaded_files[:2]]


async def _gemini_workflow(page, prompt: str, download_dir: Path) -> list[str]:
    """Gemini 工作流程"""
    print("[playwright] ===== Gemini workflow started =====")
    logger.info("[playwright] ===== Gemini workflow started =====")
    downloaded_files = []

    # 清空下载目录中的旧 gemini 图片
    for old_file in download_dir.glob("gemini_image_*.jpg"):
        try:
            old_file.unlink()
            print(f"[playwright] Removed old file: {old_file.name}")
        except:
            pass

    # 等待页面完全加载
    await page.wait_for_timeout(5000)

    # ===== 步骤1: 点击"制作图片"按钮 =====
    print("[playwright] Step 1: Looking for '制作图片' button...")
    logger.info("[playwright] Step 1: Looking for '制作图片' button...")

    clicked = False
    
    # 策略1: 通过文本查找
    try:
        image_btn = page.get_by_text("制作图片", exact=False)
        count = await image_btn.count()
        print(f"[playwright] Found {count} buttons with text '制作图片'")
        if count > 0:
            await image_btn.first.wait_for(state="visible", timeout=5000)
            await image_btn.first.click()
            print("[playwright] ✓ Clicked '制作图片' button by text")
            logger.info("[playwright] ✓ Clicked '制作图片' button by text")
            clicked = True
            await page.wait_for_timeout(3000)
    except Exception as e:
        print(f"[playwright] Text search failed: {e}")
        logger.debug(f"[playwright] Text search failed: {e}")

    # 策略2: 通过 CSS 选择器查找
    if not clicked:
        selectors = [
            "button:has-text('制作图片')",
            "[aria-label*='制作图片']",
            "[aria-label*='图片']",
            ".card:has-text('制作图片')",
            "mat-chip:has-text('制作图片')",
        ]
        for selector in selectors:
            try:
                btn = page.locator(selector).first
                await btn.wait_for(state="visible", timeout=3000)
                await btn.click()
                print(f"[playwright] ✓ Clicked button with selector: {selector}")
                logger.info(f"[playwright] ✓ Clicked button with selector: {selector}")
                clicked = True
                await page.wait_for_timeout(3000)
                break
            except Exception as e:
                logger.debug(f"[playwright] Selector {selector} failed: {e}")

    # 策略3: 通过 JavaScript 查找并点击
    if not clicked:
        try:
            result = await page.evaluate("""() => {
                // 查找包含"制作图片"文本的所有元素
                const elements = document.querySelectorAll('*');
                for (const el of elements) {
                    if (el.textContent && el.textContent.includes('制作图片')) {
                        // 找到可点击的父元素
                        let clickable = el;
                        while (clickable && clickable.tagName !== 'BUTTON' && clickable.tagName !== 'A' && !clickable.onclick) {
                            clickable = clickable.parentElement;
                        }
                        if (clickable) {
                            clickable.click();
                            return 'clicked: ' + clickable.tagName;
                        }
                    }
                }
                return 'not found';
            }""")
            if result != 'not found':
                logger.info(f"[playwright] ✓ Clicked '制作图片' via JS: {result}")
                clicked = True
                await page.wait_for_timeout(3000)
        except Exception as e:
            logger.debug(f"[playwright] JS click failed: {e}")

    if not clicked:
        logger.warning("[playwright] ⚠ Could not find '制作图片' button, continuing anyway...")

    # ===== 步骤2: 输入提示词 =====
    print("[playwright] Step 2: Filling prompt...")
    logger.info("[playwright] Step 2: Filling prompt...")

    filled = False

    # 策略1: 查找 rich-textarea (Gemini 的输入组件)
    try:
        rich_input = page.locator("rich-textarea").first
        await rich_input.wait_for(state="visible", timeout=5000)
        # 找到内部的 contenteditable 元素
        editor = rich_input.locator('[contenteditable="true"]').first
        await editor.click()
        await editor.fill(prompt)
        print("[playwright] ✓ Filled prompt in rich-textarea")
        logger.info("[playwright] ✓ Filled prompt in rich-textarea")
        filled = True
    except Exception as e:
        print(f"[playwright] rich-textarea failed: {e}")
        logger.debug(f"[playwright] rich-textarea failed: {e}")

    # 策略2: 通过 ID 和 class 查找 (参考文档)
    if not filled:
        try:
            editor = page.locator('#prompt-textarea.ProseMirror[contenteditable="true"]').first
            await editor.wait_for(state="visible", timeout=5000)
            await editor.click()
            await editor.fill(prompt)
            print("[playwright] ✓ Filled prompt in #prompt-textarea.ProseMirror")
            logger.info("[playwright] ✓ Filled prompt in #prompt-textarea.ProseMirror")
            filled = True
        except Exception as e:
            print(f"[playwright] #prompt-textarea failed: {e}")
            logger.debug(f"[playwright] #prompt-textarea failed: {e}")

    # 策略3: 通过 aria-label 查找
    if not filled:
        try:
            editor = page.locator('[aria-label="与 Gemini 聊天"][contenteditable="true"]').first
            await editor.wait_for(state="visible", timeout=5000)
            await editor.click()
            await editor.fill(prompt)
            print("[playwright] ✓ Filled prompt by aria-label")
            logger.info("[playwright] ✓ Filled prompt by aria-label")
            filled = True
        except Exception as e:
            print(f"[playwright] aria-label failed: {e}")
            logger.debug(f"[playwright] aria-label failed: {e}")

    # 策略4: 查找任何 contenteditable
    if not filled:
        try:
            editors = await page.query_selector_all('[contenteditable="true"]')
            if editors:
                await editors[-1].click()  # 通常最后一个是最新的输入框
                await editors[-1].fill(prompt)
                logger.info("[playwright] ✓ Filled prompt in last contenteditable")
                filled = True
        except Exception as e:
            logger.debug(f"[playwright] Last contenteditable failed: {e}")

    if not filled:
        logger.error("[playwright] Could not find input field")
        return []

    # ===== 步骤3: 发送消息 =====
    await page.wait_for_timeout(1000)
    
    print("[playwright] Step 3: Sending message...")
    logger.info("[playwright] Step 3: Sending message...")
    
    sent = False
    
    # 方法1: 点击发送按钮
    try:
        send_btn = page.locator('button[aria-label="发送消息"]').first
        await send_btn.wait_for(state="visible", timeout=3000)
        await send_btn.click()
        print("[playwright] ✓ Clicked send button")
        logger.info("[playwright] ✓ Clicked send button")
        sent = True
    except Exception as e:
        logger.debug(f"[playwright] Send button click failed: {e}")

    # 方法2: 按 Enter 键
    if not sent:
        try:
            await page.keyboard.press("Enter")
            print("[playwright] ✓ Pressed Enter to send")
            logger.info("[playwright] ✓ Pressed Enter to send")
            sent = True
        except Exception as e:
            logger.debug(f"[playwright] Enter key failed: {e}")

    if not sent:
        logger.error("[playwright] Could not send message")
        return []

    # ===== 步骤4: 等待图片生成 =====
    print("[playwright] Step 4: Waiting for image generation...")
    logger.info("[playwright] Step 4: Waiting for image generation...")
    
    # Gemini 生成图片需要时间，先等待一段时间让生成开始
    print("[playwright] Waiting 20s for generation to start...")
    await page.wait_for_timeout(20000)
    
    max_wait = 180  # 最多等待180秒（3分钟）
    waited = 20  # 已经等了20秒
    check_interval = 5  # 每5秒检查一次
    new_images_found = False
    last_large_count = 0
    stable_count = 0  # 连续几次检查图片数量不变
    
    while waited < max_wait:
        await page.wait_for_timeout(check_interval * 1000)
        waited += check_interval
        
        # 滚动到页面底部确保加载最新内容
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1000)
        
        # 检查所有大图片（不依赖索引，直接检查所有图片的尺寸）
        try:
            all_images = await page.query_selector_all("img")
            large_images = []
            
            for img in all_images:
                try:
                    info = await img.evaluate("""el => {
                        const rect = el.getBoundingClientRect();
                        return {
                            width: rect.width || el.naturalWidth || el.width || 0,
                            height: rect.height || el.naturalHeight || el.height || 0,
                            src: el.src || ''
                        };
                    }""")
                    # 检查大图片（>300px），使用页面可见尺寸
                    if info['width'] >= 300 and info['height'] >= 300:
                        large_images.append(img)
                except:
                    pass
            
            current_count = len(large_images)
            print(f"[playwright] Found {current_count} large images (>300px) after {waited}s")
            
            # 检测图片数量是否稳定（连续3次相同说明生成完成）
            if current_count > 0:
                if current_count == last_large_count:
                    stable_count += 1
                    if stable_count >= 3:  # 连续3次数量相同，认为生成完成
                        print(f"[playwright] Image generation stable after {waited}s, found {current_count} images")
                        logger.info(f"[playwright] Image generation stable, found {current_count} images")
                        new_images_found = True
                        # 再等待10秒确保图片完全渲染
                        await page.wait_for_timeout(10000)
                        break
                else:
                    stable_count = 0
                    last_large_count = current_count
            
        except Exception as e:
            logger.debug(f"[playwright] Error checking images: {e}")
        
        if waited % 15 == 0:
            print(f"[playwright] Still waiting... {waited}s")
            logger.info(f"[playwright] Still waiting for images... {waited}s")

    print(f"[playwright] Total waited: {waited}s, new images found: {new_images_found}")
    logger.info(f"[playwright] Total waited: {waited}s, new images found: {new_images_found}")

    # ===== 步骤5: 下载生成的图片 =====
    if not new_images_found:
        print("[playwright] ⚠ No images detected, but will try to download anyway...")
        logger.warning("[playwright] No images detected, but will try to download anyway")
    
    print("[playwright] Step 5: Downloading images...")
    logger.info("[playwright] Step 5: Downloading images...")
    downloaded_files = await _download_gemini_images(page, download_dir)
    
    print(f"[playwright] ===== Gemini workflow completed, downloaded: {len(downloaded_files)} files =====")
    logger.info(f"[playwright] ===== Gemini workflow completed, downloaded: {len(downloaded_files)} files =====")
    return downloaded_files


async def _download_gemini_images(page, download_dir: Path) -> list[str]:
    """下载 Gemini 生成的图片 - 下载所有大图片"""
    downloaded = []

    try:
        # 获取所有图片
        all_images = await page.query_selector_all("img")
        print(f"[playwright] Total images on page: {len(all_images)}")
        
        # 只保留大图片（>400px），排除头像和图标
        large_images = []
        for img in all_images:
            try:
                info = await img.evaluate("""el => {
                    return {
                        width: el.naturalWidth || el.width || 0,
                        height: el.naturalHeight || el.height || 0,
                        src: el.src || ''
                    };
                }""")
                # 调试：打印所有大图片的信息
                if info['width'] >= 200 and info['height'] >= 200:
                    print(f"[playwright] Image found: {info['width']}x{info['height']}, src: {info['src'][:80]}...")
                
                # 检查大图片（>400px）
                if info['width'] >= 400 and info['height'] >= 400:
                    large_images.append(img)
            except Exception as e:
                print(f"[playwright] Error getting image info: {e}")
        
        print(f"[playwright] Found {len(large_images)} large images (>400px)")
        logger.info(f"[playwright] Found {len(large_images)} large images")
        
        # 只取最新的 2-4 张图片
        large_images = large_images[-4:] if len(large_images) > 4 else large_images
        
        img_index = 0
        for img in large_images:
            try:
                # 获取图片信息
                info = await img.evaluate("""el => {
                    const rect = el.getBoundingClientRect();
                    return {
                        width: rect.width || el.naturalWidth || el.width || 0,
                        height: rect.height || el.naturalHeight || el.height || 0,
                        src: el.src || '',
                        visible: rect.width > 0 && rect.height > 0
                    };
                }""")

                print(f"[playwright] Processing image: {info['width']}x{info['height']}, src: {info['src'][:50]}...")

                # 只处理大图片（>300px）
                if info['width'] >= 300 and info['height'] >= 300:
                    img_index += 1
                    dest_path = download_dir / f"gemini_image_{img_index}.jpg"
                    
                    # 策略1: 如果是 Blob URL，使用 Canvas 提取
                    if info['src'].startswith('blob:'):
                        print(f"[playwright] Image {img_index} is Blob URL, using Canvas extraction...")
                        try:
                            await img.scroll_into_view_if_needed()
                            await page.wait_for_timeout(500)
                            
                            img_data = await img.evaluate("""el => {
                                return new Promise((resolve, reject) => {
                                    try {
                                        const canvas = document.createElement('canvas');
                                        canvas.width = el.naturalWidth || el.width;
                                        canvas.height = el.naturalHeight || el.height;
                                        const ctx = canvas.getContext('2d');
                                        ctx.drawImage(el, 0, 0);
                                        resolve(canvas.toDataURL('image/jpeg', 0.95));
                                    } catch (e) {
                                        reject(e.toString());
                                    }
                                });
                            }""")
                            
                            if img_data and img_data.startswith('data:image'):
                                header, encoded = img_data.split(',', 1)
                                data = base64.b64decode(encoded)
                                
                                with open(dest_path, 'wb') as f:
                                    f.write(data)
                                
                                if dest_path.exists() and dest_path.stat().st_size > 10000:
                                    print(f"[playwright] ✓ Extracted image {img_index}: {dest_path.name} ({dest_path.stat().st_size} bytes)")
                                    logger.info(f"[playwright] Extracted image {img_index}: {dest_path.name} ({dest_path.stat().st_size} bytes)")
                                    downloaded.append(str(dest_path))
                                    continue
                                else:
                                    dest_path.unlink(missing_ok=True)
                        except Exception as e:
                            print(f"[playwright] Canvas extraction failed: {e}")
                    
                    # 策略2: 如果是 HTTP URL，直接下载
                    elif info['src'].startswith('http') and any(domain in info['src'] for domain in ["googleusercontent.com", "gstatic.com"]):
                        try:
                            import urllib.request
                            req = urllib.request.Request(info['src'], headers={
                                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                            })
                            with urllib.request.urlopen(req, timeout=30) as response:
                                with open(dest_path, 'wb') as f:
                                    f.write(response.read())
                            
                            if dest_path.exists() and dest_path.stat().st_size > 10000:
                                print(f"[playwright] ✓ Downloaded image {img_index}: {dest_path.name} ({dest_path.stat().st_size} bytes)")
                                logger.info(f"[playwright] Downloaded image {img_index}: {dest_path.name} ({dest_path.stat().st_size} bytes)")
                                downloaded.append(str(dest_path))
                                continue
                            else:
                                dest_path.unlink(missing_ok=True)
                        except Exception as e:
                            print(f"[playwright] Direct download failed: {e}")
                            
            except Exception as e:
                logger.debug(f"[playwright] Failed to process image: {e}")
        
        print(f"[playwright] Total downloaded: {len(downloaded)} images")
        logger.info(f"[playwright] Total downloaded: {len(downloaded)} images")

    except Exception as e:
        logger.warning(f"[playwright] Error downloading images: {e}")

    return downloaded


async def _chatgpt_workflow(page, prompt: str, download_dir: Path) -> list[str]:
    """ChatGPT 工作流程"""
    print("[playwright] ===== ChatGPT workflow started =====")
    logger.info("[playwright] ===== ChatGPT workflow started =====")
    downloaded_files = []

    # 清空下载目录中的旧 chatgpt 图片
    for old_file in download_dir.glob("chatgpt_image_*.jpg"):
        try:
            old_file.unlink()
            print(f"[playwright] Removed old file: {old_file.name}")
        except:
            pass

    # 等待页面加载
    await page.wait_for_timeout(5000)

    # ===== 步骤1: 选择图片生成模式 =====
    print("[playwright] Step 1: Looking for '生成图片' button...")
    logger.info("[playwright] Step 1: Looking for '生成图片' button...")

    clicked = False

    # 策略1: 通过文本查找
    try:
        btn = page.get_by_text("生成图片", exact=False).first
        await btn.wait_for(state="visible", timeout=5000)
        await btn.click()
        print("[playwright] ✓ Clicked '生成图片' button by text")
        logger.info("[playwright] ✓ Clicked '生成图片' button by text")
        clicked = True
        await page.wait_for_timeout(3000)
    except Exception as e:
        print(f"[playwright] Text search failed: {e}")
        logger.debug(f"[playwright] Text search failed: {e}")

    # 策略2: 通过 CSS 选择器查找
    if not clicked:
        selectors = [
            "button:has-text('生成图片')",
            "[aria-label*='生成图片']",
            "[aria-label*='图片']",
            "button:has(svg):has-text('图片')",
        ]
        for selector in selectors:
            try:
                btn = page.locator(selector).first
                await btn.wait_for(state="visible", timeout=3000)
                await btn.click()
                print(f"[playwright] ✓ Clicked button with selector: {selector}")
                logger.info(f"[playwright] ✓ Clicked button with selector: {selector}")
                clicked = True
                await page.wait_for_timeout(3000)
                break
            except Exception as e:
                logger.debug(f"[playwright] Selector {selector} failed: {e}")

    # 策略3: 通过 JavaScript 查找并点击
    if not clicked:
        try:
            result = await page.evaluate("""() => {
                const elements = document.querySelectorAll('*');
                for (const el of elements) {
                    if (el.textContent && el.textContent.includes('生成图片')) {
                        let clickable = el;
                        while (clickable && clickable.tagName !== 'BUTTON' && clickable.tagName !== 'A' && !clickable.onclick) {
                            clickable = clickable.parentElement;
                        }
                        if (clickable) {
                            clickable.click();
                            return 'clicked: ' + clickable.tagName;
                        }
                    }
                }
                return 'not found';
            }""")
            if result != 'not found':
                print(f"[playwright] ✓ Clicked '生成图片' via JS: {result}")
                logger.info(f"[playwright] ✓ Clicked '生成图片' via JS: {result}")
                clicked = True
                await page.wait_for_timeout(3000)
        except Exception as e:
            logger.debug(f"[playwright] JS click failed: {e}")

    if not clicked:
        logger.warning("[playwright] ⚠ Could not find '生成图片' button, continuing anyway...")

    # ===== 步骤2: 输入提示词 =====
    print("[playwright] Step 2: Filling prompt...")
    logger.info("[playwright] Step 2: Filling prompt...")

    filled = False

    # 策略1: 查找 #prompt-textarea.ProseMirror
    try:
        editor = page.locator('#prompt-textarea.ProseMirror[contenteditable="true"]').first
        await editor.wait_for(state="visible", timeout=5000)
        await editor.click()
        await editor.fill(prompt)
        print("[playwright] ✓ Filled prompt in #prompt-textarea.ProseMirror")
        logger.info("[playwright] ✓ Filled prompt in #prompt-textarea.ProseMirror")
        filled = True
    except Exception as e:
        print(f"[playwright] #prompt-textarea failed: {e}")
        logger.debug(f"[playwright] #prompt-textarea failed: {e}")

    # 策略2: 通过 aria-label 查找
    if not filled:
        try:
            editor = page.locator('[aria-label="与 ChatGPT 聊天"][contenteditable="true"]').first
            await editor.wait_for(state="visible", timeout=5000)
            await editor.click()
            await editor.fill(prompt)
            print("[playwright] ✓ Filled prompt by aria-label")
            logger.info("[playwright] ✓ Filled prompt by aria-label")
            filled = True
        except Exception as e:
            print(f"[playwright] aria-label failed: {e}")
            logger.debug(f"[playwright] aria-label failed: {e}")

    # 策略3: 查找任何 contenteditable
    if not filled:
        try:
            editors = await page.query_selector_all('[contenteditable="true"]')
            if editors:
                await editors[-1].click()
                await editors[-1].fill(prompt)
                print("[playwright] ✓ Filled prompt in last contenteditable")
                logger.info("[playwright] ✓ Filled prompt in last contenteditable")
                filled = True
        except Exception as e:
            logger.debug(f"[playwright] Last contenteditable failed: {e}")

    if not filled:
        logger.error("[playwright] Could not find input field")
        return []

    # ===== 步骤3: 发送消息 =====
    await page.wait_for_timeout(1000)

    print("[playwright] Step 3: Sending message...")
    logger.info("[playwright] Step 3: Sending message...")

    sent = False

    # 方法1: 点击发送按钮 (#composer-submit-button)
    try:
        send_btn = page.locator('#composer-submit-button').first
        await send_btn.wait_for(state="visible", timeout=3000)
        await send_btn.click()
        print("[playwright] ✓ Clicked send button #composer-submit-button")
        logger.info("[playwright] ✓ Clicked send button #composer-submit-button")
        sent = True
    except Exception as e:
        logger.debug(f"[playwright] Send button #composer-submit-button failed: {e}")

    # 方法2: 通过 aria-label 查找发送按钮
    if not sent:
        try:
            send_btn = page.locator('button[aria-label="发送提示"]').first
            await send_btn.wait_for(state="visible", timeout=3000)
            await send_btn.click()
            print("[playwright] ✓ Clicked send button by aria-label")
            logger.info("[playwright] ✓ Clicked send button by aria-label")
            sent = True
        except Exception as e:
            logger.debug(f"[playwright] Send button aria-label failed: {e}")

    # 方法3: 按 Enter 键
    if not sent:
        try:
            await page.keyboard.press("Enter")
            print("[playwright] ✓ Pressed Enter to send")
            logger.info("[playwright] ✓ Pressed Enter to send")
            sent = True
        except Exception as e:
            logger.debug(f"[playwright] Enter key failed: {e}")

    if not sent:
        logger.error("[playwright] Could not send message")
        return []

    # ===== 步骤4: 等待图片生成 =====
    print("[playwright] Step 4: Waiting for image generation...")
    logger.info("[playwright] Step 4: Waiting for image generation...")

    # ChatGPT 生成图片需要时间，先等待一段时间让生成开始
    print("[playwright] Waiting 20s for generation to start...")
    await page.wait_for_timeout(20000)

    max_wait = 180  # 最多等待180秒（3分钟）
    waited = 20  # 已经等了20秒
    check_interval = 5  # 每5秒检查一次
    new_images_found = False
    last_large_count = 0
    stable_count = 0  # 连续几次检查图片数量不变

    while waited < max_wait:
        await page.wait_for_timeout(check_interval * 1000)
        waited += check_interval

        # 滚动到页面底部确保加载最新内容
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1000)

        # 检查所有大图片（使用 ChatGPT 特定的选择器）
        try:
            # ChatGPT 生成的图片有特定的 class 和结构
            all_images = await page.query_selector_all("img")
            large_images = []

            for img in all_images:
                try:
                    info = await img.evaluate("""el => {
                        const rect = el.getBoundingClientRect();
                        return {
                            width: rect.width || el.naturalWidth || el.width || 0,
                            height: rect.height || el.naturalHeight || el.height || 0,
                            src: el.src || '',
                            alt: el.alt || '',
                            className: el.className || ''
                        };
                    }""")
                    # ChatGPT 生成的图片通常是竖屏，尺寸较大
                    # 检查是否包含 chatgpt.com/backend-api/estuary/content 的 URL
                    is_chatgpt_image = False
                    if info['width'] >= 300 and info['height'] >= 300:
                        if 'chatgpt.com/backend-api/estuary/content' in info['src']:
                            is_chatgpt_image = True
                        elif '已生成图片' in info['alt']:
                            is_chatgpt_image = True
                        elif 'absolute' in info['className'] and 'z-1' in info['className']:
                            is_chatgpt_image = True
                        elif 'chatgpt.com' in info['src'] and info['width'] >= 500 and info['height'] >= 500:
                            is_chatgpt_image = True
                    
                    # 打印所有大图片的详细信息用于调试
                    if info['width'] >= 200 and info['height'] >= 200:
                        print(f"[playwright] Check image: {info['width']}x{info['height']}, alt: '{info['alt']}', class: '{info['className'][:60]}', src: {info['src'][:80]}..., is_chatgpt: {is_chatgpt_image}")
                    
                    if is_chatgpt_image:
                        large_images.append(img)
                        print(f"[playwright] ✓ Detected ChatGPT image: {info['width']}x{info['height']}")
                except Exception as e:
                    print(f"[playwright] Error checking image: {e}")

            current_count = len(large_images)
            print(f"[playwright] Found {current_count} ChatGPT images after {waited}s")

            # 检测图片数量是否稳定（连续3次相同说明生成完成）
            if current_count > 0:
                if current_count == last_large_count:
                    stable_count += 1
                    if stable_count >= 3:  # 连续3次数量相同，认为生成完成
                        print(f"[playwright] Image generation stable after {waited}s, found {current_count} images")
                        logger.info(f"[playwright] Image generation stable, found {current_count} images")
                        new_images_found = True
                        # 再等待10秒确保图片完全渲染
                        await page.wait_for_timeout(10000)
                        break
                else:
                    stable_count = 0
                    last_large_count = current_count

        except Exception as e:
            logger.debug(f"[playwright] Error checking images: {e}")

        if waited % 15 == 0:
            print(f"[playwright] Still waiting... {waited}s")
            logger.info(f"[playwright] Still waiting for images... {waited}s")

    print(f"[playwright] Total waited: {waited}s, new images found: {new_images_found}")
    logger.info(f"[playwright] Total waited: {waited}s, new images found: {new_images_found}")

    # ===== 步骤5: 下载生成的图片 =====
    if not new_images_found:
        print("[playwright] ⚠ No images detected, but will try to download anyway...")
        logger.warning("[playwright] No images detected, but will try to download anyway")

    print("[playwright] Step 5: Downloading images...")
    logger.info("[playwright] Step 5: Downloading images...")
    downloaded_files = await _download_chatgpt_images(page, download_dir)

    print(f"[playwright] ===== ChatGPT workflow completed, downloaded: {len(downloaded_files)} files =====")
    logger.info(f"[playwright] ===== ChatGPT workflow completed, downloaded: {len(downloaded_files)} files =====")
    return downloaded_files


async def _download_chatgpt_images(page, download_dir: Path) -> list[str]:
    """下载 ChatGPT 生成的图片 - 下载所有大图片"""
    downloaded = []

    try:
        # 获取所有图片
        all_images = await page.query_selector_all("img")
        print(f"[playwright] Total images on page: {len(all_images)}")

        # 只保留 ChatGPT 生成的大图片
        large_images = []
        for img in all_images:
            try:
                info = await img.evaluate("""el => {
                    const rect = el.getBoundingClientRect();
                    return {
                        width: rect.width || el.naturalWidth || el.width || 0,
                        height: rect.height || el.naturalHeight || el.height || 0,
                        src: el.src || '',
                        alt: el.alt || '',
                        className: el.className || ''
                    };
                }""")
                # 调试：打印所有大图片的信息
                if info['width'] >= 200 and info['height'] >= 200:
                    print(f"[playwright] Image found: {info['width']}x{info['height']}, src: {info['src'][:80]}...")

                # ChatGPT 生成的图片特征 - 更宽松的检测
                is_chatgpt_image = False
                if info['width'] >= 300 and info['height'] >= 300:
                    # 检查是否是 ChatGPT 生成的图片
                    if 'chatgpt.com/backend-api/estuary/content' in info['src']:
                        is_chatgpt_image = True
                    elif '已生成图片' in info['alt']:
                        is_chatgpt_image = True
                    elif 'absolute' in info['className'] and 'z-1' in info['className']:
                        is_chatgpt_image = True
                    # 如果没有匹配到特定特征，但尺寸很大且是 ChatGPT 域名，也认为是生成的图片
                    elif 'chatgpt.com' in info['src'] and info['width'] >= 500 and info['height'] >= 500:
                        is_chatgpt_image = True
                
                print(f"[playwright] Check image: {info['width']}x{info['height']}, src: {info['src'][:60]}..., alt: '{info['alt']}', class: '{info['className'][:50]}', is_chatgpt: {is_chatgpt_image}")
                if is_chatgpt_image:
                    large_images.append(img)
            except Exception as e:
                print(f"[playwright] Error getting image info: {e}")

        print(f"[playwright] Found {len(large_images)} ChatGPT images")
        logger.info(f"[playwright] Found {len(large_images)} ChatGPT images")

        # 只取最新的 2-4 张图片
        large_images = large_images[-4:] if len(large_images) > 4 else large_images

        img_index = 0
        for img in large_images:
            try:
                # 获取图片信息
                info = await img.evaluate("""el => {
                    const rect = el.getBoundingClientRect();
                    return {
                        width: rect.width || el.naturalWidth || el.width || 0,
                        height: rect.height || el.naturalHeight || el.height || 0,
                        src: el.src || '',
                        visible: rect.width > 0 && rect.height > 0
                    };
                }""")

                print(f"[playwright] Processing image: {info['width']}x{info['height']}, src: {info['src'][:50]}...")

                # 只处理大图片（>300px）
                if info['width'] >= 300 and info['height'] >= 300:
                    img_index += 1
                    dest_path = download_dir / f"chatgpt_image_{img_index}.jpg"

                    # ChatGPT 图片是 HTTP URL，使用 Playwright 的 page.request 下载（带 cookies）
                    if info['src'].startswith('http') and 'chatgpt.com/backend-api/estuary/content' in info['src']:
                        try:
                            print(f"[playwright] Downloading ChatGPT image via page.request...")
                            response = await page.request.get(info['src'])
                            if response.ok:
                                data = await response.body()
                                with open(dest_path, 'wb') as f:
                                    f.write(data)

                                if dest_path.exists() and dest_path.stat().st_size > 10000:
                                    print(f"[playwright] ✓ Downloaded image {img_index}: {dest_path.name} ({dest_path.stat().st_size} bytes)")
                                    logger.info(f"[playwright] Downloaded image {img_index}: {dest_path.name} ({dest_path.stat().st_size} bytes)")
                                    downloaded.append(str(dest_path))
                                    continue
                                else:
                                    dest_path.unlink(missing_ok=True)
                            else:
                                print(f"[playwright] page.request failed with status: {response.status}")
                        except Exception as e:
                            print(f"[playwright] page.request download failed: {e}")

                    # 策略2: 如果是 Blob URL 或 HTTP 下载失败，使用 Canvas 提取
                    if not dest_path.exists() or dest_path.stat().st_size <= 10000:
                        print(f"[playwright] Image {img_index} trying Canvas extraction...")
                        try:
                            await img.scroll_into_view_if_needed()
                            await page.wait_for_timeout(500)

                            img_data = await img.evaluate("""el => {
                                return new Promise((resolve, reject) => {
                                    try {
                                        const canvas = document.createElement('canvas');
                                        canvas.width = el.naturalWidth || el.width || 1024;
                                        canvas.height = el.naturalHeight || el.height || 1024;
                                        const ctx = canvas.getContext('2d');
                                        ctx.drawImage(el, 0, 0);
                                        resolve(canvas.toDataURL('image/jpeg', 0.95));
                                    } catch (e) {
                                        reject(e.toString());
                                    }
                                });
                            }""")

                            if img_data and img_data.startswith('data:image'):
                                header, encoded = img_data.split(',', 1)
                                data = base64.b64decode(encoded)

                                with open(dest_path, 'wb') as f:
                                    f.write(data)

                                if dest_path.exists() and dest_path.stat().st_size > 10000:
                                    print(f"[playwright] ✓ Extracted image {img_index}: {dest_path.name} ({dest_path.stat().st_size} bytes)")
                                    logger.info(f"[playwright] Extracted image {img_index}: {dest_path.name} ({dest_path.stat().st_size} bytes)")
                                    downloaded.append(str(dest_path))
                                    continue
                                else:
                                    dest_path.unlink(missing_ok=True)
                        except Exception as e:
                            print(f"[playwright] Canvas extraction failed: {e}")

            except Exception as e:
                logger.debug(f"[playwright] Failed to process image: {e}")

        print(f"[playwright] Total downloaded: {len(downloaded)} images")
        logger.info(f"[playwright] Total downloaded: {len(downloaded)} images")

    except Exception as e:
        logger.error(f"[playwright] Error downloading images: {e}")
        print(f"[playwright] Error downloading images: {e}")

    return downloaded


async def generate_ai_cover_playwright(
    job_id: str,
    title: str,
    description: str = "",
    platforms: Optional[list[str]] = None,
) -> dict:
    """
    使用 Playwright 生成 AI 封面图

    Args:
        job_id: 任务 ID
        title: 视频标题
        description: 视频描述（可选）
        platforms: 平台列表，如 ["gemini", "chatgpt"]

    Returns:
        {"status": "success", "images": [...], "prompt": "..."}
    """
    platforms = platforms or ["gemini"]
    prompt = _build_prompt(title, description)

    job_dir = get_job_dir(job_id)
    output_dir = job_dir / "ai_covers"
    output_dir.mkdir(parents=True, exist_ok=True)

    download_dir = AI_COVER_DOWNLOAD_DIR
    download_dir.mkdir(parents=True, exist_ok=True)

    all_images = []
    last_error = None

    print(f"[playwright] Prompt: {prompt[:100]}...")

    for platform in platforms:
        logger.info(f"[playwright] Generating cover for {platform}: {title}")
        print(f"[playwright] Generating cover for {platform}: {title}")

        try:
            downloaded = await _generate_with_playwright(
                job_id=job_id,
                platform=platform,
                prompt=prompt,
                output_dir=output_dir,
                download_dir=download_dir,
            )
            print(f"[playwright] Downloaded files: {downloaded}")

            for idx, src_path in enumerate(downloaded):
                src = Path(src_path)
                if not src.exists():
                    continue

                dest_name = f"{platform}_cover_{idx + 1}.jpg"
                dest_path = output_dir / dest_name

                if _convert_and_save_image(src, dest_path):
                    all_images.append({
                        "filename": dest_name,
                        "path": str(dest_path),
                        "platform": platform,
                    })
                    logger.info(f"[playwright] Saved cover: {dest_name}")

        except Exception as exc:
            error_msg = str(exc)
            logger.error(f"[playwright] Failed to generate cover for {platform}: {error_msg}")
            last_error = error_msg
            continue

    # 保存发布草稿
    if all_images:
        save_publish_draft(
            job_id=job_id,
            draft={
                "title": title,
                "description": description,
                "covers": all_images,
            },
        )

    if all_images:
        return {
            "status": "success",
            "images": all_images,
            "prompt": prompt,
        }
    else:
        return {
            "status": "failed",
            "images": [],
            "prompt": prompt,
            "error": last_error or "No images generated",
        }
