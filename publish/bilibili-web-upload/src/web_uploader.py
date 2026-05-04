# -*- coding: utf-8 -*-
"""B站网页投稿模块 - 通过Playwright模拟浏览器操作上传视频到B站创作中心."""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from playwright.async_api import Playwright, async_playwright, Page

from conf import (
    LOCAL_CHROME_PATH,
    HEADLESS,
    COOKIE_FILE,
    VIDEO_DIR,
    DEFAULT_CATEGORY,
    DEFAULT_COPYRIGHT,
    LOG_DIR,
)
from .web_logger import bilibili_web_logger as logger


async def bilibili_cookie_gen(account_file: str):
    """打开浏览器让用户扫码登录，保存cookie."""
    async with async_playwright() as playwright:
        options = {
            'args': ['--lang zh-CN'],
            'headless': HEADLESS,
            'executable_path': LOCAL_CHROME_PATH or None,
        }
        browser = await playwright.chromium.launch(**options)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(
            "https://www.bilibili.com",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        for _ in range(120):
            await page.wait_for_timeout(3000)
            if await page.get_by_text('登录').count() == 0:
                await context.storage_state(path=account_file)
                await browser.close()
                logger.success("cookie saved")
                return True
        await context.storage_state(path=account_file)
        await browser.close()
        logger.warning("登录等待超时，已保存当前 cookie，请检查是否登录成功")
        return False


async def cookie_auth(account_file: str) -> bool:
    """验证cookie是否有效."""
    if not Path(account_file).exists():
        return False

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=HEADLESS,
            executable_path=LOCAL_CHROME_PATH or None,
        )
        context = await browser.new_context(storage_state=account_file)
        try:
            page = await context.new_page()
            await page.goto(
                "https://api.bilibili.com/x/web-interface/nav",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            try:
                nav = await page.text_content("body")
                data = json.loads(nav or "{}")
                if data.get("code") == 0 and data.get("data", {}).get("isLogin"):
                    logger.success("[+] cookie 有效")
                    return True
            except Exception:
                pass

            await page.goto(
                "https://member.bilibili.com/platform/upload/video/frame",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            await page.wait_for_timeout(timeout=5000)

            if await page.get_by_text('登录').count():
                logger.error("cookie 失效")
                return False
            logger.success("[+] cookie 有效")
            return True
        finally:
            await context.close()
            await browser.close()


async def bilibili_setup(account_file: str, handle: bool = False) -> bool:
    """检查并初始化登录状态."""
    if not Path(account_file).exists() or not await cookie_auth(account_file):
        if not handle:
            return False
        logger.error("cookie文件不存在或已失效，即将自动打开浏览器，请扫码登录")
        await bilibili_cookie_gen(account_file)
        return await cookie_auth(account_file)
    return True


class BilibiliWebVideo:
    """B站网页投稿类.

    使用Playwright模拟浏览器操作，完成视频上传和投稿。

    Attributes:
        title: 视频标题(最多80字符)
        file_path: 视频文件路径
        tags: 标签列表(最多12个，每个最多20字符)
        publish_date: 发布时间，0为立即发布，datetime对象为定时发布
        account_file: cookie文件路径
        category: 分区，如 vlog, game 等
        copyright: 1=自制, 2=转载
        description: 视频简介
        thumbnail_path: 封面图路径
    """

    def __init__(
        self,
        title: str,
        file_path: str,
        tags: Optional[List[str]] = None,
        publish_date: Optional[datetime] = None,
        account_file: Optional[str] = None,
        category: str = DEFAULT_CATEGORY,
        copyright: int = DEFAULT_COPYRIGHT,
        description: str = "",
        thumbnail_path: Optional[str] = None,
        headless: bool = None,
        local_chrome_path: str = None,
        dry_run: bool = False,
    ):
        self.title = title
        self.file_path = file_path
        self.tags = tags or []
        self.publish_date = publish_date
        self.account_file = account_file or str(COOKIE_FILE)
        self.category = category
        self.copyright = copyright
        self.description = description
        self.thumbnail_path = thumbnail_path
        self.headless = headless if headless is not None else HEADLESS
        self.local_executable_path = local_chrome_path or LOCAL_CHROME_PATH
        self.dry_run = dry_run
        self.file_path = str(Path(self.file_path).expanduser().resolve())
        if not Path(self.file_path).exists():
            raise FileNotFoundError(f"视频文件不存在: {self.file_path}")
        if self.thumbnail_path:
            self.thumbnail_path = str(Path(self.thumbnail_path).expanduser().resolve())
            if not Path(self.thumbnail_path).exists():
                raise FileNotFoundError(f"封面文件不存在: {self.thumbnail_path}")
        Path(self.account_file).expanduser().parent.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)

    def _screenshot_path(self, name: str) -> str:
        return str(LOG_DIR / name)

    async def open_upload_page(self, page: Page):
        """打开B站创作中心上传页面."""
        target_url = "https://member.bilibili.com/platform/upload/video/frame"
        last_error = None
        for _ in range(2):
            try:
                await page.goto(target_url, timeout=120000, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)
                if "member.bilibili.com" in page.url:
                    return
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"打开B站上传页面失败，最后错误: {last_error}")

    async def set_video_file(self, page: Page):
        """设置要上传的视频文件."""
        logger.info("【步骤1/6】等待上传组件加载...")

        # 先输出当前页面所有 input[type='file'] 的信息
        try:
            input_info = await page.evaluate("""
                () => {
                    const inputs = document.querySelectorAll('input[type="file"]');
                    return Array.from(inputs).map((input, i) => ({
                        index: i,
                        accept: input.accept,
                        name: input.name,
                        style: input.style.cssText,
                        parentClass: input.parentElement ? input.parentElement.className : null,
                        parentId: input.parentElement ? input.parentElement.id : null,
                        display: window.getComputedStyle(input).display,
                        visibility: window.getComputedStyle(input).visibility,
                    }));
                }
            """)
            logger.info(f"【调试】页面中的文件输入框信息: {input_info}")
        except Exception as exc:
            logger.warning(f"【调试】获取输入框信息失败: {exc}")

        # 先等待上传区域出现，说明页面组件已加载
        upload_area_selectors = [
            "div[id^='b-uploader-input-container']",
            "input[name='buploader']",
            "div.bcc-upload-wrapper",
            "div.upload-area",
            "div[class*='upload']",
        ]
        upload_area_found = False
        for selector in upload_area_selectors:
            try:
                await page.locator(selector).first.wait_for(state="attached", timeout=15000)
                logger.info(f"【步骤2/6】上传区域已加载: {selector}")
                upload_area_found = True
                break
            except Exception:
                continue

        if not upload_area_found:
            logger.warning("【警告】未检测到上传区域，继续尝试查找文件输入框")

        # 方法1: 使用 Playwright 的文件选择器拦截功能
        # B站新组件需要点击 input 触发文件选择器，然后设置文件
        logger.info("【步骤3/6】尝试使用文件选择器拦截方式上传...")
        try:
            # 找到上传按钮/区域
            upload_button_selectors = [
                "div[id^='b-uploader-input-container']",
                "input[name='buploader']",
                "div.bcc-upload-wrapper",
                "div.upload-area",
                "button:has-text('上传视频')",
                "div:has-text('点击上传'):has(~ input[type='file'])",
            ]

            for btn_selector in upload_button_selectors:
                btn_locator = page.locator(btn_selector).first
                try:
                    await btn_locator.wait_for(state="attached", timeout=5000)
                    logger.info(f"【步骤4/6】找到上传按钮/区域: {btn_selector}")

                    # 使用 expect_file_chooser 拦截文件选择器
                    async with page.expect_file_chooser(timeout=10000) as fc_info:
                        logger.info(f"【步骤5/6】点击上传按钮/区域: {btn_selector}")
                        await btn_locator.click(timeout=5000)

                    file_chooser = await fc_info.value
                    logger.info(f"【步骤6/6】文件选择器已弹出，设置文件: {self.file_path}")
                    await file_chooser.set_files(self.file_path)
                    logger.info("【成功】文件已通过文件选择器设置")
                    return
                except Exception as exc:
                    logger.warning(f"【失败】选择器 {btn_selector} 文件选择器方式失败: {exc}")
                    continue
        except Exception as exc:
            logger.warning(f"【失败】文件选择器拦截方式失败: {exc}")

        # 方法2: 直接设置 input[type='file']（旧组件或备用方式）
        logger.info("【降级】尝试直接设置 input[type='file']...")
        file_input_selectors = [
            "input[name='buploader'][accept*='mp4']",
            "input[name='buploader']",
            "div[id^='b-uploader-input-container'] input[type='file']",
            "div.bcc-upload-wrapper input[type='file']",
            "div.upload-area input[type='file']",
            "input[type='file'][accept*='video']",
            "input[type='file'][accept*='mp4']",
            "input[type='file']",
        ]

        last_error = None
        for selector in file_input_selectors:
            locator = page.locator(selector)
            try:
                await locator.first.wait_for(state="attached", timeout=10000)
                count = await locator.count()
                logger.info(f"【降级】选择器 {selector} 找到 {count} 个元素")
                if count == 0:
                    continue
                for index in range(count):
                    target = locator.nth(index)
                    try:
                        logger.info(f"【降级】尝试对 {selector}[{index}] 设置文件")
                        await target.set_input_files(self.file_path, timeout=10000)
                        logger.info(f"【降级成功】已命中文件上传输入框: {selector}[{index}]")
                        return
                    except Exception as exc:
                        last_error = exc
                        logger.warning(f"【降级失败】选择器 {selector}[{index}] 设置文件失败: {exc}")
            except Exception as exc:
                last_error = exc
                logger.warning(f"【降级失败】选择器 {selector} 未找到: {exc}")

        screenshot_path = self._screenshot_path("bilibili_upload_timeout.png")
        try:
            await page.screenshot(path=screenshot_path, full_page=True)
            logger.info(f"【调试】已保存截图: {screenshot_path}")
        except Exception:
            pass

        raise RuntimeError(f"未找到B站视频上传 input，最后错误: {last_error}")

    async def wait_video_uploaded(self, page: Page):
        """等待视频上传完成，页面跳转到编辑页面."""
        logger.info("【等待上传】开始等待视频上传完成...")
        for i in range(300):
            await page.wait_for_timeout(2000)

            # 检查是否已进入编辑页面（有标题输入框）
            try:
                title_input = page.locator("input[placeholder*='稿件标题']")
                title_count = await title_input.count()
                if title_count > 0:
                    logger.success("【等待上传】检测到标题输入框，视频上传完成，页面已跳转")
                    return True
            except Exception as e:
                logger.debug(f"【等待上传】检查标题输入框失败: {e}")

            # 检查页面状态文本
            try:
                page_text = await page.content()
                uploading_texts = ["上传中", "上传完成", "处理中", "转码中", "封面上传中", "视频信息"]
                found_status = []
                for text in uploading_texts:
                    if text in page_text:
                        found_status.append(text)
                if found_status:
                    logger.info(f"【等待上传】第 {i*2} 秒 - 页面状态: {', '.join(found_status)}")
                else:
                    logger.info(f"【等待上传】第 {i*2} 秒 - 未检测到上传状态文本")

                # 如果页面已经包含"视频信息"但还没有标题输入框，可能页面结构变了
                if "视频信息" in page_text and i > 5:
                    logger.info("【等待上传】检测到'视频信息'，页面可能已经跳转但结构不同")
                    # 尝试查找其他编辑页面的特征
                    edit_indicators = [
                        "div[class*='video-info']",
                        "div[class*='edit']",
                        "input[class*='input']",
                        "textarea",
                    ]
                    for indicator in edit_indicators:
                        try:
                            indicator_count = await page.locator(indicator).count()
                            if indicator_count > 0:
                                logger.info(f"【等待上传】找到编辑页面指示器: {indicator} ({indicator_count}个)")
                                return True
                        except Exception:
                            pass
            except Exception as e:
                logger.debug(f"【等待上传】检查页面文本失败: {e}")

        logger.warning("【等待上传】等待上传超时，继续尝试后续步骤...")
        return True

    async def set_title(self, page: Page):
        """填写视频标题."""
        title = self.title[:80]
        selectors = [
            "input[placeholder*='稿件标题']",
            "input[maxlength='80']",
            "input.input-val",
            "div.input-instance input",
        ]
        last_error = None
        for selector in selectors:
            locator = page.locator(selector)
            try:
                count = await locator.count()
                if count == 0:
                    continue
                await locator.first.fill(title, timeout=5000)
                logger.info(f"已设置标题: {title}")
                return
            except Exception as exc:
                last_error = exc
                try:
                    await locator.first.click(timeout=1000)
                    await page.keyboard.press("Control+A")
                    await page.keyboard.insert_text(title)
                    logger.info(f"已设置标题(键盘): {title}")
                    return
                except Exception as fallback_exc:
                    last_error = fallback_exc

        screenshot_path = self._screenshot_path("bilibili_title_timeout.png")
        try:
            await page.screenshot(path=screenshot_path, full_page=True)
        except Exception:
            pass
        raise RuntimeError(f"未找到B站标题输入框，最后错误: {last_error}")

    async def set_description(self, page: Page):
        """填写视频简介/描述."""
        description = self.description or self.title
        selectors = [
            "div.ql-editor",
            "div[contenteditable='true']",
            "div.ql-blank",
            "div[placeholder*='相关信息']",
        ]
        last_error = None
        for selector in selectors:
            locator = page.locator(selector)
            try:
                count = await locator.count()
                if count == 0:
                    continue
                await locator.first.click(timeout=5000)
                await page.keyboard.press("Control+A")
                await page.keyboard.insert_text(description)
                logger.info("已设置简介/描述")
                return
            except Exception as exc:
                last_error = exc

        logger.warning("未找到描述输入框，跳过")
        return

    async def set_thumbnail(self, page: Page):
        """上传本地封面图."""
        if not self.thumbnail_path:
            return

        logger.info(f"准备上传封面: {self.thumbnail_path}")

        async def click_first_visible(candidates: list[tuple[str, object]], timeout: int = 5000) -> str | None:
            for label, locator in candidates:
                try:
                    await locator.first.wait_for(state="visible", timeout=timeout)
                    await locator.first.scroll_into_view_if_needed(timeout=3000)
                    await locator.first.click(force=True, timeout=3000)
                    return label
                except Exception:
                    continue
            return None

        clicked = await click_first_visible(
            [
                ("封面设置编辑文字", page.locator("span.edit-text").filter(has_text="封面设置")),
                ("封面设置文字", page.get_by_text("封面设置", exact=True)),
                ("封面设置按钮", page.locator("button").filter(has_text="封面设置")),
                ("封面区域", page.locator("div").filter(has_text="封面设置")),
            ],
            timeout=10000,
        )
        if not clicked:
            raise RuntimeError("未找到B站封面设置入口")
        logger.info(f"已点击封面入口: {clicked}")

        modal = page.locator(
            "div:has(div.upload-area), div[role='dialog']:has-text('上传封面'), div[class*='modal']:has-text('上传封面')"
        ).last
        try:
            await modal.wait_for(state="visible", timeout=15000)
        except Exception:
            logger.warning("未检测到封面弹窗，尝试直接在页面中查找封面上传控件")
            modal = page

        file_input = modal.locator(
            "input[type='file'][accept*='image'], input[type='file'][accept*='jpg'], input[type='file'][accept*='png']"
        ).first
        if not await file_input.count() and modal is not page:
            file_input = page.locator(
                "input[type='file'][accept*='image'], input[type='file'][accept*='jpg'], input[type='file'][accept*='png']"
        ).first
        await file_input.wait_for(state="attached", timeout=10000)
        await file_input.set_input_files(self.thumbnail_path)
        logger.info("封面图片已经提交给页面")
        await page.wait_for_timeout(3000)

        confirm_clicked = await click_first_visible(
            [
                ("完成提交div", page.locator("div.button.submit").filter(has_text="完成")),
                ("完成提交class", page.locator("div[class~='button'][class~='submit']").filter(has_text="完成")),
                ("弹窗完成提交div", modal.locator("div.button.submit").filter(has_text="完成")),
                ("弹窗完成提交class", modal.locator("div[class~='button'][class~='submit']").filter(has_text="完成")),
                ("完成按钮", page.locator("button").filter(has_text="完成")),
                ("确定按钮", page.locator("button").filter(has_text="确定")),
                ("保存按钮", page.locator("button").filter(has_text="保存")),
                ("提交按钮", page.locator("button").filter(has_text="提交")),
                ("使用按钮", page.locator("button").filter(has_text="使用")),
            ],
            timeout=8000,
        )
        if confirm_clicked:
            logger.info(f"已确认封面设置: {confirm_clicked}")
            if modal is not page:
                try:
                    await modal.wait_for(state="hidden", timeout=10000)
                except Exception:
                    logger.warning("封面弹窗未自动关闭，继续后续投稿流程")
            await page.wait_for_timeout(1500)
        else:
            logger.warning("封面已上传，但未找到确认按钮，继续后续投稿流程")

    async def set_copyright_and_category(self, page: Page):
        """设置创作类型(自制/转载)和分区."""
        try:
            target_name = "自制" if self.copyright == 1 else "转载"
            candidates = [
                page.locator(f"span.check-radio-v2-name:has-text('{target_name}')"),
                page.get_by_text(target_name, exact=True),
            ]
            for locator in candidates:
                if await locator.count() == 0:
                    continue
                await locator.first.click(timeout=3000)
                logger.info(f"已选择{target_name}")
                break
        except Exception as exc:
            logger.warning(f"设置类型失败: {exc}")

        try:
            if self.category:
                current = page.locator("p.select-item-cont, p.select-item-cont-inserted").first
                if await current.count() == 0:
                    logger.warning("未找到分区控件，跳过")
                    return
                current_text = (await current.inner_text(timeout=3000)).strip().lower()
                if self.category.lower() in current_text:
                    logger.info(f"当前分区已是: {current_text}")
                    return

                await current.click(timeout=3000)
                await page.wait_for_timeout(800)
                option_candidates = [
                    page.locator(f"p:has-text('{self.category}')"),
                    page.locator(f"li:has-text('{self.category}')"),
                    page.locator(f"div:has-text('{self.category}')"),
                    page.get_by_text(self.category, exact=False),
                ]
                for option in option_candidates:
                    if await option.count() == 0:
                        continue
                    await option.first.click(timeout=3000)
                    logger.info(f"已选择分区: {self.category}")
                    return
                logger.warning(f"未找到分区选项: {self.category}，保留当前分区: {current_text}")
        except Exception as exc:
            logger.warning(f"设置分区失败: {exc}")

    async def set_tags(self, page: Page):
        """添加视频标签."""
        if not self.tags:
            return
        try:
            tag_locator = page.locator("input[placeholder*='回车键']")
            if await tag_locator.count() > 0:
                for tag in self.tags[:12]:
                    tag_text = tag[:20]
                    await tag_locator.first.fill(tag_text)
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(500)
                logger.info(f"已设置标签: {self.tags[:12]}")
        except Exception as exc:
            logger.warning(f"设置标签失败: {exc}")

    async def dismiss_popups(self, page: Page):
        """关闭可能的弹窗."""
        dismiss_texts = [
            "暂不设置", "跳过", "取消", "关闭", "知道了", "我知道了",
            "以后再说", "稍后", "下次再说", "暂不授权"
        ]
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(200)
        except Exception:
            pass
        for text in dismiss_texts:
            try:
                locator = page.locator(f"button:has-text('{text}')").last
                if await locator.count():
                    await locator.click(timeout=1000)
                    await page.wait_for_timeout(300)
            except Exception:
                continue

    async def click_submit(self, page: Page):
        """点击立即投稿按钮."""
        last_error = None
        submit_selectors = [
            "span.submit-add:has-text('立即投稿')",
            "span.submit-add",
            "[data-reporter-id='94']:has-text('立即投稿')",
            "button:has-text('立即投稿')",
            "span:has-text('立即投稿')",
        ]

        for selector in submit_selectors:
            locator = page.locator(selector)
            try:
                count = await locator.count()
                if count == 0:
                    continue
                await page.mouse.wheel(0, 2000)
                await page.wait_for_timeout(500)
                await locator.first.scroll_into_view_if_needed(timeout=3000)
                await locator.first.click(timeout=5000)
                logger.info("已点击立即投稿")
                return
            except Exception as exc:
                last_error = exc
                continue

        screenshot_path = self._screenshot_path("bilibili_submit_timeout.png")
        try:
            await page.screenshot(path=screenshot_path, full_page=True)
        except Exception:
            pass
        raise RuntimeError(f"未找到投稿按钮，最后错误: {last_error}")

    async def wait_publish_success(self, page: Page):
        """等待发布成功."""
        success_texts = [
            "发布成功", "投稿成功", "提交成功", "审核中", "已发布", "发布成功!"
        ]
        for _ in range(60):
            try:
                for text in success_texts:
                    if await page.get_by_text(text, exact=False).count():
                        logger.success(f"检测到: {text}")
                        return
            except Exception:
                pass
            current_url = page.url
            if "success" in current_url.lower() or ("upload" not in current_url and "frame" not in current_url):
                logger.success("投稿完成")
                return
            await page.wait_for_timeout(1000)
        logger.warning("未检测到明确的成功状态")

    async def upload(self, playwright: Playwright) -> dict:
        """执行上传流程."""
        result = {"success": False, "message": ""}

        browser = await playwright.chromium.launch(
            headless=self.headless,
            executable_path=self.local_executable_path,
        )
        context = await browser.new_context(
            storage_state=self.account_file,
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.150 Safari/537.36',
            viewport={"width": 1920, "height": 1080}
        )

        page = await context.new_page()
        logger.info(f"开始上传: {self.file_path}")

        try:
            await self.open_upload_page(page)
            await self.set_video_file(page)
            await self.wait_video_uploaded(page)

            # 上传完成后，等待页面完全加载稳定
            logger.info("【上传完成】等待页面稳定...")
            await page.wait_for_timeout(3000)

            await self.dismiss_popups(page)
            await self.set_title(page)
            await self.set_description(page)
            await self.set_thumbnail(page)
            await self.set_copyright_and_category(page)
            await self.set_tags(page)

            if self.dry_run:
                await page.screenshot(
                    path=self._screenshot_path("bilibili_dry_run_ready.png"),
                    full_page=True,
                )
                result["success"] = True
                result["message"] = "模拟上传完成：已上传视频并填写投稿信息，未点击立即投稿"
                logger.success(result["message"])
                return result

            await self.dismiss_popups(page)
            await self.click_submit(page)
            await self.wait_publish_success(page)

            await context.storage_state(path=self.account_file)
            logger.info('cookie更新完毕')

            result["success"] = True
            result["message"] = "视频发布成功"

        except Exception as exc:
            result["message"] = str(exc)
            logger.error(f"上传失败: {exc}")
            try:
                await page.screenshot(
                    path=self._screenshot_path("bilibili_upload_error.png"),
                    full_page=True,
                )
            except Exception:
                pass

        finally:
            # 只有非预览模式且非出错时才自动关闭浏览器
            # 如果上传过程中出错，保持浏览器打开方便调试
            if not self.dry_run and result["success"]:
                logger.info("上传成功，2秒后关闭浏览器...")
                await asyncio.sleep(2)
                await context.close()
                await browser.close()
            elif not self.dry_run and not result["success"]:
                logger.error("上传失败，保持浏览器打开30秒以便查看错误...")
                await asyncio.sleep(30)
                logger.info("关闭浏览器")
                await context.close()
                await browser.close()

        if self.dry_run:
            logger.success("预览模式：浏览器保持打开，请在确认后手动关闭")
            return result

        logger.success("视频发布完成")
        return result

    async def run(self) -> dict:
        """运行上传任务."""
        async with async_playwright() as playwright:
            return await self.upload(playwright)

    def run_sync(self) -> dict:
        """同步方式运行上传任务."""
        return asyncio.run(self.run())
