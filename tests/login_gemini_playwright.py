#!/usr/bin/env python3
"""使用 Playwright 登录 Gemini"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, '/home/zzgzczq/12-video/01-auto-video-studio/web/backend')

from playwright.async_api import async_playwright

NODRIVER_PROFILE = Path.home() / ".auto-video-studio" / "nodriver_profile"
CHROME_PATH = "/usr/bin/google-chrome"


async def login_gemini():
    """登录 Gemini"""
    print("="*60)
    print("Gemini 登录助手")
    print("="*60)
    print()
    print("此脚本将打开 Chrome 并导航到 Gemini 登录页面")
    print("请在浏览器中完成登录")
    print("登录信息将自动保存，供后续使用")
    print()

    async with async_playwright() as p:
        chrome_path = CHROME_PATH if Path(CHROME_PATH).exists() else None

        print("正在启动 Chrome...")

        # 使用 persistent context 来保存登录状态
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(NODRIVER_PROFILE),
            headless=False,
            executable_path=chrome_path,
            args=["--lang=zh-CN"],
            viewport={"width": 1280, "height": 800},
        )

        # 获取或创建页面
        pages = context.pages
        if pages:
            page = pages[0]
        else:
            page = await context.new_page()

        # 导航到 Gemini
        print("正在打开 Gemini...")
        await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        print(f"当前页面: {page.url}")

        # 检查是否需要登录
        if "accounts.google.com" in page.url or "signin" in page.url.lower():
            print()
            print("="*60)
            print("请在浏览器窗口中登录 Gemini")
            print("登录完成后，按 Enter 键退出此脚本")
            print("="*60)
            print()

            # 等待用户按 Enter
            input("按 Enter 键退出...")
        else:
            print()
            print("="*60)
            print("✓ 已登录 Gemini!")
            print("="*60)
            print()
            await page.wait_for_timeout(3000)

        await context.close()


if __name__ == "__main__":
    asyncio.run(login_gemini())
