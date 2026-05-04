# -*- coding: utf-8 -*-
from datetime import datetime

from playwright.async_api import Playwright, TimeoutError as PlaywrightTimeoutError, async_playwright
import os
import asyncio

from conf import LOCAL_CHROME_PATH, LOCAL_CHROME_HEADLESS
from utils.base_social_media import set_init_script
from utils.files_times import get_absolute_path
from utils.log import tencent_logger


def format_str_for_short_title(origin_title: str) -> str:
    # 定义允许的特殊字符
    allowed_special_chars = "《》“”:+?%°"

    # 移除不允许的特殊字符
    filtered_chars = [char if char.isalnum() or char in allowed_special_chars else ' ' if char == ',' else '' for
                      char in origin_title]
    formatted_string = ''.join(filtered_chars)

    # 调整字符串长度
    if len(formatted_string) > 16:
        # 截断字符串
        formatted_string = formatted_string[:16]
    elif len(formatted_string) < 6:
        # 使用空格来填充字符串
        formatted_string += ' ' * (6 - len(formatted_string))

    return formatted_string


async def cookie_auth(account_file):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=LOCAL_CHROME_HEADLESS,
            executable_path=LOCAL_CHROME_PATH or None,
        )
        context = await browser.new_context(storage_state=account_file)
        context = await set_init_script(context)
        # 创建一个新的页面
        page = await context.new_page()
        # 访问指定的 URL
        await page.goto("https://channels.weixin.qq.com/platform/post/create")
        try:
            await page.wait_for_selector('div.title-name:has-text("微信小店")', timeout=5000)  # 等待5秒
            tencent_logger.error("[+] 等待5秒 cookie 失效")
            return False
        except:
            tencent_logger.success("[+] cookie 有效")
            return True


async def get_tencent_cookie(account_file):
    async with async_playwright() as playwright:
        options = {
            'args': [
                '--lang en-GB'
            ],
            'headless': LOCAL_CHROME_HEADLESS,  # Set headless option here
            'executable_path': LOCAL_CHROME_PATH or None,
        }
        # Make sure to run headed.
        browser = await playwright.chromium.launch(**options)
        # Setup context however you like.
        context = await browser.new_context()  # Pass any options
        # Pause the page, and start recording manually.
        context = await set_init_script(context)
        page = await context.new_page()
        await page.goto("https://channels.weixin.qq.com")
        for _ in range(120):
            await page.wait_for_timeout(3000)
            if "/platform" in page.url:
                await context.storage_state(path=account_file)
                await browser.close()
                tencent_logger.success("[+] cookie saved")
                return
        await context.storage_state(path=account_file)
        await browser.close()
        tencent_logger.warning("[+] 登录等待超时，已保存当前 cookie，请检查是否登录成功")


async def weixin_setup(account_file, handle=False):
    account_file = get_absolute_path(account_file, "tencent_uploader")
    if not os.path.exists(account_file) or not await cookie_auth(account_file):
        if not handle:
            # Todo alert message
            return False
        tencent_logger.info('[+] cookie文件不存在或已失效，即将自动打开浏览器，请扫码登录，登陆后会自动生成cookie文件')
        await get_tencent_cookie(account_file)
    return True


class TencentVideo(object):
    def __init__(
        self,
        title,
        file_path,
        tags,
        publish_date: datetime,
        account_file,
        category=None,
        is_draft=False,
        is_preview=False,
        thumbnail_path=None,
    ):
        self.title = title  # 视频标题
        self.file_path = file_path
        self.tags = tags
        self.publish_date = publish_date
        self.account_file = account_file
        self.category = category
        self.thumbnail_path = thumbnail_path
        self.headless = LOCAL_CHROME_HEADLESS
        self.is_draft = is_draft  # 是否保存为草稿
        self.is_preview = is_preview  # 是否预览模式（停在页面等待用户手动操作）
        self.local_executable_path = LOCAL_CHROME_PATH or None

    async def set_schedule_time_tencent(self, page, publish_date):
        label_element = page.locator("label").filter(has_text="定时").nth(1)
        await label_element.click()

        await page.click('input[placeholder="请选择发表时间"]')

        str_month = str(publish_date.month) if publish_date.month > 9 else "0" + str(publish_date.month)
        current_month = str_month + "月"
        # 获取当前的月份
        page_month = await page.inner_text('span.weui-desktop-picker__panel__label:has-text("月")')

        # 检查当前月份是否与目标月份相同
        if page_month != current_month:
            await page.click('button.weui-desktop-btn__icon__right')

        # 获取页面元素
        elements = await page.query_selector_all('table.weui-desktop-picker__table a')

        # 遍历元素并点击匹配的元素
        for element in elements:
            if 'weui-desktop-picker__disabled' in await element.evaluate('el => el.className'):
                continue
            text = await element.inner_text()
            if text.strip() == str(publish_date.day):
                await element.click()
                break

        # 输入小时部分（假设选择11小时）
        await page.click('input[placeholder="请选择时间"]')
        await page.keyboard.press("Control+KeyA")
        await page.keyboard.type(str(publish_date.hour))

        # 选择标题栏（令定时时间生效）
        await page.locator("div.input-editor").click()

    async def handle_upload_error(self, page):
        tencent_logger.info("视频出错了，重新上传中")
        await page.locator('div.media-status-content div.tag-inner:has-text("删除")').click()
        await page.get_by_role('button', name="删除", exact=True).click()
        file_input = page.locator('input[type="file"]')
        await file_input.set_input_files(self.file_path)

    async def upload(self, playwright: Playwright) -> None:
        # 使用 Chromium (这里使用系统内浏览器，用chromium 会造成h264错误
        browser = await playwright.chromium.launch(headless=self.headless, executable_path=self.local_executable_path)
        # 创建一个浏览器上下文，使用指定的 cookie 文件
        context = await browser.new_context(storage_state=f"{self.account_file}")
        context = await set_init_script(context)

        # 创建一个新的页面
        page = await context.new_page()
        # 访问指定的 URL
        await page.goto("https://channels.weixin.qq.com/platform/post/create")
        tencent_logger.info(f'[+]正在上传-------{self.title}.mp4')
        # 等待页面跳转到指定的 URL，没进入，则自动等待到超时
        await page.wait_for_url("https://channels.weixin.qq.com/platform/post/create")
        # await page.wait_for_selector('input[type="file"]', timeout=10000)
        file_input = page.locator('input[type="file"]')
        await file_input.set_input_files(self.file_path)
        # 填充标题和话题
        await self.add_title_tags(page)
        # 添加商品
        # await self.add_product(page)
        # 合集功能
        await self.add_collection(page)
        # 原创选择
        await self.add_original(page)
        # 检测上传状态
        await self.detect_upload_status(page)
        if self.publish_date != 0:
            await self.set_schedule_time_tencent(page, self.publish_date)
        await self.upload_cover_if_needed(page)
        # 添加短标题
        await self.add_short_title(page)

        # 预览模式：停在发布页面等待用户手动操作，不点击发布/保存草稿
        if getattr(self, 'is_preview', False):
            tencent_logger.success("  [-]预览模式：已填写完表单，请手动点击发布/保存草稿")
            # 保持页面打开，等待用户手动操作（最多等待30分钟）
            for _ in range(360):
                await asyncio.sleep(5)
                current_url = page.url
                if "post/list" in current_url or "draft" in current_url:
                    tencent_logger.success("  [-]预览模式：检测到页面已跳转，发布/保存成功")
                    break
        else:
            await self.click_publish(page)

        await context.storage_state(path=f"{self.account_file}")  # 保存cookie
        tencent_logger.success('  [-]cookie更新完毕！')
        await asyncio.sleep(2)  # 这里延迟是为了方便眼睛直观的观看
        # 关闭浏览器上下文和浏览器实例
        await context.close()
        await browser.close()

    async def upload_cover_if_needed(self, page):
        if not self.thumbnail_path:
            tencent_logger.info("  [-]未提供封面路径，跳过封面上传")
            return
        if not os.path.exists(self.thumbnail_path):
            raise FileNotFoundError(f"视频号封面图不存在: {self.thumbnail_path}")

        tencent_logger.info(f"  [-]准备上传视频号封面: {self.thumbnail_path}")

        # 视频号封面上传流程：必须先点击"编辑"或"上传封面"入口，弹出封面编辑弹窗，
        # 然后在弹窗内设置封面文件。直接在页面初始状态找 input 设置文件不会生效。
        opened = await self.open_cover_panel(page)
        if not opened:
            raise RuntimeError("未找到视频号封面入口（上传封面/编辑）")

        # 弹窗/面板可能需要时间加载，轮询查找 input（最多等待 10 秒）
        tencent_logger.info("  [-]等待封面弹窗/面板加载...")
        for attempt in range(10):
            await page.wait_for_timeout(1000)
            # 只在弹窗/dialog 内查找 input，避免命中页面初始状态的 input
            if await self.set_image_input_files_in_dialog(page):
                tencent_logger.success("  [-]视频号封面已通过封面面板 input 选择")
                await self.confirm_cover_dialog(page)
                await self.wait_cover_apply(page)
                return
            tencent_logger.info(f"  [-]第 {attempt + 1}/10 次尝试查找封面 input...")

        # 兜底：尝试直接用 JS 在弹窗内查找并设置 input
        tencent_logger.info("  [-]尝试通过 JS 在弹窗内查找并设置封面 input")
        if await self.set_cover_via_js(page):
            tencent_logger.success("  [-]视频号封面已通过 JS 设置")
            await self.confirm_cover_dialog(page)
            await self.wait_cover_apply(page)
            return

        raise RuntimeError("已打开视频号封面入口，但未找到图片 input[type=file]")

    async def set_image_input_files_in_dialog(self, page):
        """只在弹窗/dialog 内查找图片 input 并设置封面文件。"""
        # 只在弹窗相关容器内查找 input
        dialog_selectors = [
            '.weui-desktop-dialog input[type="file"]',
            '[class*="dialog"] input[type="file"]',
            '[class*="modal"] input[type="file"]',
            '.cover-uploader input[type="file"]',
            '.cover-wrap input[type="file"]',
        ]

        for selector in dialog_selectors:
            inputs = page.locator(selector)
            count = await inputs.count()
            for index in range(count):
                item = inputs.nth(index)
                try:
                    accept = (await item.get_attribute("accept") or "").lower()
                    if accept and not self.is_image_accept(accept):
                        continue
                    await item.set_input_files(self.thumbnail_path)
                    tencent_logger.info(f"  [-]命中视频号封面 input(弹窗): {selector}, accept={accept or '-'}")
                    return True
                except Exception as exc:
                    tencent_logger.warning(f"  [-]视频号封面 input(弹窗) 设置失败: {selector}, {exc}")
        return False

    async def set_image_input_files(self, page, prefer_visible=False):
        """尝试设置封面文件到图片 input。"""
        # 1. 优先在封面相关容器内查找 input
        container_selectors = [
            '.cover-uploader input[type="file"]',
            '.cover-wrap input[type="file"]',
            '.img-wrap input[type="file"]',
            '.vertical-img-wrap input[type="file"]',
            '[class*="cover"] input[type="file"]',
            '[class*="dialog"] input[type="file"]',
            '[class*="modal"] input[type="file"]',
        ]

        for selector in container_selectors:
            inputs = page.locator(selector)
            count = await inputs.count()
            for index in range(count):
                item = inputs.nth(index)
                try:
                    if prefer_visible and not await item.is_visible():
                        continue
                    accept = (await item.get_attribute("accept") or "").lower()
                    if accept and not self.is_image_accept(accept):
                        continue
                    await item.set_input_files(self.thumbnail_path)
                    tencent_logger.info(f"  [-]命中视频号封面 input(容器): {selector}, accept={accept or '-'}")
                    return True
                except Exception as exc:
                    tencent_logger.warning(f"  [-]视频号封面 input(容器) 设置失败: {selector}, {exc}")

        # 2. 全局查找带 accept 的图片 input
        selectors = [
            'input[type="file"][accept*="image"]',
            'input[type="file"][accept*="png"]',
            'input[type="file"][accept*="jpg"]',
            'input[type="file"][accept*="jpeg"]',
            'input[type="file"][accept*="webp"]',
        ]
        for selector in selectors:
            inputs = page.locator(selector)
            count = await inputs.count()
            for index in range(count):
                item = inputs.nth(index)
                try:
                    if prefer_visible and not await item.is_visible():
                        continue
                    await item.set_input_files(self.thumbnail_path)
                    tencent_logger.info(f"  [-]命中视频号封面 input: {selector}")
                    return True
                except Exception as exc:
                    tencent_logger.warning(f"  [-]视频号封面 input 设置失败: {selector}, {exc}")

        # 3. 兜底：查找所有 input[type="file"]（不限于可见），严格排除视频 input
        inputs = page.locator('input[type="file"]')
        count = await inputs.count()
        tencent_logger.info(f"  [-]页面共有 {count} 个 input[type=file]，逐个检查")
        for index in range(count):
            item = inputs.nth(index)
            try:
                accept = (await item.get_attribute("accept") or "").lower()
                is_visible = await item.is_visible()
                tencent_logger.info(f"  [-]  input[{index}]: accept={accept or '-'}, visible={is_visible}")
                if any(v in accept for v in ["video", "mp4", "mov", "avi"]):
                    continue
                if accept and not self.is_image_accept(accept):
                    continue
                await item.set_input_files(self.thumbnail_path)
                tencent_logger.info(f"  [-]命中视频号封面 input(兜底): index={index}, accept={accept or '-'}")
                return True
            except Exception as exc:
                tencent_logger.warning(f"  [-]视频号封面 input(兜底) 设置失败: index={index}, {exc}")

        return False

    async def set_cover_via_js(self, page):
        """通过 JS 在页面中查找图片 input 并设置文件。"""
        try:
            result = await page.evaluate("""
                async (filePath) => {
                    const inputs = document.querySelectorAll('input[type="file"]');
                    const candidates = [];
                    for (let i = 0; i < inputs.length; i++) {
                        const el = inputs[i];
                        const accept = (el.getAttribute('accept') || '').toLowerCase();
                        const isVideo = ['video', 'mp4', 'mov', 'avi'].some(v => accept.includes(v));
                        const isImage = ['image', 'png', 'jpg', 'jpeg', 'webp'].some(v => accept.includes(v));
                        const rect = el.getBoundingClientRect();
                        candidates.push({
                            index: i,
                            accept: accept,
                            visible: rect.width > 0 && rect.height > 0,
                            parentTag: el.parentElement ? el.parentElement.tagName : null,
                            parentClass: el.parentElement ? el.parentElement.className : null
                        });
                        if (!isVideo && (isImage || !accept)) {
                            // 尝试触发点击，让浏览器创建 file chooser
                            el.click();
                            return { success: true, index: i, accept: accept };
                        }
                    }
                    return { success: false, candidates: candidates };
                }
            """, self.thumbnail_path)
            tencent_logger.info(f"  [-]JS 查找 input 结果: {result}")
            if result and result.get("success"):
                return True
        except Exception as exc:
            tencent_logger.warning(f"  [-]JS 设置封面失败: {exc}")
        return False

    async def open_cover_panel(self, page):
        entries = [
            ("get_by_text('上传封面')", page.get_by_text("上传封面", exact=True)),
            ("div.text-wrap:has-text('上传封面')", page.locator('div.text-wrap:has-text("上传封面")')),
            ("div.wrap:has-text('上传封面')", page.locator('div.wrap:has-text("上传封面")')),
            ("div.edit-btn:has-text('编辑')", page.locator('div.edit-btn:has-text("编辑")')),
            ("get_by_text('编辑')", page.get_by_text("编辑", exact=True)),
        ]

        # 先输出所有入口的数量和可见性
        tencent_logger.info("  [-]扫描视频号封面入口...")
        found_any = False
        for name, entry in entries:
            count = await entry.count()
            visible_count = 0
            for i in range(count):
                try:
                    if await entry.nth(i).is_visible():
                        visible_count += 1
                except Exception:
                    pass
            tencent_logger.info(f"  [-]  入口 '{name}': 总数={count}, 可见={visible_count}")
            if visible_count > 0:
                found_any = True

        if not found_any:
            tencent_logger.warning("  [-]未找到任何可见的视频号封面入口")
            return False

        for name, entry in entries:
            count = await entry.count()
            for index in range(count):
                target = entry.nth(index)
                try:
                    visible = await target.is_visible()
                    if not visible:
                        continue
                    text = await target.inner_text()
                    tencent_logger.info(f"  [-]准备点击视频号封面入口 '{name}' [{index}]: text='{text.strip()}'")
                except Exception as exc:
                    tencent_logger.warning(f"  [-]检查入口 '{name}' [{index}] 失败: {exc}")
                    continue

                try:
                    tencent_logger.info(f"  [-]正在点击...")
                    await target.scroll_into_view_if_needed(timeout=3000)
                    await target.click(timeout=5000, force=True)
                    tencent_logger.info(f"  [-]点击完成，等待弹窗/面板...")
                    await page.wait_for_timeout(2000)
                    return True
                except Exception as exc:
                    tencent_logger.error(f"  [-]点击入口 '{name}' [{index}] 失败: {exc}")
                    continue
        tencent_logger.warning("  [-]所有视频号封面入口都点击失败")
        return False

    async def confirm_cover_dialog(self, page):
        """点击封面弹窗内的确认按钮。优先点击在 dialog/modal 内的按钮。"""
        await page.wait_for_timeout(1000)
        # 优先查找在弹窗/dialog 内的按钮
        dialog_buttons = [
            page.locator('.weui-desktop-dialog__ft button:has-text("确认")'),
            page.locator('.weui-desktop-dialog__ft button:has-text("确定")'),
            page.locator('.weui-desktop-dialog__ft button:has-text("完成")'),
            page.locator('.weui-desktop-dialog__ft button:has-text("保存")'),
            page.locator('[class*="dialog"] button:has-text("确认")'),
            page.locator('[class*="dialog"] button:has-text("确定")'),
            page.locator('[class*="dialog"] button:has-text("完成")'),
            page.locator('[class*="dialog"] button:has-text("保存")'),
            page.locator('[class*="modal"] button:has-text("确认")'),
            page.locator('[class*="modal"] button:has-text("确定")'),
            page.locator('[class*="modal"] button:has-text("完成")'),
            page.locator('[class*="modal"] button:has-text("保存")'),
        ]
        for button in dialog_buttons:
            count = await button.count()
            for idx in range(count):
                target = button.nth(idx)
                try:
                    if await target.is_visible():
                        await target.click(timeout=3000)
                        tencent_logger.info("  [-]已点击视频号封面确认按钮(弹窗内)")
                        await page.wait_for_timeout(1000)
                        return
                except Exception:
                    continue

        # 兜底：查找页面上的通用按钮
        buttons = [
            page.get_by_role("button", name="确认"),
            page.get_by_role("button", name="确定"),
            page.get_by_role("button", name="完成"),
            page.get_by_role("button", name="保存"),
            page.locator('button:has-text("确认")'),
            page.locator('button:has-text("确定")'),
            page.locator('button:has-text("完成")'),
            page.locator('button:has-text("保存")'),
        ]
        for button in buttons:
            if await button.count():
                try:
                    await button.last.click(timeout=3000)
                    tencent_logger.info("  [-]已点击视频号封面确认按钮")
                    await page.wait_for_timeout(1000)
                    return
                except Exception:
                    continue

    async def wait_cover_apply(self, page):
        """Wait for the cover dialog to finish applying changes to the main form."""
        dialog = page.locator('.weui-desktop-dialog, [class*="dialog"], [class*="modal"]')
        try:
            if await dialog.count():
                await dialog.first.wait_for(state="hidden", timeout=10000)
        except Exception:
            # Some Tencent dialog containers stay mounted or are named generically.
            # A short settle delay is still safer than closing with Escape immediately.
            pass
        await page.wait_for_timeout(5000)
        tencent_logger.info("  [-]视频号封面确认后已等待页面应用")

    async def close_cover_panel_if_needed(self, page):
        """尝试关闭可能残留的封面弹窗/dialog。"""
        await page.wait_for_timeout(500)
        # 尝试按 ESC 关闭弹窗
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)
        except Exception:
            pass

        # 尝试点击遮罩层关闭
        masks = [
            page.locator('.weui-desktop-dialog__mask'),
            page.locator('.weui-desktop-mask'),
            page.locator('[class*="mask"]'),
            page.locator('[class*="overlay"]'),
        ]
        for mask in masks:
            try:
                if await mask.count() and await mask.first.is_visible():
                    await mask.first.click(timeout=2000)
                    await page.wait_for_timeout(500)
                    tencent_logger.info("  [-]已点击遮罩层关闭弹窗")
                    return
            except Exception:
                continue

    @staticmethod
    def is_image_accept(accept):
        if not accept:
            return False
        return any(item in accept for item in ["image", "png", "jpg", "jpeg", "webp", "bmp", "tif"])

    async def add_short_title(self, page):
        short_title_element = page.get_by_text("短标题", exact=True).locator("..").locator(
            "xpath=following-sibling::div").locator(
            'span input[type="text"]')
        if await short_title_element.count():
            short_title = format_str_for_short_title(self.title)
            await short_title_element.fill(short_title)

    async def click_publish(self, page):
        max_retries = 60  # 最多重试60次，避免无限循环
        for attempt in range(max_retries):
            try:
                # 先尝试关闭可能遮挡按钮的弹窗
                await self.close_cover_panel_if_needed(page)

                if self.is_draft:
                    # 点击"保存草稿"按钮
                    draft_button = page.locator('div.form-btns button:has-text("保存草稿")')
                    if await draft_button.count():
                        await draft_button.click(timeout=5000)
                    # 等待跳转到草稿箱页面或确认保存成功
                    await page.wait_for_url("**/post/list**", timeout=5000)  # 使用通配符匹配包含post/list的URL
                    tencent_logger.success("  [-]视频草稿保存成功")
                else:
                    # 点击"发表"按钮
                    publish_button = page.locator('div.form-btns button:has-text("发表")')
                    if await publish_button.count():
                        await publish_button.click(timeout=5000)
                    await page.wait_for_url("https://channels.weixin.qq.com/platform/post/list", timeout=5000)
                    tencent_logger.success("  [-]视频发布成功")
                break
            except Exception as e:
                current_url = page.url
                if self.is_draft:
                    # 检查是否在草稿相关的页面
                    if "post/list" in current_url or "draft" in current_url:
                        tencent_logger.success("  [-]视频草稿保存成功")
                        break
                else:
                    # 检查是否在发布列表页面
                    if "https://channels.weixin.qq.com/platform/post/list" in current_url:
                        tencent_logger.success("  [-]视频发布成功")
                        break
                tencent_logger.exception(f"  [-] Exception: {e}")
                tencent_logger.info(f"  [-] 视频正在发布中... (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(1)
        else:
            raise RuntimeError(f"视频号发布/保存草稿失败，已达到最大重试次数({max_retries})")

    async def detect_upload_status(self, page):
        while True:
            # 匹配删除按钮，代表视频上传完毕，如果不存在，代表视频正在上传，则等待
            try:
                # 匹配删除按钮，代表视频上传完毕
                if "weui-desktop-btn_disabled" not in await page.get_by_role("button", name="发表").get_attribute(
                        'class'):
                    tencent_logger.info("  [-]视频上传完毕")
                    break
                else:
                    tencent_logger.info("  [-] 正在上传视频中...")
                    await asyncio.sleep(2)
                    # 出错了视频出错
                    if await page.locator('div.status-msg.error').count() and await page.locator(
                            'div.media-status-content div.tag-inner:has-text("删除")').count():
                        tencent_logger.error("  [-] 发现上传出错了...准备重试")
                        await self.handle_upload_error(page)
            except:
                tencent_logger.info("  [-] 正在上传视频中...")
                await asyncio.sleep(2)

    async def add_title_tags(self, page):
        await page.locator("div.input-editor").click()
        await page.keyboard.type(self.title)
        await page.keyboard.press("Enter")
        for index, tag in enumerate(self.tags, start=1):
            await page.keyboard.type("#" + tag)
            await page.keyboard.press("Space")
        tencent_logger.info(f"成功添加hashtag: {len(self.tags)}")

    async def add_collection(self, page):
        collection_elements = page.get_by_text("添加到合集").locator("xpath=following-sibling::div").locator(
            '.option-list-wrap > div')
        if await collection_elements.count() > 1:
            await page.get_by_text("添加到合集").locator("xpath=following-sibling::div").click()
            await collection_elements.first.click()

    async def add_original(self, page):
        if await page.get_by_label("视频为原创").count():
            await page.get_by_label("视频为原创").check()
        # 检查 "我已阅读并同意 《视频号原创声明使用条款》" 元素是否存在
        label_locator = await page.locator('label:has-text("我已阅读并同意 《视频号原创声明使用条款》")').is_visible()
        if label_locator:
            await page.get_by_label("我已阅读并同意 《视频号原创声明使用条款》").check()
            await page.get_by_role("button", name="声明原创").click()
        # 2023年11月20日 wechat更新: 可能新账号或者改版账号，出现新的选择页面
        if await page.locator('div.label span:has-text("声明原创")').count() and self.category:
            # 因处罚无法勾选原创，故先判断是否可用
            if not await page.locator('div.declare-original-checkbox input.ant-checkbox-input').is_disabled():
                await page.locator('div.declare-original-checkbox input.ant-checkbox-input').click()
                if not await page.locator(
                        'div.declare-original-dialog label.ant-checkbox-wrapper.ant-checkbox-wrapper-checked:visible').count():
                    await page.locator('div.declare-original-dialog input.ant-checkbox-input:visible').click()
            if await page.locator('div.original-type-form > div.form-label:has-text("原创类型"):visible').count():
                await page.locator('div.form-content:visible').click()  # 下拉菜单
                await page.locator(
                    f'div.form-content:visible ul.weui-desktop-dropdown__list li.weui-desktop-dropdown__list-ele:has-text("{self.category}")').first.click()
                await page.wait_for_timeout(1000)
            if await page.locator('button:has-text("声明原创"):visible').count():
                await page.locator('button:has-text("声明原创"):visible').click()

    async def main(self):
        async with async_playwright() as playwright:
            await self.upload(playwright)
