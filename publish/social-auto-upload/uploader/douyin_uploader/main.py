# -*- coding: utf-8 -*-
from datetime import datetime

import asyncio
import inspect
import os
from pathlib import Path

from patchright.async_api import Page
from patchright.async_api import Playwright
from patchright.async_api import TimeoutError as PlaywrightTimeoutError
from patchright.async_api import async_playwright

from conf import DEBUG_MODE, LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH
from uploader.base_video import BaseVideoUploader
from utils.base_social_media import set_init_script
from utils.login_qrcode import build_login_qrcode_path
from utils.login_qrcode import decode_qrcode_from_path
from utils.login_qrcode import print_terminal_qrcode
from utils.login_qrcode import remove_qrcode_file
from utils.login_qrcode import save_data_url_image
from utils.log import douyin_logger

DOUYIN_PUBLISH_STRATEGY_IMMEDIATE = "immediate"
DOUYIN_PUBLISH_STRATEGY_SCHEDULED = "scheduled"
DOUYIN_COVER_PORTRAIT_SIZE = (1200, 1600)  # 3:4
DOUYIN_COVER_LANDSCAPE_SIZE = (1600, 1200)  # 4:3


def _msg(emoji: str, text: str) -> str:
    return f"{emoji} {text}"


async def _goto_with_retry(page: Page, url: str, retries: int = 2, timeout: int = 60000):
    last_error = None
    for attempt in range(retries + 1):
        try:
            return await page.goto(url, timeout=timeout)
        except Exception as exc:
            last_error = exc
            if "ERR_CERT_VERIFIER_CHANGED" not in str(exc) or attempt >= retries:
                raise
            douyin_logger.warning(_msg("😵", "浏览器证书校验状态变化，稍等后重试打开抖音后台"))
            await asyncio.sleep(2)
    raise last_error


async def _emit_qrcode_callback(qrcode_callback, payload: dict):
    if not qrcode_callback:
        return

    callback_result = qrcode_callback(payload)
    if inspect.isawaitable(callback_result):
        await callback_result


def _build_login_result(success: bool, status: str, message: str, account_file: str, qrcode: dict | None = None, current_url: str = "") -> dict:
    return {
        "success": success,
        "status": status,
        "message": message,
        "account_file": str(account_file),
        "qrcode": qrcode,
        "current_url": current_url,
    }


def _image_size(path: str | Path) -> tuple[int, int] | None:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return image.size
    except Exception:
        return None


def _render_cover_variant(source_path: str | Path, output_path: Path, size: tuple[int, int]) -> Path:
    from PIL import Image, ImageFilter

    source = Path(source_path)
    with Image.open(source) as image:
        image = image.convert("RGB")

        bg = image.copy()
        bg.thumbnail(size, Image.Resampling.LANCZOS)
        scale = max(size[0] / bg.width, size[1] / bg.height)
        bg = bg.resize((int(bg.width * scale), int(bg.height * scale)), Image.Resampling.LANCZOS)
        left = (bg.width - size[0]) // 2
        top = (bg.height - size[1]) // 2
        bg = bg.crop((left, top, left + size[0], top + size[1]))
        bg = bg.filter(ImageFilter.GaussianBlur(radius=28))

        fg = image.copy()
        fg.thumbnail(size, Image.Resampling.LANCZOS)
        canvas = bg.copy()
        canvas.paste(fg, ((size[0] - fg.width) // 2, (size[1] - fg.height) // 2))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output_path, "JPEG", quality=92, optimize=True)
    return output_path


def _prepare_douyin_cover_variants(source_path: str | Path) -> tuple[str, str]:
    source = Path(source_path).expanduser().resolve()
    stem = source.with_suffix("")
    portrait_path = stem.parent / f"{stem.name}.douyin_portrait_3x4.jpg"
    landscape_path = stem.parent / f"{stem.name}.douyin_landscape_4x3.jpg"
    _render_cover_variant(source, portrait_path, DOUYIN_COVER_PORTRAIT_SIZE)
    _render_cover_variant(source, landscape_path, DOUYIN_COVER_LANDSCAPE_SIZE)
    return str(landscape_path), str(portrait_path)


async def cookie_auth(account_file):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, channel="chrome")
        try:
            context = await browser.new_context(storage_state=account_file, ignore_https_errors=True)
            context = await set_init_script(context)
            page = await context.new_page()
            await _goto_with_retry(page, "https://creator.douyin.com/creator-micro/content/upload")
            try:
                await page.wait_for_url("https://creator.douyin.com/creator-micro/content/upload", timeout=5000)
            except Exception:
                return False

            if await page.get_by_text("手机号登录").count() or await page.get_by_text("扫码登录").count():
                return False

            return True
        finally:
            await browser.close()


async def douyin_setup(account_file, handle=False, return_detail=False, qrcode_callback=None, headless: bool = LOCAL_CHROME_HEADLESS):
    if not os.path.exists(account_file) or not await cookie_auth(account_file):
        if not handle:
            result = _build_login_result(False, "cookie_invalid", "cookie文件不存在或已失效", account_file)
            return result if return_detail else False
        douyin_logger.info(_msg("🥹", "cookie 失效了，准备打开浏览器重新登录"))
        result = await douyin_cookie_gen(account_file, qrcode_callback=qrcode_callback, headless=headless)
        return result if return_detail else result["success"]

    result = _build_login_result(True, "cookie_valid", "cookie有效", account_file)
    return result if return_detail else True


async def _extract_douyin_qrcode_src(page: Page) -> str:
    scan_login_tab = page.get_by_text("扫码登录", exact=True).first
    await scan_login_tab.wait_for(timeout=30000)

    qrcode_img = (
        scan_login_tab
        .locator("..")
        .locator("xpath=following-sibling::div[1]")
        .locator('img[aria-label="二维码"]')
        .first
    )

    if not await qrcode_img.count():
        qrcode_img = page.get_by_role("img", name="二维码").first

    await qrcode_img.wait_for(state="visible", timeout=30000)
    src = await qrcode_img.get_attribute("src")
    if not src:
        raise RuntimeError("未获取到抖音登录二维码地址")

    return src


async def _save_douyin_qrcode(page: Page, account_file: str, previous_qrcode_path: Path | None = None, qrcode_callback=None) -> dict:
    qrcode_src = await _extract_douyin_qrcode_src(page)
    qrcode_path = save_data_url_image(qrcode_src, build_login_qrcode_path(account_file))
    if previous_qrcode_path and previous_qrcode_path != qrcode_path:
        if remove_qrcode_file(previous_qrcode_path):
            douyin_logger.info(_msg("🧹", f"临时二维码文件已清理: {previous_qrcode_path}"))
    douyin_logger.info(_msg("🖼️", f"二维码已经准备好啦，已保存到: {qrcode_path}"))
    qrcode_content = decode_qrcode_from_path(qrcode_path)
    if qrcode_content:
        print_terminal_qrcode(qrcode_content, qrcode_path, "抖音APP")
    else:
        douyin_logger.warning(_msg("😵", f"终端没法完整显示二维码，请打开 {qrcode_path} 扫码"))
    qrcode_info = {
        "image_path": str(qrcode_path),
        "image_data_url": qrcode_src,
    }
    await _emit_qrcode_callback(qrcode_callback, qrcode_info)
    return qrcode_info


async def _is_douyin_login_completed(page: Page) -> bool:
    if not page.url.startswith("https://creator.douyin.com/creator-micro/home"):
        return False

    login_markers = [
        page.get_by_text("扫码登录", exact=True).first,
        page.get_by_text("手机号登录", exact=True).first,
        page.get_by_text("二维码失效", exact=True).first,
        page.get_by_role("img", name="二维码").first,
    ]

    for marker in login_markers:
        if not await marker.count():
            continue
        try:
            if await marker.is_visible():
                return False
        except Exception:
            continue

    return True


async def _wait_for_douyin_login(page: Page, account_file: str, qrcode_info: dict, qrcode_callback=None, poll_interval: int = 3, max_checks: int = 100) -> dict:
    qrcode_path = Path(qrcode_info["image_path"])
    for _ in range(max_checks):
        if await _is_douyin_login_completed(page):
            douyin_logger.info(_msg("🥳", f"扫码成功，已经跳转到登录后页面: {page.url}"))
            return _build_login_result(True, "success", "抖音扫码登录成功", account_file, qrcode_info, page.url)

        expired_box = page.get_by_text("二维码失效", exact=True).locator("..").first
        if await expired_box.count() and await expired_box.is_visible():
            douyin_logger.warning(_msg("😵", "二维码失效了，小人马上去刷新"))
            await expired_box.click()
            await asyncio.sleep(1)
            qrcode_info = await _save_douyin_qrcode(page, account_file, qrcode_path, qrcode_callback=qrcode_callback)
            qrcode_path = Path(qrcode_info["image_path"])

        await asyncio.sleep(poll_interval)

    return _build_login_result(False, "timeout", "等待抖音扫码登录超时", account_file, qrcode_info, page.url)


async def douyin_cookie_gen(
    account_file,
    qrcode_callback=None,
    poll_interval: int = 3,
    max_checks: int = 100,
    headless: bool = LOCAL_CHROME_HEADLESS,
):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless, channel="chrome")
        context = await browser.new_context(ignore_https_errors=True)
        context = await set_init_script(context)
        qrcode_path = None
        result = _build_login_result(False, "failed", "抖音登录失败", account_file)
        try:
            page = await context.new_page()
            await _goto_with_retry(page, "https://creator.douyin.com/")
            qrcode_info = await _save_douyin_qrcode(page, account_file, qrcode_callback=qrcode_callback)
            qrcode_path = Path(qrcode_info["image_path"])
            douyin_logger.info(_msg("🧍", "请扫码，小人正在耐心等待登录完成"))
            result = await _wait_for_douyin_login(
                page,
                account_file,
                qrcode_info,
                qrcode_callback=qrcode_callback,
                poll_interval=poll_interval,
                max_checks=max_checks,
            )
            if result["success"]:
                await asyncio.sleep(2)
                await context.storage_state(path=account_file)
                if not await cookie_auth(account_file):
                    result = _build_login_result(
                        False,
                        "cookie_invalid",
                        "抖音扫码流程结束，但 cookie 校验失败",
                        account_file,
                        qrcode_info,
                        page.url,
                    )
        except Exception as exc:
            result = _build_login_result(False, "failed", str(exc), account_file, current_url=page.url if "page" in locals() else "")
        finally:
            if remove_qrcode_file(qrcode_path):
                douyin_logger.info(_msg("🧹", f"临时二维码文件已清理: {qrcode_path}"))
            if not result["success"]:
                douyin_logger.error(_msg("😢", f"登录失败: {result['message']}"))
            await context.close()
            await browser.close()
        return result


class DouYinBaseUploader(BaseVideoUploader):
    def __init__(
        self,
        publish_date: datetime | int,
        account_file,
        publish_strategy: str = DOUYIN_PUBLISH_STRATEGY_IMMEDIATE,
        debug: bool = DEBUG_MODE,
        headless: bool = LOCAL_CHROME_HEADLESS,
        preview: bool = False,
    ):
        self.publish_date = publish_date
        self.account_file = account_file
        self.publish_strategy = publish_strategy
        self.debug = debug
        self.date_format = "%Y年%m月%d日 %H:%M"
        self.local_executable_path = LOCAL_CHROME_PATH
        self.headless = headless
        self.preview = preview

    async def validate_base_args(self):
        if not os.path.exists(self.account_file):
            raise RuntimeError(f"cookie文件不存在，请先完成抖音登录: {self.account_file}")
        if not await cookie_auth(self.account_file):
            raise RuntimeError(f"cookie文件已失效，请先完成抖音登录: {self.account_file}")
        if self.publish_strategy not in {DOUYIN_PUBLISH_STRATEGY_IMMEDIATE, DOUYIN_PUBLISH_STRATEGY_SCHEDULED}:
            raise ValueError(f"不支持的发布策略: {self.publish_strategy}")

        if self.publish_strategy == DOUYIN_PUBLISH_STRATEGY_SCHEDULED:
            self.publish_date = self.validate_publish_date(self.publish_date)
        else:
            self.publish_date = 0

    async def set_schedule_time_douyin(self, page, publish_date):
        label_element = page.locator("[class^='radio']:has-text('定时发布')")
        await label_element.click()
        await asyncio.sleep(1)
        publish_date_hour = publish_date.strftime("%Y-%m-%d %H:%M")

        await asyncio.sleep(1)
        await page.locator('.semi-input[placeholder="日期和时间"]').click()
        await page.keyboard.press("Control+KeyA")
        await page.keyboard.type(str(publish_date_hour))
        await page.keyboard.press("Enter")
        await asyncio.sleep(1)

    async def fill_title_and_description(self, page: Page, title: str, description: str, tags: list[str] | None = None):
        description_section = (
            page.get_by_text("作品描述", exact=True)
            .locator("xpath=ancestor::div[2]")
            .locator("xpath=following-sibling::div[1]")
        )

        title_input = description_section.locator('input[type="text"]').first
        await title_input.wait_for(state="visible", timeout=10000)
        await title_input.fill(title[:30])

        description_editor = description_section.locator('.zone-container[contenteditable="true"]').first
        await description_editor.wait_for(state="visible", timeout=10000)
        await description_editor.click()
        await page.keyboard.press("Control+KeyA")
        await page.keyboard.press("Delete")
        await page.keyboard.type(description, delay=20)
        await asyncio.sleep(0.5)

        for tag in tags or []:
            tag = str(tag).strip().lstrip("#")
            if not tag:
                continue
            await description_editor.click()
            await page.keyboard.type(" #" + tag, delay=60)
            await page.keyboard.press("Space")
            await asyncio.sleep(0.8)

    async def set_location(self, page: Page, location: str = ""):
        if not location:
            return
        await page.locator('div.semi-select span:has-text("输入地理位置")').click()
        await page.keyboard.press("Backspace")
        await page.wait_for_timeout(2000)
        await page.keyboard.type(location)
        await page.wait_for_selector('div[role="listbox"] [role="option"]', timeout=5000)
        await page.locator('div[role="listbox"] [role="option"]').first.click()

    async def handle_product_dialog(self, page: Page, product_title: str):
        await page.wait_for_timeout(2000)
        await page.wait_for_selector('input[placeholder="请输入商品短标题"]', timeout=10000)
        short_title_input = page.locator('input[placeholder="请输入商品短标题"]')
        if not await short_title_input.count():
            douyin_logger.error(_msg("😵", "没找到商品短标题输入框"))
            return False

        product_title = product_title[:10]
        await short_title_input.fill(product_title)
        await page.wait_for_timeout(1000)

        finish_button = page.locator('button:has-text("完成编辑")')
        if "disabled" not in await finish_button.get_attribute("class"):
            await finish_button.click()
            douyin_logger.debug(_msg("🥳", "已点击“完成编辑”按钮"))
            await page.wait_for_selector(".semi-modal-content", state="hidden", timeout=5000)
            return True

        douyin_logger.error(_msg("😵", "“完成编辑”按钮是灰的，小人先把弹窗关掉"))
        cancel_button = page.locator('button:has-text("取消")')
        if await cancel_button.count():
            await cancel_button.click()
        else:
            close_button = page.locator(".semi-modal-close")
            await close_button.click()
        await page.wait_for_selector(".semi-modal-content", state="hidden", timeout=5000)
        return False

    async def set_product_link(self, page: Page, product_link: str, product_title: str):
        await page.wait_for_timeout(2000)
        try:
            await page.wait_for_selector("text=添加标签", timeout=10000)
            dropdown = page.get_by_text("添加标签").locator("..").locator("..").locator("..").locator(".semi-select").first
            if not await dropdown.count():
                douyin_logger.error(_msg("😵", "没找到标签下拉框"))
                return False
            douyin_logger.debug(_msg("🧍", "找到标签下拉框，小人准备选择“购物车”"))
            await dropdown.click()
            await page.wait_for_selector('[role="listbox"]', timeout=5000)
            await page.locator('[role="option"]:has-text("购物车")').click()
            douyin_logger.debug(_msg("🥳", "已经选中“购物车”"))

            await page.wait_for_selector('input[placeholder="粘贴商品链接"]', timeout=5000)
            input_field = page.locator('input[placeholder="粘贴商品链接"]')
            await input_field.fill(product_link)
            douyin_logger.debug(_msg("🔗", f"商品链接已经填好了: {product_link}"))

            add_button = page.locator('span:has-text("添加链接")')
            button_class = await add_button.get_attribute("class")
            if "disable" in button_class:
                douyin_logger.error(_msg("😵", "“添加链接”按钮现在点不了"))
                return False
            await add_button.click()
            douyin_logger.debug(_msg("🥳", "已点击“添加链接”按钮"))

            await page.wait_for_timeout(2000)
            error_modal = page.locator("text=未搜索到对应商品")
            if await error_modal.count():
                confirm_button = page.locator('button:has-text("确定")')
                await confirm_button.click()
                douyin_logger.error(_msg("😢", "这个商品链接无效"))
                return False

            if not await self.handle_product_dialog(page, product_title):
                return False

            douyin_logger.debug(_msg("🥳", "商品链接设置好了"))
            return True
        except Exception as e:
            douyin_logger.error(_msg("😢", f"设置商品链接时出错: {str(e)}"))
            return False


class DouYinVideo(DouYinBaseUploader):
    def __init__(
        self,
        title,
        file_path,
        tags,
        publish_date: datetime | int,
        account_file,
        thumbnail_landscape_path=None,
        productLink="",
        productTitle="",
        thumbnail_portrait_path=None,
        desc: str | None = None,
        publish_strategy: str = DOUYIN_PUBLISH_STRATEGY_IMMEDIATE,
        debug: bool = DEBUG_MODE,
        headless: bool = LOCAL_CHROME_HEADLESS,
        preview: bool = False,
    ):
        super().__init__(
            publish_date=publish_date,
            account_file=account_file,
            publish_strategy=publish_strategy,
            debug=debug,
            headless=headless,
            preview=preview,
        )
        self.title = title
        self.file_path = file_path
        self.tags = tags
        self.thumbnail_landscape_path = thumbnail_landscape_path
        self.thumbnail_portrait_path = thumbnail_portrait_path
        self.productLink = productLink
        self.productTitle = productTitle
        self.desc = desc or ""

    async def validate_upload_args(self):
        await self.validate_base_args()
        if not self.title or not str(self.title).strip():
            raise ValueError("视频模式下，title 是必须的")

        self.file_path = str(self.validate_video_file(self.file_path))
        if self.thumbnail_landscape_path and not self.thumbnail_portrait_path:
            source_thumbnail = self.validate_image_file(self.thumbnail_landscape_path)
            self.thumbnail_landscape_path, self.thumbnail_portrait_path = _prepare_douyin_cover_variants(source_thumbnail)
            douyin_logger.info(
                _msg(
                    "🖼️",
                    f"已为抖音生成封面比例版本: 横版4:3={self.thumbnail_landscape_path}, 竖版3:4={self.thumbnail_portrait_path}",
                )
            )
        elif self.thumbnail_landscape_path:
            self.thumbnail_landscape_path = str(self.validate_image_file(self.thumbnail_landscape_path))
        if self.thumbnail_portrait_path:
            self.thumbnail_portrait_path = str(self.validate_image_file(self.thumbnail_portrait_path))

    async def handle_upload_error(self, page):
        douyin_logger.warning(_msg("😵", "视频上传摔了一跤，小人马上重新上传"))
        await page.locator('div.progress-div [class^="upload-btn-input"]').set_input_files(self.file_path)

    async def handle_auto_video_cover(self, page):
        if await page.get_by_text("请设置封面后再发布").first.is_visible():
            douyin_logger.info(_msg("🧍", "发布前还得先把封面弄好"))
            recommend_cover = page.locator('[class^="recommendCover-"]').first
            if await recommend_cover.count():
                douyin_logger.info(_msg("🏃", "小人去选第一个推荐封面"))
                try:
                    await recommend_cover.click()
                    await asyncio.sleep(1)
                    confirm_text = "是否确认应用此封面？"
                    if await page.get_by_text(confirm_text).first.is_visible():
                        douyin_logger.info(_msg("🪟", f"弹出确认框了: {confirm_text}"))
                        await page.get_by_role("button", name="确定").click()
                        douyin_logger.info(_msg("🥳", "推荐封面已经应用"))
                        await asyncio.sleep(1)
                    douyin_logger.info(_msg("🥳", "封面选择流程完成"))
                    return True
                except Exception as e:
                    douyin_logger.warning(_msg("😵", f"推荐封面没选成功: {e}"))
        return False

    async def set_thumbnail(self, page: Page):
        if not self.thumbnail_landscape_path and not self.thumbnail_portrait_path:
            return

        douyin_logger.info(_msg("🏃", "小人正在设置视频封面"))

        async def click_first_visible(
            candidates: list[tuple[str, object]],
            timeout: int = 5000,
            file_chooser_path: str | None = None,
        ) -> str | None:
            for label, locator in candidates:
                try:
                    count = await locator.count()
                    douyin_logger.info(_msg("🧭", f"检查封面入口 '{label}': 数量={count}"))
                    if count == 0:
                        continue
                    await locator.first.wait_for(state="visible", timeout=timeout)
                    await locator.first.scroll_into_view_if_needed(timeout=3000)
                    if file_chooser_path:
                        try:
                            async with page.expect_file_chooser(timeout=1500) as chooser_info:
                                await locator.first.click(force=True, timeout=3000)
                            chooser = await chooser_info.value
                            await chooser.set_files(file_chooser_path)
                            douyin_logger.info(_msg("🧭", f"点击 '{label}' 时触发了文件选择器，已自动选择: {file_chooser_path}"))
                        except PlaywrightTimeoutError:
                            douyin_logger.info(_msg("🧭", f"点击 '{label}' 未触发文件选择器"))
                    else:
                        await locator.first.click(force=True, timeout=3000)
                    douyin_logger.info(_msg("🧭", f"成功点击封面入口: {label}"))
                    return label
                except Exception as exc:
                    douyin_logger.warning(_msg("😵", f"点击封面入口 '{label}' 失败: {exc}"))
                    continue
            return None

        async def resolve_cover_dialog():
            dialog_candidates = [
                ("creator-content-modal", page.locator('div[id*="creator-content-modal"]:visible').last),
                ("semi-modal-content", page.locator('div.semi-modal-content:has-text("封面"):visible').last),
                ("role=dialog", page.locator('div[role="dialog"]:has-text("封面"):visible').last),
                ("modal", page.locator('div[class*="modal"]:has-text("封面"):visible').last),
            ]
            for name, dialog in dialog_candidates:
                try:
                    await dialog.wait_for(state="visible", timeout=4000)
                    douyin_logger.info(_msg("🧭", f"找到封面弹窗: {name}"))
                    return dialog
                except Exception:
                    continue
            douyin_logger.warning(_msg("😵", "未找到封面弹窗"))
            return None

        clicked = await click_first_visible(
            [
                ("选择封面按钮", page.get_by_role("button", name="选择封面", exact=True)),
                ("设置封面按钮", page.get_by_role("button", name="设置封面", exact=True)),
                ("编辑封面按钮", page.get_by_role("button", name="编辑封面", exact=True)),
                ("更换封面按钮", page.get_by_role("button", name="更换封面", exact=True)),
                ("选择封面文字", page.get_by_text("选择封面", exact=True)),
                ("设置封面文字", page.get_by_text("设置封面", exact=True)),
                ("编辑封面文字", page.get_by_text("编辑封面", exact=True)),
                ("更换封面文字", page.get_by_text("更换封面", exact=True)),
                ("封面上传入口", page.locator('[class*="cover"]:has-text("封面")').locator("button, div").filter(has_text="封面")),
            ],
            timeout=8000,
            file_chooser_path=self.thumbnail_landscape_path or self.thumbnail_portrait_path,
        )
        if clicked:
            douyin_logger.info(_msg("🧭", f"已点击封面入口: {clicked}"))

        cover_locator = await resolve_cover_dialog()
        if cover_locator is None:
            direct_upload = page.locator('input[type="file"][accept*="image"], input.semi-upload-hidden-input').first
            if await direct_upload.count():
                douyin_logger.warning(_msg("😵", "没有看到封面弹窗，但找到了图片上传控件，直接尝试上传封面"))
                cover_locator = page
            else:
                douyin_logger.warning(_msg("😵", "没有打开封面弹窗，跳过自定义封面，发布时再用推荐封面兜底"))
                return

        tab_clicked = await click_first_visible(
            [
                ("上传封面页签", cover_locator.get_by_text("上传封面", exact=True)),
                ("本地上传页签", cover_locator.get_by_text("本地上传", exact=True)),
                ("上传图片页签", cover_locator.get_by_text("上传图片", exact=True)),
                ("从电脑上传页签", cover_locator.get_by_text("从电脑上传", exact=True)),
            ],
            timeout=3000,
            file_chooser_path=self.thumbnail_landscape_path or self.thumbnail_portrait_path,
        )
        if tab_clicked:
            douyin_logger.info(_msg("🧭", f"已切换封面上传页签: {tab_clicked}"))
            # 等待页签切换后的 input 加载
            await page.wait_for_timeout(2000)

        async def upload_cover_file(path: str, label: str):
            input_selectors = [
                'input[type="file"].semi-upload-hidden-input',
                'input[type="file"][class*="semi-upload-hidden-input"]:not([class*="replace"])',
                'input[type="file"][accept*="image"]:not([class*="replace"])',
                '.semi-upload input[type="file"]',
                'input[type="file"]',
            ]

            async def find_file_input():
                # 抖音弹窗内有两个 semi-upload 区域：推荐封面 + 上传封面
                # 用 JS 精确找到"上传封面"文字对应的 semi-upload 中的 input
                # 关键：只选 semi-upload-hidden-input（真正的 input），不选 semi-upload-hidden-input-replace（替代 input 会触发系统文件选择器）
                try:
                    js_result = await page.evaluate("""() => {
                        const tabs = document.querySelectorAll('div[class*="modal"] div, div[role="dialog"] div');
                        let uploadTab = null;
                        for (const tab of tabs) {
                            if (tab.textContent.trim() === '上传封面' && tab.querySelector('.semi-upload')) {
                                uploadTab = tab;
                                break;
                            }
                        }
                        if (!uploadTab) return null;
                        const uploadDiv = uploadTab.querySelector('.semi-upload');
                        if (!uploadDiv) return null;
                        // 优先选择 semi-upload-hidden-input（真正的 input），避免 replace input 触发文件选择器
                        const realInput = uploadDiv.querySelector('input[type="file"].semi-upload-hidden-input');
                        if (realInput) {
                            return {index: Array.from(document.querySelectorAll('input[type="file"]')).indexOf(realInput), accept: realInput.getAttribute('accept') || ''};
                        }
                        return null;
                    }""")
                    if js_result is not None:
                        all_inputs = page.locator('input[type="file"]')
                        candidate = all_inputs.nth(js_result["index"])
                        douyin_logger.info(_msg("🧭", f"JS 精确定位到上传封面 input: index={js_result['index']}, accept={js_result['accept']}"))
                        return candidate
                except Exception as exc:
                    douyin_logger.warning(_msg("😵", f"JS 精确定位上传封面 input 失败: {exc}"))

                # 备选：在弹窗内查找，只用 semi-upload-hidden-input，不用 replace
                dialog_input_selectors = [
                    'div[class*="modal"] input[type="file"].semi-upload-hidden-input',
                    'div[role="dialog"] input[type="file"].semi-upload-hidden-input',
                    'div[class*="modal"] input[type="file"][accept*="image"]',
                    'div[role="dialog"] input[type="file"][accept*="image"]',
                ]

                for selector in dialog_input_selectors:
                    inputs = page.locator(selector)
                    count = await inputs.count()
                    douyin_logger.info(_msg("🧭", f"查找 input: selector='{selector}', count={count}"))
                    if count == 0:
                        continue
                    candidate = inputs.last
                    try:
                        await candidate.wait_for(state="attached", timeout=1000)
                        class_name = ((await candidate.get_attribute("class")) or "").lower()
                        if "replace" in class_name:
                            continue
                        accept = ((await candidate.get_attribute("accept")) or "").lower()
                        if any(v in accept for v in ["video", "mp4", "mov", "avi"]):
                            continue
                        douyin_logger.info(_msg("🧭", f"找到图片 input: selector='{selector}', accept={accept}"))
                        return candidate
                    except Exception:
                        continue

                # 兜底：在弹窗 locator 内查找
                if cover_locator is not page:
                    for selector in input_selectors:
                        inputs = cover_locator.locator(selector)
                        count = await inputs.count()
                        if count == 0:
                            continue
                        candidate = inputs.last
                        try:
                            await candidate.wait_for(state="attached", timeout=1000)
                            class_name = ((await candidate.get_attribute("class")) or "").lower()
                            if "replace" in class_name:
                                continue
                            accept = ((await candidate.get_attribute("accept")) or "").lower()
                            if any(v in accept for v in ["video", "mp4", "mov", "avi"]):
                                continue
                            if "image" in accept or selector != 'input[type="file"]':
                                return candidate
                        except Exception:
                            continue
                return None

            # 等待弹窗内的 input 加载（最多等待 10 秒）
            douyin_logger.info(_msg("🧭", f"等待{label}封面的文件输入框加载..."))
            file_input = None
            for attempt in range(10):
                file_input = await find_file_input()
                if file_input is not None:
                    break
                await page.wait_for_timeout(1000)
                douyin_logger.info(_msg("🧭", f"第 {attempt + 1}/10 次尝试查找{label}封面的 input..."))
            
            if file_input is not None:
                douyin_logger.info(_msg("🧭", f"已找到{label}封面的页面文件输入框，直接提交文件"))
                await file_input.wait_for(state="attached", timeout=5000)
                # 关键修复：在 set_input_files 前隐藏 replace input，上传完成后再显示
                # 不删除 DOM，只隐藏，避免影响页面结构
                try:
                    await page.evaluate("""() => {
                        const replaces = document.querySelectorAll('input[type="file"].semi-upload-hidden-input-replace');
                        replaces.forEach(el => {
                            el.setAttribute('data-was-display', el.style.display);
                            el.style.display = 'none';
                        });
                    }""")
                    douyin_logger.info(_msg("🧭", f"已隐藏 replace input"))
                except Exception as exc:
                    douyin_logger.warning(_msg("😵", f"隐藏 replace input 失败: {exc}"))
                await file_input.set_input_files(path)
                douyin_logger.info(_msg("🧭", f"已调用 set_input_files({path})"))
                await page.wait_for_timeout(3000)
                # 恢复 replace input 显示
                try:
                    await page.evaluate("""() => {
                        const replaces = document.querySelectorAll('input[type="file"].semi-upload-hidden-input-replace');
                        replaces.forEach(el => {
                            const wasDisplay = el.getAttribute('data-was-display');
                            el.style.display = wasDisplay || '';
                        });
                    }""")
                    douyin_logger.info(_msg("🧭", f"已恢复 replace input 显示"))
                except Exception as exc:
                    douyin_logger.warning(_msg("😵", f"恢复 replace input 显示失败: {exc}"))
                # 截图检查文件选择器是否弹出
                try:
                    screenshot_dir = Path(self.file_path).parent / "logs" / "douyin-cover-debug"
                    screenshot_dir.mkdir(parents=True, exist_ok=True)
                    screenshot_path = screenshot_dir / f"after-upload-{label}.png"
                    await page.screenshot(path=str(screenshot_path), full_page=False)
                    douyin_logger.info(_msg("📸", f"已保存截图: {screenshot_path}"))
                except Exception as exc:
                    douyin_logger.warning(_msg("😵", f"截图失败: {exc}"))
            else:
                raise RuntimeError(
                    f"没有找到{label}封面的页面文件输入框，"
                    "为避免停在系统文件选择器，已停止自动上传"
                )

            # 等待文件上传和预览画布出现（最多等待 15 秒）
            douyin_logger.info(_msg("🧭", f"等待{label}封面的预览画布出现..."))
            upload_success = False
            for attempt in range(15):
                await page.wait_for_timeout(1000)

                preview_selectors = [
                    'canvas#videoHor',
                    'canvas#videoVer',
                    'div[class*="previewphone"]',
                    'div[class*="preview-"]',
                    'canvas[class*="horVideo"]',
                    'canvas[class*="verCover"]',
                    '#horizontal_coverCanvas',
                    '#vertical_coverCanvas',
                    'canvas[class*="cloudImage"]',
                ]
                for sel in preview_selectors:
                    loc = cover_locator.locator(sel).first
                    if cover_locator is not page and not await loc.count():
                        loc = page.locator(sel).first
                    if await loc.count():
                        try:
                            await loc.wait_for(state="visible", timeout=2000)
                            douyin_logger.info(_msg("🧭", f"{label}封面的预览已出现: {sel}"))
                            upload_success = True
                            break
                        except Exception:
                            pass
                if upload_success:
                    break

                # 检测弹窗内是否有 blob 图片
                img_loc = cover_locator.locator('div[style*="blob:"]').first
                if cover_locator is not page and not await img_loc.count():
                    img_loc = page.locator('div[style*="blob:"]').first
                if await img_loc.count():
                    try:
                        await img_loc.wait_for(state="visible", timeout=2000)
                        douyin_logger.info(_msg("🧭", f"{label}封面的 blob 图片已出现"))
                        upload_success = True
                        break
                    except Exception:
                        pass

                douyin_logger.info(_msg("🧭", f"第 {attempt + 1}/15 次尝试检测{label}封面的预览..."))
            
            if not upload_success:
                douyin_logger.warning(_msg("😵", f"{label}封面已提交，但暂未检测到预览变为可见"))
            douyin_logger.info(_msg("🖼️", f"{label}封面上传完成"))

        if self.thumbnail_landscape_path:
            await upload_cover_file(self.thumbnail_landscape_path, "横版")

        if self.thumbnail_portrait_path:
            portrait_tab = await click_first_visible(
                [
                    ("竖版封面页签", cover_locator.get_by_text("竖版封面", exact=True)),
                    ("设置竖版封面页签", cover_locator.get_by_text("设置竖版封面", exact=True)),
                    ("第二个封面步骤", cover_locator.locator("div[class*='steps'] div").nth(1)),
                ],
                timeout=2000,
            )
            if portrait_tab:
                douyin_logger.info(_msg("🧭", f"已切换到: {portrait_tab}"))
            await upload_cover_file(self.thumbnail_portrait_path, "竖版")

        confirm_clicked = await click_first_visible(
            [
                ("完成按钮", cover_locator.locator("button").filter(has_text="完成")),
                ("确定按钮", cover_locator.locator("button").filter(has_text="确定")),
                ("保存按钮", cover_locator.locator("button").filter(has_text="保存")),
                ("应用按钮", cover_locator.locator("button").filter(has_text="应用")),
            ],
            timeout=10000,
        )
        if not confirm_clicked:
            raise RuntimeError("封面已上传，但未找到确认按钮")
        douyin_logger.info(_msg("🧭", f"已点击封面确认按钮: {confirm_clicked}"))

        try:
            await page.wait_for_selector("div.extractFooter", state="detached", timeout=15000)
        except Exception:
            try:
                if cover_locator is not page:
                    await cover_locator.wait_for(state="hidden", timeout=15000)
            except Exception:
                douyin_logger.warning(_msg("😵", "封面弹窗没有自动关闭，小人继续后续发布流程"))
        await page.wait_for_timeout(1000)
        bad_cover = page.get_by_text("封面不佳", exact=False).first
        if await bad_cover.count():
            try:
                if await bad_cover.is_visible():
                    raise RuntimeError("抖音页面提示“封面不佳”，自定义封面没有通过页面校验")
            except RuntimeError:
                raise
            except Exception:
                pass
        douyin_logger.info(_msg("🥳", "视频封面设置完成"))

    async def click_publish_button(self, page: Page) -> bool:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1000)
        publish_button = page.get_by_role("button", name="发布", exact=True)
        button_count = await publish_button.count()
        for index in range(button_count):
            candidate = publish_button.nth(index)
            try:
                await candidate.scroll_into_view_if_needed(timeout=3000)
                if await candidate.is_visible() and await candidate.is_enabled():
                    await candidate.click()
                    return True
            except Exception:
                continue
        return False

    async def upload(self, playwright: Playwright) -> None:
        douyin_logger.info(_msg("🧍", "小人先检查 cookie、视频文件、封面和发布时间"))
        await self.validate_upload_args()
        douyin_logger.info(_msg("🥳", "上传前检查通过"))

        browser = await playwright.chromium.launch(headless=self.headless, channel="chrome")
        context = await browser.new_context(
            storage_state=f"{self.account_file}",
            permissions=["geolocation"],
            ignore_https_errors=True,
        )
        context = await set_init_script(context)

        page = await context.new_page()
        await _goto_with_retry(page, "https://creator.douyin.com/creator-micro/content/upload")
        douyin_logger.info(_msg("🏃", f"小人开始搬运视频: {self.title}.mp4"))
        douyin_logger.info(_msg("🧭", "小人正在赶往上传主页"))
        await page.wait_for_url("https://creator.douyin.com/creator-micro/content/upload")
        await page.locator("div[class^='container'] input").set_input_files(self.file_path)

        while True:
            try:
                await page.wait_for_url(
                    "https://creator.douyin.com/creator-micro/content/publish?enter_from=publish_page",
                    timeout=3000,
                )
                douyin_logger.info(_msg("🥳", "已经进入 version_1 发布页面"))
                break
            except Exception:
                try:
                    await page.wait_for_url(
                        "https://creator.douyin.com/creator-micro/content/post/video?enter_from=publish_page",
                        timeout=3000,
                    )
                    douyin_logger.info(_msg("🥳", "已经进入 version_2 发布页面"))
                    break
                except Exception:
                    douyin_logger.debug(_msg("🧍", "还没进到视频发布页面，小人继续等一会"))
                    await asyncio.sleep(0.5)

        await asyncio.sleep(1)
        douyin_logger.info(_msg("✍️", "小人开始填标题、描述和话题"))
        await self.fill_title_and_description(page, self.title, self.desc or self.title, self.tags)
        douyin_logger.info(_msg("🏷️", f"小人一共贴了 {len(self.tags)} 个话题"))

        while True:
            try:
                number = await page.locator('[class^="long-card"] div:has-text("重新上传")').count()
                if number > 0:
                    douyin_logger.success(_msg("🥳", "视频已经传完啦"))
                    break
                douyin_logger.info(_msg("🏃", "小人正在努力上传视频"))
                await asyncio.sleep(2)
                if await page.locator('div.progress-div > div:has-text("上传失败")').count():
                    douyin_logger.error(_msg("😵", "检测到上传失败，小人准备重试"))
                    await self.handle_upload_error(page)
            except Exception:
                douyin_logger.debug(_msg("🧍", "小人还在等视频上传完成"))
                await asyncio.sleep(2)

        if self.productLink and self.productTitle:
            douyin_logger.info(_msg("🛒", "小人正在设置商品链接"))
            await self.set_product_link(page, self.productLink, self.productTitle)
            douyin_logger.info(_msg("🥳", "商品链接设置完成"))

        await self.set_thumbnail(page)

        third_part_element = '[class^="info"] > [class^="first-part"] div div.semi-switch'
        if await page.locator(third_part_element).count():
            if "semi-switch-checked" not in await page.eval_on_selector(third_part_element, "div => div.className"):
                await page.locator(third_part_element).locator("input.semi-switch-native-control").click()

        if self.publish_strategy == DOUYIN_PUBLISH_STRATEGY_SCHEDULED and self.publish_date != 0:
            await self.set_schedule_time_douyin(page, self.publish_date)

        # 预览模式：停在发布确认页面，等待用户手动点击发布
        if self.preview:
            douyin_logger.info(_msg("👀", "预览模式：视频和内容已填充完毕，请检查后手动点击「发布」按钮"))
            douyin_logger.info(_msg("💡", "发布完成后关闭浏览器即可，脚本会自动保存 cookie"))
            # 等待用户操作或超时
            try:
                await page.wait_for_timeout(300000)  # 等待5分钟
            except Exception:
                pass
            # 用户关闭浏览器后，尝试更新 cookie
            try:
                await context.storage_state(path=self.account_file)
                douyin_logger.success(_msg("🥳", "预览模式结束，cookie 已更新"))
            except Exception:
                pass
            await context.close()
            await browser.close()
            return

        while True:
            try:
                if not await self.click_publish_button(page):
                    douyin_logger.warning(_msg("😵", "暂时没找到可点击的发布按钮，继续滚动重试"))
                await page.wait_for_url(
                    "https://creator.douyin.com/creator-micro/content/manage**",
                    timeout=3000,
                )
                douyin_logger.success(_msg("🥳", "视频发布成功，小人开心收工"))
                break
            except Exception:
                await self.handle_auto_video_cover(page)
                douyin_logger.info(_msg("🏃", "小人正在冲刺发布视频"))
                if self.debug:
                    await page.screenshot(full_page=True)
                await asyncio.sleep(0.5)

        await context.storage_state(path=self.account_file)
        douyin_logger.success(_msg("🥳", "cookie 更新完毕"))
        await asyncio.sleep(2)
        await context.close()
        await browser.close()

    async def douyin_upload_video(self):
        async with async_playwright() as playwright:
            await self.upload(playwright)

    async def main(self):
        await self.douyin_upload_video()


class DouYinNote(DouYinBaseUploader):
    def __init__(
        self,
        image_paths,
        note,
        tags,
        publish_date: datetime | int,
        account_file,
        title: str | None = None,
        publish_strategy: str = DOUYIN_PUBLISH_STRATEGY_IMMEDIATE,
        debug: bool = DEBUG_MODE,
        headless: bool = LOCAL_CHROME_HEADLESS,
    ):
        super().__init__(
            publish_date=publish_date,
            account_file=account_file,
            publish_strategy=publish_strategy,
            debug=debug,
            headless=headless,
        )
        self.image_paths = image_paths
        self.note = note or ""
        self.title = title or (self.note[:30] if self.note else "")
        self.tags = tags or []

    async def validate_upload_args(self):
        await self.validate_base_args()
        if not self.title or not str(self.title).strip():
            raise ValueError("图文模式下，title 是必须的")
        if not self.image_paths:
            raise ValueError("图文模式下，图片是必须的")

        if isinstance(self.image_paths, (str, Path)):
            self.image_paths = [self.image_paths]

        if len(self.image_paths) > 35:
            raise ValueError("图文模式下最多只支持上传 35 张图片")

        normalized_image_paths = []
        for image_path in self.image_paths:
            normalized_image_paths.append(str(self.validate_image_file(image_path)))
        self.image_paths = normalized_image_paths

    async def upload_note_content(self, page: Page) -> None:
        douyin_logger.info(_msg("🏃", f"小人开始搬运图文，共 {len(self.image_paths)} 张图片"))
        douyin_logger.info(_msg("🔀", "小人正在切换到图文发布"))
        await page.get_by_text("发布图文", exact=True).click()
        await page.wait_for_timeout(1000)

        douyin_logger.info(_msg("📤", "小人正在上传图片"))
        await page.locator("div[class^='container'] input[accept*='image']").set_input_files(self.image_paths)

        while True:
            try:
                await page.wait_for_url(
                    "**/creator-micro/content/post/image?**",
                    timeout=3000,
                )
                douyin_logger.info(_msg("🥳", "已经进入图文发布页面"))
                break
            except Exception:
                douyin_logger.debug(_msg("🧍", "小人还在等图片上传完成"))
                await asyncio.sleep(0.5)

        await asyncio.sleep(1)
        douyin_logger.info(_msg("✍️", "小人开始填标题、描述和话题"))
        await self.fill_title_and_description(page, self.title, self.note, self.tags)
        douyin_logger.info(_msg("🏷️", f"小人一共贴了 {len(self.tags)} 个话题"))

        if self.publish_strategy == DOUYIN_PUBLISH_STRATEGY_SCHEDULED and self.publish_date != 0:
            await self.set_schedule_time_douyin(page, self.publish_date)

        while True:
            try:
                publish_button = page.get_by_role("button", name="发布", exact=True)
                if await publish_button.count():
                    await publish_button.click()
                await page.wait_for_url(
                    "**/creator-micro/content/manage?enter_from=publish**",
                    timeout=3000,
                )
                douyin_logger.success(_msg("🥳", "图文发布成功，小人开心收工"))
                break
            except Exception:
                douyin_logger.info(_msg("🏃", "小人正在冲刺发布图文"))
                await asyncio.sleep(0.5)

    async def upload(self, playwright: Playwright) -> None:
        douyin_logger.info(_msg("🧍", "小人先检查 cookie、图片和发布时间"))
        await self.validate_upload_args()
        douyin_logger.info(_msg("🥳", "图文上传前检查通过"))

        browser = await playwright.chromium.launch(headless=self.headless, channel="chrome")
        context = await browser.new_context(
            storage_state=f"{self.account_file}",
            permissions=["geolocation"],
            ignore_https_errors=True,
        )
        context = await set_init_script(context)

        upload_success = False
        try:
            page = await context.new_page()
            await _goto_with_retry(page, "https://creator.douyin.com/creator-micro/content/upload")
            douyin_logger.info(_msg("🧭", "小人正在赶往图文发布页"))
            await page.wait_for_url("https://creator.douyin.com/creator-micro/content/upload")

            await self.upload_note_content(page)
            upload_success = True
        finally:
            if upload_success:
                await context.storage_state(path=self.account_file)
                douyin_logger.success(_msg("🥳", "cookie 更新完毕"))
                await asyncio.sleep(2)
            await context.close()
            await browser.close()

    async def douyin_upload_note(self):
        async with async_playwright() as playwright:
            await self.upload(playwright)
