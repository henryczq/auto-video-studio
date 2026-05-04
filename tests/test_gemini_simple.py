#!/usr/bin/env python3
"""最简单的 Gemini 测试 - 使用普通浏览器启动"""

import asyncio
from pathlib import Path

async def main():
    from playwright.async_api import async_playwright
    
    profile = Path.home() / '.auto-video-studio/nodriver_profile'
    chrome_path = '/usr/bin/google-chrome'
    
    print(f"Profile: {profile}")
    print(f"Chrome: {chrome_path}")
    print(f"Profile exists: {profile.exists()}")
    
    async with async_playwright() as p:
        # 方法1: 使用普通 launch + storage_state
        print("\n方法1: 使用普通 launch + context...")
        browser = await p.chromium.launch(
            headless=False,
            executable_path=chrome_path,
            args=['--user-data-dir=' + str(profile)]
        )
        context = await browser.new_context()
        page = await context.new_page()
        
        print("访问 Gemini...")
        await page.goto('https://gemini.google.com/app', wait_until='domcontentloaded')
        await page.wait_for_timeout(5000)
        
        print(f"URL: {page.url}")
        
        # 检查登录状态
        if 'signin' in page.url.lower() or 'accounts.google.com' in page.url:
            print("❌ 需要登录")
        else:
            print("✅ 已登录!")
            # 检查是否有输入框
            try:
                await page.wait_for_selector('[contenteditable="true"]', timeout=5000)
                print("✅ 找到输入框")
            except:
                print("⚠️  未找到输入框")
        
        input("\n按 Enter 关闭浏览器...")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
