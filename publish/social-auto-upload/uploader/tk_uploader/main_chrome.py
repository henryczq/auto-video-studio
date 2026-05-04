# -*- coding: utf-8 -*-
import re
from datetime import datetime

from playwright.async_api import Playwright, async_playwright
import os
import asyncio

from conf import LOCAL_CHROME_PATH, LOCAL_CHROME_HEADLESS
from uploader.tk_uploader.tk_config import Tk_Locator
from utils.base_social_media import set_init_script
from utils.files_times import get_absolute_path
from utils.log import tiktok_logger


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
        await page.goto("https://www.tiktok.com/tiktokstudio/upload?lang=en", wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(5000)
        if "login" in page.url:
            tiktok_logger.error("[+] cookie expired")
            return False
        try:
            # 选择所有的 select 元素
            select_elements = await page.query_selector_all('select')
            for element in select_elements:
                class_name = await element.get_attribute('class')
                # 使用正则表达式匹配特定模式的 class 名称
                if re.match(r'tiktok-.*-SelectFormContainer.*', class_name):
                    tiktok_logger.error("[+] cookie expired")
                    return False
            tiktok_logger.success("[+] cookie valid")
            return True
        except:
            tiktok_logger.success("[+] cookie valid")
            return True


async def tiktok_setup(account_file, handle=False):
    account_file = get_absolute_path(account_file, "tk_uploader")
    if not os.path.exists(account_file) or not await cookie_auth(account_file):
        if not handle:
            return False
        tiktok_logger.info('[+] cookie file is not existed or expired. Now open the browser auto. Please login with your way(gmail phone, whatever, the cookie file will generated after login')
        await get_tiktok_cookie(account_file)
    return True


async def get_tiktok_cookie(account_file):
    async with async_playwright() as playwright:
        options = {
            'args': [
                '--lang en-GB',
            ],
            'headless': LOCAL_CHROME_HEADLESS,  # Set headless option here
            'executable_path': LOCAL_CHROME_PATH or None,
        }
        # Make sure to run headed.
        browser = await playwright.chromium.launch(**options)
        # Setup context however you like.
        context = await browser.new_context()  # Pass any options
        context = await set_init_script(context)
        # Pause the page, and start recording manually.
        page = await context.new_page()
        await page.goto("https://www.tiktok.com/login?lang=en")
        for _ in range(120):
            await page.wait_for_timeout(3000)
            if "login" not in page.url:
                await context.storage_state(path=account_file)
                await browser.close()
                tiktok_logger.success("[+] cookie saved")
                return
        await context.storage_state(path=account_file)
        await browser.close()
        tiktok_logger.warning("[+] login wait timeout, saved current cookie")


class TiktokVideo(object):
    def __init__(self, title, file_path, tags, publish_date, account_file, thumbnail_path=None):
        self.title = title
        self.file_path = file_path
        self.tags = tags
        self.publish_date = publish_date
        self.thumbnail_path = thumbnail_path
        self.account_file = account_file
        self.local_executable_path = LOCAL_CHROME_PATH
        self.headless = LOCAL_CHROME_HEADLESS
        self.locator_base = None

    async def wait_upload_entry(self, page):
        candidates = [
            ("上传区标题", page.get_by_text("选择要上传的视频", exact=True)),
            ("选择视频按钮", page.locator('button[data-e2e="select_video_button"]')),
            ("选择视频文字", page.get_by_text("选择视频", exact=True)),
            ("英文选择视频按钮", page.locator('button:has-text("Select video")')),
            ("上传页容器", page.locator("div.upload-stage-container, div.upload-container")),
            ("文件输入框", page.locator('input[type="file"]')),
            ("上传 iframe", page.locator('iframe[data-tt="Upload_index_iframe"], iframe[src*="upload"]')),
        ]
        last_error = None
        for _ in range(180):
            for label, locator in candidates:
                try:
                    if await locator.count():
                        tiktok_logger.info(f"Upload entry detected: {label}")
                        return
                except Exception as exc:
                    last_error = exc
            await page.wait_for_timeout(1000)

        title = ""
        url = ""
        screenshot_msg = "screenshot skipped"
        try:
            title = await page.title()
            url = page.url
            await page.screenshot(path="logs/tiktok_upload_page_timeout.png", full_page=True)
            screenshot_msg = "screenshot saved to logs/tiktok_upload_page_timeout.png"
        except Exception as screenshot_exc:
            screenshot_msg = f"screenshot failed: {screenshot_exc}"
        raise RuntimeError(
            f"Neither iframe nor upload container appeared. url={url}, title={title}. "
            f"{screenshot_msg}. last_error={last_error}"
        )

    async def select_video_file(self, page):
        input_candidates = [
            self.locator_base.locator('input[type="file"]').first,
            page.locator('input[type="file"]').first,
        ]
        for file_input in input_candidates:
            try:
                if await file_input.count():
                    await file_input.set_input_files(self.file_path)
                    tiktok_logger.info("Video file submitted via file input")
                    return
            except Exception as exc:
                tiktok_logger.info(f"File input upload attempt failed: {exc}")

        button_candidates = [
            self.locator_base.locator('button[data-e2e="select_video_button"]:visible').first,
            self.locator_base.locator('button:has-text("选择视频"):visible').first,
            self.locator_base.locator('button[aria-label="选择视频"]:visible').first,
            self.locator_base.locator('button:has-text("Select video"):visible').first,
            self.locator_base.locator('button:has-text("Upload"):visible').first,
            self.locator_base.locator('button[aria-label="Select file"]:visible').first,
            page.locator('button[data-e2e="select_video_button"]:visible').first,
            page.locator('button:has-text("选择视频"):visible').first,
            page.locator('button[aria-label="选择视频"]:visible').first,
            page.locator('button:has-text("Select video"):visible').first,
            page.locator('button:has-text("Upload"):visible').first,
            page.locator('button[aria-label="Select file"]:visible').first,
        ]
        last_error = None
        for button in button_candidates:
            try:
                if not await button.count():
                    continue
                await button.wait_for(state="visible", timeout=3000)
                async with page.expect_file_chooser() as fc_info:
                    await button.click(force=True)
                file_chooser = await fc_info.value
                await file_chooser.set_files(self.file_path)
                tiktok_logger.info("Video file submitted via select video button")
                return
            except Exception as exc:
                last_error = exc
                continue
        raise RuntimeError(f"未找到 TikTok 选择视频控件，最后错误: {last_error}")

    async def dismiss_upload_popups(self, page):
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(300)
        except Exception:
            pass

        button_texts = [
            "Continue",
            "Got it",
            "OK",
            "Okay",
            "I understand",
            "Done",
            "Start",
            "Confirm",
            "Close",
            "继续",
            "知道了",
            "我知道了",
            "确定",
            "确认",
            "完成",
            "关闭",
        ]
        for _ in range(3):
            clicked = False
            for text in button_texts:
                candidates = [
                    page.get_by_role("button", name=text, exact=True),
                    page.locator("button").filter(has_text=text),
                    page.locator('[role="button"]').filter(has_text=text),
                ]
                for button in candidates:
                    try:
                        if not await button.count():
                            continue
                        await button.first.click(force=True, timeout=1500)
                        tiktok_logger.info(f"Dismissed TikTok popup with button: {text}")
                        await page.wait_for_timeout(800)
                        clicked = True
                        break
                    except Exception:
                        continue
                if clicked:
                    break
            if not clicked:
                return

    async def confirm_publish_prompts(self, page):
        """Handle TikTok confirmation dialogs shown after clicking Post."""
        prompt_buttons = [
            "Turn on",
            "Continue",
            "Confirm",
            "OK",
            "开启",
            "打开",
            "继续",
            "确认",
            "确定",
            "立即发布",
        ]
        for _ in range(15):
            if "/tiktokstudio/content" in page.url:
                return
            clicked = False
            for text in prompt_buttons:
                candidates = [
                    page.locator('[role="dialog"] button').filter(has_text=text),
                    page.locator('[class*="modal"] button').filter(has_text=text),
                    page.locator('[class*="Modal"] button').filter(has_text=text),
                ]
                for button in candidates:
                    try:
                        if not await button.count():
                            continue
                        visible_button = button.first
                        if not await visible_button.is_visible(timeout=500):
                            continue
                        disabled = await visible_button.get_attribute("disabled")
                        aria_disabled = await visible_button.get_attribute("aria-disabled")
                        if disabled is not None or aria_disabled == "true":
                            continue
                        await visible_button.click(force=True, timeout=1500)
                        tiktok_logger.info(f"Confirmed TikTok publish prompt with button: {text}")
                        clicked = True
                        break
                    except Exception:
                        continue
                if clicked:
                    break
            await page.wait_for_timeout(1000 if clicked else 500)

    async def set_schedule_time(self, page, publish_date):
        schedule_input_element = self.locator_base.get_by_label('Schedule')
        await schedule_input_element.wait_for(state='visible')  # 确保按钮可见

        await schedule_input_element.click(force=True)
        if await self.locator_base.locator('div.TUXButton-content >> text=Allow').count():
            await self.locator_base.locator('div.TUXButton-content >> text=Allow').click()

        scheduled_picker = self.locator_base.locator('div.scheduled-picker')
        await scheduled_picker.locator('div.TUXInputBox').nth(1).click()

        calendar_month = await self.locator_base.locator(
            'div.calendar-wrapper span.month-title').inner_text()

        n_calendar_month = datetime.strptime(calendar_month, '%B').month

        schedule_month = publish_date.month

        if n_calendar_month != schedule_month:
            if n_calendar_month < schedule_month:
                arrow = self.locator_base.locator('div.calendar-wrapper span.arrow').nth(-1)
            else:
                arrow = self.locator_base.locator('div.calendar-wrapper span.arrow').nth(0)
            await arrow.click()

        # day set
        valid_days_locator = self.locator_base.locator(
            'div.calendar-wrapper span.day.valid')
        valid_days = await valid_days_locator.count()
        for i in range(valid_days):
            day_element = valid_days_locator.nth(i)
            text = await day_element.inner_text()
            if text.strip() == str(publish_date.day):
                await day_element.click()
                break
        # time set
        await scheduled_picker.locator('div.TUXInputBox').nth(0).click()

        hour_str = publish_date.strftime("%H")
        correct_minute = int(publish_date.minute / 5)
        minute_str = f"{correct_minute:02d}"

        hour_selector = f"span.tiktok-timepicker-left:has-text('{hour_str}')"
        minute_selector = f"span.tiktok-timepicker-right:has-text('{minute_str}')"

        # pick hour first
        await page.wait_for_timeout(1000)  # 等待500毫秒
        await self.locator_base.locator(hour_selector).click()
        # click time button again
        await page.wait_for_timeout(1000)  # 等待500毫秒
        # pick minutes after
        await self.locator_base.locator(minute_selector).click()

        # click title to remove the focus.
        # await self.locator_base.locator("h1:has-text('Upload video')").click()

    async def handle_upload_error(self, page):
        tiktok_logger.info("video upload error retrying.")
        select_file_button = self.locator_base.locator('button[aria-label="Select file"]')
        async with page.expect_file_chooser() as fc_info:
            await select_file_button.click()
        file_chooser = await fc_info.value
        await file_chooser.set_files(self.file_path)

    async def upload(self, playwright: Playwright) -> None:
        browser = await playwright.chromium.launch(
            headless=self.headless,
            executable_path=self.local_executable_path,
            args=[
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = await browser.new_context(storage_state=f"{self.account_file}")
        # context = await set_init_script(context)
        page = await context.new_page()

        await page.goto("https://www.tiktok.com/tiktokstudio/upload?lang=en", wait_until="domcontentloaded", timeout=90000)
        tiktok_logger.info(f'[+]Uploading-------{self.title}.mp4')

        if "login" in page.url:
            raise RuntimeError("TikTok cookie expired, please run web login again")

        try:
            await page.wait_for_url("**/tiktokstudio/upload**", timeout=30000)
        except Exception:
            tiktok_logger.info(f"Current TikTok URL after upload navigation: {page.url}")

        await self.wait_upload_entry(page)

        await self.choose_base_locator(page)
        await self.select_video_file(page)
        await self.dismiss_upload_popups(page)

        await self.add_title_tags(page)
        # detect upload status
        await self.detect_upload_status(page)
        if self.thumbnail_path:
            tiktok_logger.info(f'[+] Uploading thumbnail file {self.title}.png')
            try:
                await self.upload_thumbnails(page)
            except Exception as exc:
                tiktok_logger.warning(f"Thumbnail upload skipped after failure: {exc}")
                try:
                    await page.screenshot(path="logs/tiktok_thumbnail_upload_failed.png", full_page=True)
                except Exception:
                    pass
                await self.dismiss_upload_popups(page)
                try:
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(500)
                except Exception:
                    pass

        if self.publish_date != 0:
            await self.set_schedule_time(page, self.publish_date)

        await self.click_publish(page)
        tiktok_logger.success(f"video_id: {await self.get_last_video_id(page)}")

        await context.storage_state(path=f"{self.account_file}")  # save cookie
        tiktok_logger.info('  [-] update cookie！')
        await asyncio.sleep(2)  # close delay for look the video status
        # close all
        await context.close()
        await browser.close()

    async def add_title_tags(self, page):

        editor_locator = self.locator_base.locator('div.public-DraftEditor-content')
        try:
            await editor_locator.click(timeout=5000)
        except Exception:
            await self.dismiss_upload_popups(page)
            await editor_locator.click(force=True, timeout=10000)

        await page.keyboard.press("End")

        await page.keyboard.press("Control+A")

        await page.keyboard.press("Delete")

        await page.keyboard.press("End")

        await page.wait_for_timeout(1000)  # 等待1秒

        await page.keyboard.insert_text(self.title)
        await page.wait_for_timeout(1000)  # 等待1秒
        await page.keyboard.press("End")

        await page.keyboard.press("Enter")

        # tag part
        for index, tag in enumerate(self.tags, start=1):
            tiktok_logger.info("Setting the %s tag" % index)
            await page.keyboard.press("End")
            await page.wait_for_timeout(1000)  # 等待1秒
            await page.keyboard.insert_text("#" + tag + " ")
            await page.keyboard.press("Space")
            await page.wait_for_timeout(1000)  # 等待1秒

            await page.keyboard.press("Backspace")
            await page.keyboard.press("End")

    async def upload_thumbnails(self, page):
        await self.dismiss_upload_popups(page)
        cover_container = self.locator_base.locator(".cover-container")
        try:
            await cover_container.click(timeout=5000)
        except Exception:
            await self.dismiss_upload_popups(page)
            await cover_container.click(force=True, timeout=10000)

        upload_cover = self.locator_base.locator(".cover-edit-container >> text=Upload cover")
        if not await upload_cover.count():
            upload_cover = self.locator_base.locator(
                'text=Upload cover, text=上传封面, button:has-text("Upload cover"), button:has-text("上传封面")'
            )
        if await upload_cover.count():
            await upload_cover.first.click(force=True, timeout=5000)

        image_input = self.locator_base.locator(
            'input[type="file"][accept*="image"], input[type="file"][accept*="jpg"], input[type="file"][accept*="png"]'
        ).first
        if await image_input.count():
            await image_input.set_input_files(self.thumbnail_path)
        else:
            upload_area = self.locator_base.locator(
                '.upload-image-upload-area, [class*="upload"]:has-text("Upload"), [class*="upload"]:has-text("上传")'
            ).first
            await upload_area.wait_for(state="visible", timeout=5000)
            async with page.expect_file_chooser() as fc_info:
                await upload_area.click(force=True)
            file_chooser = await fc_info.value
            await file_chooser.set_files(self.thumbnail_path)

        confirm_candidates = [
            self.locator_base.locator(
                'div.cover-edit-panel:not(.hide-panel) button:has-text("Save"), '
                'div.cover-edit-panel:not(.hide-panel) button:has-text("保存"), '
                'div.cover-edit-panel:not(.hide-panel) button:has-text("Confirm"), '
                'div.cover-edit-panel:not(.hide-panel) button:has-text("确认"), '
                'div.cover-edit-panel:not(.hide-panel) button:has-text("Done"), '
                'div.cover-edit-panel:not(.hide-panel) button:has-text("完成")'
            ).first,
            self.locator_base.locator(
                'button:has-text("Save"), button:has-text("保存"), '
                'button:has-text("Confirm"), button:has-text("确认"), '
                'button:has-text("Done"), button:has-text("完成")'
            ).first,
            page.locator(
                'button:has-text("Save"), button:has-text("保存"), '
                'button:has-text("Confirm"), button:has-text("确认"), '
                'button:has-text("Done"), button:has-text("完成")'
            ).first,
            page.locator('.Button__content:has-text("保存"), .Button__content:has-text("Save")').first,
        ]
        for confirm_button in confirm_candidates:
            if await confirm_button.count():
                await confirm_button.click(force=True, timeout=5000)
                tiktok_logger.info("Thumbnail upload confirmed")
                break
        else:
            tiktok_logger.warning("Thumbnail file submitted, but no confirm button was found")
        await page.wait_for_timeout(3000)  # wait 3s, fix it later

    async def change_language(self, page):
        # set the language to english
        await page.goto("https://www.tiktok.com")
        await page.wait_for_load_state('domcontentloaded')
        await page.wait_for_selector('[data-e2e="nav-more-menu"]')
        # 已经设置为英文, 省略这个步骤
        if await page.locator('[data-e2e="nav-more-menu"]').text_content() == "More":
            return

        await page.locator('[data-e2e="nav-more-menu"]').click()
        await page.locator('[data-e2e="language-select"]').click()
        await page.locator('#creator-tools-selection-menu-header >> text=English (US)').click()

    async def click_publish(self, page):
        for attempt in range(1, 11):
            try:
                await self.dismiss_upload_popups(page)
                button_candidates = [
                    self.locator_base.locator('button[data-e2e="post_video_button"]:visible').first,
                    self.locator_base.locator('[data-e2e="post_video_button"] button:visible').first,
                    self.locator_base.locator('button:has-text("Post"):visible').first,
                    self.locator_base.locator('button:has-text("发布"):visible').first,
                    page.locator('button[data-e2e="post_video_button"]:visible').first,
                    page.locator('[data-e2e="post_video_button"] button:visible').first,
                    page.locator('button:has-text("Post"):visible').first,
                    page.locator('button:has-text("发布"):visible').first,
                ]
                publish_button = None
                for candidate in button_candidates:
                    if await candidate.count():
                        publish_button = candidate
                        break
                if publish_button is None:
                    await page.screenshot(path="logs/tiktok_publish_button_not_found.png", full_page=True)
                    raise RuntimeError("未找到 TikTok 发布按钮")

                await publish_button.scroll_into_view_if_needed(timeout=3000)
                disabled = await publish_button.get_attribute("disabled")
                aria_disabled = await publish_button.get_attribute("aria-disabled")
                if disabled is not None or aria_disabled == "true":
                    raise RuntimeError("TikTok 发布按钮仍处于禁用状态")
                await publish_button.click(force=True, timeout=10000)

                await self.confirm_publish_prompts(page)
                await page.wait_for_url("**/tiktokstudio/content**", timeout=10000)
                tiktok_logger.success("  [-] video published success")
                return
            except Exception as e:
                tiktok_logger.exception(f"  [-] publish attempt {attempt}/10 failed: {e}")
                tiktok_logger.info("  [-] video publishing")
                await asyncio.sleep(0.5)
        await page.screenshot(path="logs/tiktok_publish_timeout.png", full_page=True)
        raise RuntimeError("TikTok 发布未在最大重试次数内完成")

    async def get_last_video_id(self, page):
        await page.wait_for_selector('div[data-tt="components_PostTable_Container"]')
        video_list_locator = self.locator_base.locator('div[data-tt="components_PostTable_Container"] div[data-tt="components_PostInfoCell_Container"] a')
        if await video_list_locator.count():
            first_video_obj = await video_list_locator.nth(0).get_attribute('href')
            video_id = re.search(r'video/(\d+)', first_video_obj).group(1) if first_video_obj else None
            return video_id


    async def detect_upload_status(self, page):
        while True:
            try:
                # if await self.locator_base.locator('div.btn-post > button').get_attribute("disabled") is None:
                post_button = self.locator_base.locator(
                    'button:has-text("Post"), button:has-text("发布"), div.button-group > button'
                ).first
                if await post_button.get_attribute("disabled") is None:
                    tiktok_logger.info("  [-]video uploaded.")
                    break
                else:
                    tiktok_logger.info("  [-] video uploading...")
                    await asyncio.sleep(2)
                    if await self.locator_base.locator(
                            'button[aria-label="Select file"]').count():
                        tiktok_logger.info("  [-] found some error while uploading now retry...")
                        await self.handle_upload_error(page)
            except:
                tiktok_logger.info("  [-] video uploading...")
                await asyncio.sleep(2)

    async def choose_base_locator(self, page):
        # await page.wait_for_selector('div.upload-container')
        if await page.locator('iframe[data-tt="Upload_index_iframe"]').count():
            self.locator_base = page.frame_locator(Tk_Locator.tk_iframe)
        else:
            self.locator_base = page.locator(Tk_Locator.default) 

    async def main(self):
        async with async_playwright() as playwright:
            await self.upload(playwright)
