# -*- coding: utf-8 -*-
import asyncio
from datetime import datetime
from pathlib import Path

from playwright.async_api import Playwright, async_playwright, Page

from conf import LOCAL_CHROME_PATH, LOCAL_CHROME_HEADLESS
from utils.log import bilibili_logger


async def bilibili_cookie_gen(account_file):
    async with async_playwright() as playwright:
        options = {
            'args': ['--lang zh-CN'],
            'headless': LOCAL_CHROME_HEADLESS,
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
                bilibili_logger.success("cookie saved")
                return
        await context.storage_state(path=account_file)
        await browser.close()
        bilibili_logger.warning("登录等待超时，已保存当前 cookie，请检查是否登录成功")


async def cookie_auth(account_file):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=LOCAL_CHROME_HEADLESS,
            executable_path=LOCAL_CHROME_PATH or None,
        )
        context = await browser.new_context(storage_state=account_file)
        page = await context.new_page()
        await page.goto(
            "https://member.bilibili.com/platform/upload/video/frame",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        await page.wait_for_timeout(timeout=5000)

        if await page.get_by_text('登录').count():
            bilibili_logger.error("cookie 失效")
            return False
        else:
            bilibili_logger.success("[+] cookie 有效")
            return True


async def bilibili_setup(account_file, handle=False):
    if not Path(account_file).exists() or not await cookie_auth(account_file):
        if not handle:
            return False
        bilibili_logger.error("cookie文件不存在或已失效，即将自动打开浏览器，请扫码登录")
        await bilibili_cookie_gen(account_file)
    return True


class BilibiliWebVideo:
    def __init__(self, title, file_path, tags, publish_date: datetime, account_file, proxy_setting=None,
                 category: str = "vlog", copyright: int = 1):
        self.title = title
        self.file_path = file_path
        self.tags = tags or []
        self.publish_date = publish_date
        self.account_file = account_file
        self.date_format = '%Y年%m月%d日 %H:%M'
        self.local_executable_path = LOCAL_CHROME_PATH
        self.headless = LOCAL_CHROME_HEADLESS
        self.proxy_setting = proxy_setting
        self.category = category
        self.copyright = copyright  # 1=自制, 2=转载

    async def open_upload_page(self, page):
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

    async def set_video_file(self, page):
        selectors = [
            "input[type='file'][accept*='video']",
            "input[type='file'][accept*='mp4']",
            "input[type='file']",
            "input[accept*='video']",
        ]
        last_error = None
        for selector in selectors:
            locator = page.locator(selector)
            try:
                count = await locator.count()
                if count == 0:
                    continue
                for index in range(count):
                    target = locator.nth(index)
                    try:
                        await target.set_input_files(self.file_path, timeout=10000)
                        bilibili_logger.info(f"已命中文件上传输入框: {selector}[{index}]")
                        return
                    except Exception as exc:
                        last_error = exc
            except Exception as exc:
                last_error = exc

        screenshot_path = "logs/bilibili_upload_timeout.png"
        try:
            await page.screenshot(path=screenshot_path, full_page=True)
        except Exception:
            pass
        raise RuntimeError(f"未找到B站视频上传 input，最后错误: {last_error}")

    async def wait_video_uploaded(self, page):
        bilibili_logger.info("等待视频上传完成...")
        for _ in range(300):
            await page.wait_for_timeout(2000)
            try:
                title_input = page.locator("input[placeholder*='稿件标题']")
                if await title_input.count() > 0:
                    bilibili_logger.success("视频上传完成，页面已跳转")
                    return True
            except Exception:
                pass
            try:
                upload_area = page.locator("div.upload-area")
                if await upload_area.count() > 0:
                    uploading_texts = ["上传中", "上传完成", "处理中", "转码中"]
                    page_text = await page.content()
                    for text in uploading_texts:
                        if text in page_text:
                            bilibili_logger.info(f"状态: {text}...")
                            break
                    continue
            except Exception:
                pass
        bilibili_logger.warning("等待上传超时，继续尝试...")
        return True

    async def set_title(self, page):
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
                bilibili_logger.info(f"已设置标题: {title}")
                return
            except Exception as exc:
                last_error = exc
                try:
                    await locator.first.click(timeout=1000)
                    await page.keyboard.press("Control+A")
                    await page.keyboard.insert_text(title)
                    bilibili_logger.info(f"已设置标题(键盘): {title}")
                    return
                except Exception as fallback_exc:
                    last_error = fallback_exc

        screenshot_path = "logs/bilibili_title_timeout.png"
        try:
            await page.screenshot(path=screenshot_path, full_page=True)
        except Exception:
            pass
        raise RuntimeError(f"未找到B站标题输入框，最后错误: {last_error}")

    async def set_description(self, page):
        description = self.title
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
                bilibili_logger.info("已设置简介/描述")
                return
            except Exception as exc:
                last_error = exc

        bilibili_logger.warning("未找到描述输入框，跳过")
        return

    async def set_category(self, page):
        try:
            zizhi_locator = page.locator("span.check-radio-v2-name:text('自制')")
            if await zizhi_locator.count() > 0:
                if self.copyright == 1:
                    await zizhi_locator.click(timeout=3000)
                    bilibili_logger.info("已选择自制")
                else:
                    zhuanzai_locator = page.locator("span.check-radio-v2-name:text('转载')")
                    if await zhuanzai_locator.count() > 0:
                        await zhuanzai_locator.click(timeout=3000)
                        bilibili_logger.info("已选择转载")
        except Exception as exc:
            bilibili_logger.warning(f"设置类型失败: {exc}")

        try:
            category_selectors = [
                "p.select-item-cont:text('vlog')",
                "p.select-item-cont",
                "div[data-v-45bbfbca*='select-item-cont']",
            ]
            if self.category:
                for sel in category_selectors:
                    locator = page.locator(sel)
                    if await locator.count() > 0:
                        await locator.first.click(timeout=3000)
                        bilibili_logger.info(f"已选择分区: {self.category}")
                        break
        except Exception as exc:
            bilibili_logger.warning(f"设置分区失败: {exc}")

    async def set_tags(self, page):
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
                bilibili_logger.info(f"已设置标签: {self.tags[:12]}")
        except Exception as exc:
            bilibili_logger.warning(f"设置标签失败: {exc}")

    async def dismiss_popups(self, page):
        dismiss_texts = [
            "暂不设置", "跳过", "取消", "关闭", "知道了", "我知道了",
            "以后再说", "稍后", "下次再说"
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

    async def click_submit(self, page):
        last_error = None
        submit_selectors = [
            "span.submit-add:text('立即投稿')",
            "span.submit-add",
            "button[data-reporter-id]",
            "span:text('立即投稿')",
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
                bilibili_logger.info("已点击立即投稿")
                return
            except Exception as exc:
                last_error = exc
                continue

        screenshot_path = "logs/bilibili_submit_timeout.png"
        try:
            await page.screenshot(path=screenshot_path, full_page=True)
        except Exception:
            pass
        raise RuntimeError(f"未找到投稿按钮，最后错误: {last_error}")

    async def wait_publish_success(self, page):
        success_texts = [
            "发布成功", "投稿成功", "提交成功", "审核中", "已发布"
        ]
        for _ in range(60):
            try:
                for text in success_texts:
                    if await page.get_by_text(text, exact=False).count():
                        bilibili_logger.success(f"检测到: {text}")
                        return
            except Exception:
                pass
            current_url = page.url
            if "success" in current_url.lower() or "upload" not in current_url:
                bilibili_logger.success("投稿完成")
                return
            await page.wait_for_timeout(1000)
        bilibili_logger.warning("未检测到明确的成功状态")

    async def upload(self, playwright: Playwright) -> None:
        browser = await playwright.chromium.launch(
            headless=self.headless,
            executable_path=self.local_executable_path,
            proxy=self.proxy_setting
        )
        context = await browser.new_context(
            storage_state=str(self.account_file),
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.150 Safari/537.36',
            viewport={"width": 1920, "height": 1080}
        )

        page = await context.new_page()
        bilibili_logger.info(f"开始上传: {self.file_path}")

        await self.open_upload_page(page)
        await self.set_video_file(page)
        await self.wait_video_uploaded(page)

        await self.dismiss_popups(page)
        await self.set_title(page)
        await self.set_description(page)
        await self.set_category(page)
        await self.set_tags(page)

        await self.dismiss_popups(page)
        await self.click_submit(page)
        await self.wait_publish_success(page)

        await context.storage_state(path=self.account_file)
        bilibili_logger.info('cookie更新完毕')

        await asyncio.sleep(2)
        await context.close()
        await browser.close()
        bilibili_logger.success("视频发布完成")

    async def main(self):
        async with async_playwright() as playwright:
            await self.upload(playwright)
