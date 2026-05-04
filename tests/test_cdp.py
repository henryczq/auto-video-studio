#!/usr/bin/env python3
"""通过 CDP 连接到已运行的 Chrome"""

import asyncio
import re

async def main():
    from playwright.async_api import async_playwright
    
    # 从进程获取调试端口
    import subprocess
    result = subprocess.run(['pgrep', '-f', 'remote-debugging-port'], capture_output=True, text=True)
    
    if not result.stdout.strip():
        print("没有找到 Chrome 进程")
        return
    
    # 获取端口号
    pid = result.stdout.strip().split('\n')[0]
    cmdline = subprocess.run(['ps', '-p', pid, '-o', 'command='], capture_output=True, text=True)
    match = re.search(r'--remote-debugging-port=(\d+)', cmdline.stdout)
    
    if not match:
        print("没有找到调试端口")
        return
    
    port = match.group(1)
    ws_endpoint = f"http://localhost:{port}"
    print(f"连接到 Chrome: {ws_endpoint}")
    
    async with async_playwright() as p:
        try:
            # 通过 CDP 连接
            browser = await p.chromium.connect_over_cdp(ws_endpoint)
            print(f"✓ 已连接，上下文数量: {len(browser.contexts)}")
            
            if browser.contexts:
                context = browser.contexts[0]
                print(f"✓ 页面数量: {len(context.pages)}")
                
                if context.pages:
                    page = context.pages[0]
                    print(f"当前页面: {page.url}")
                    
                    # 导航到 Gemini
                    await page.goto('https://gemini.google.com/app')
                    await page.wait_for_timeout(3000)
                    
                    print(f"导航后 URL: {page.url}")
                    
                    if 'signin' in page.url.lower():
                        print("❌ 需要登录")
                    else:
                        print("✅ 已登录!")
                        # 测试输入
                        try:
                            await page.wait_for_selector('[contenteditable="true"]', timeout=5000)
                            print("✅ 找到输入框")
                        except:
                            print("⚠️ 未找到输入框")
                else:
                    print("没有页面")
            else:
                print("没有上下文")
                
        except Exception as e:
            print(f"错误: {e}")

if __name__ == "__main__":
    asyncio.run(main())
