# -*- coding: utf-8 -*-
"""调试脚本：获取B站上传页面的HTML结构和input元素信息."""

import asyncio
import json
from playwright.async_api import async_playwright
from conf import LOCAL_CHROME_PATH, HEADLESS

COOKIE_FILE = "/home/zzgzczq/12-video/01-auto-video-studio/publish/bilibili-web-upload/cookies/bilibili_web_uploader/b站.json"


async def debug_upload_page():
    """打开B站上传页面，获取页面结构和input元素信息."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=HEADLESS,
            executable_path=LOCAL_CHROME_PATH or None,
        )
        context = await browser.new_context(
            storage_state=str(COOKIE_FILE),
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.150 Safari/537.36',
            viewport={"width": 1920, "height": 1080}
        )
        page = await context.new_page()

        print("正在打开B站上传页面...")
        await page.goto(
            "https://member.bilibili.com/platform/upload/video/frame",
            timeout=120000,
            wait_until="domcontentloaded"
        )

        # 等待页面加载
        print("等待3秒...")
        await page.wait_for_timeout(3000)

        # 检查是否有iframe
        frames = page.frames
        print(f"\n页面帧数量: {len(frames)}")
        for i, frame in enumerate(frames):
            print(f"  Frame {i}: {frame.url}")

        # 获取页面HTML
        html = await page.content()
        print(f"\n页面HTML长度: {len(html)}")

        # 保存HTML到文件
        with open("/tmp/bilibili_page.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("HTML已保存到 /tmp/bilibili_page.html")

        # 查找所有input[type='file']
        file_inputs = await page.query_selector_all("input[type='file']")
        print(f"\n找到 {len(file_inputs)} 个 input[type='file']")

        for i, inp in enumerate(file_inputs):
            attrs = await inp.evaluate("""
                el => ({
                    accept: el.accept,
                    multiple: el.multiple,
                    style: el.style.cssText,
                    display: window.getComputedStyle(el).display,
                    visibility: window.getComputedStyle(el).visibility,
                    parentTag: el.parentElement ? el.parentElement.tagName : null,
                    parentClass: el.parentElement ? el.parentElement.className : null,
                    parentId: el.parentElement ? el.parentElement.id : null,
                    outerHTML: el.outerHTML.substring(0, 200)
                })
            """)
            print(f"\n  Input {i}: {json.dumps(attrs, ensure_ascii=False, indent=4)}")

        # 查找上传区域
        upload_areas = await page.query_selector_all("div.upload-area, div.bcc-upload-wrapper")
        print(f"\n找到 {len(upload_areas)} 个上传区域")
        for i, area in enumerate(upload_areas):
            html_snippet = await area.evaluate("el => el.outerHTML.substring(0, 300)")
            print(f"  区域 {i}: {html_snippet}")

        # 检查是否有Shadow DOM
        shadow_hosts = await page.evaluate("""
            () => {
                const all = document.querySelectorAll('*');
                const hosts = [];
                for (const el of all) {
                    if (el.shadowRoot) {
                        hosts.push({
                            tag: el.tagName,
                            class: el.className,
                            id: el.id,
                            shadowHtml: el.shadowRoot.innerHTML.substring(0, 200)
                        });
                    }
                }
                return hosts;
            }
        """)
        print(f"\nShadow DOM hosts: {json.dumps(shadow_hosts, ensure_ascii=False, indent=4)}")

        # 截图
        await page.screenshot(path="/tmp/bilibili_debug.png", full_page=True)
        print("\n截图已保存到 /tmp/bilibili_debug.png")

        print("\n等待10秒后关闭...")
        await page.wait_for_timeout(10000)
        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(debug_upload_page())
