# -*- coding: utf-8 -*-
"""调试脚本：测试B站文件上传流程."""

import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

COOKIE_FILE = "/home/zzgzczq/12-video/01-auto-video-studio/publish/bilibili-web-upload/cookies/bilibili_web_uploader/b站.json"
TEST_VIDEO = "/home/zzgzczq/12-video/01-auto-video-studio/videos/web_jobs/6786acd9/final_replace_audio_subtitled.mp4"


async def debug_upload():
    """测试文件上传."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=False,
        )
        context = await browser.new_context(
            storage_state=COOKIE_FILE,
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.150 Safari/537.36',
            viewport={"width": 1920, "height": 1080}
        )
        page = await context.new_page()

        print("=" * 60)
        print("步骤1: 打开B站上传页面")
        print("=" * 60)
        await page.goto(
            "https://member.bilibili.com/platform/upload/video/frame",
            timeout=120000,
            wait_until="domcontentloaded"
        )
        print(f"页面URL: {page.url}")

        print("\n等待5秒让页面完全加载...")
        await page.wait_for_timeout(5000)

        print("\n" + "=" * 60)
        print("步骤2: 检查页面上的文件输入框")
        print("=" * 60)

        inputs_info = await page.evaluate("""
            () => {
                const inputs = document.querySelectorAll('input[type="file"]');
                return Array.from(inputs).map((input, i) => ({
                    index: i,
                    accept: input.accept,
                    name: input.name,
                    id: input.id,
                    style: input.style.cssText,
                    parentTag: input.parentElement ? input.parentElement.tagName : null,
                    parentClass: input.parentElement ? input.parentElement.className : null,
                    parentId: input.parentElement ? input.parentElement.id : null,
                    display: window.getComputedStyle(input).display,
                    visibility: window.getComputedStyle(input).visibility,
                    width: input.offsetWidth,
                    height: input.offsetHeight,
                    outerHTML: input.outerHTML
                }));
            }
        """)

        for info in inputs_info:
            print(f"\nInput {info['index']}:")
            print(f"  name: {info['name']}")
            print(f"  accept: {info['accept']}")
            print(f"  display: {info['display']}")
            print(f"  visibility: {info['visibility']}")
            print(f"  width x height: {info['width']} x {info['height']}")
            print(f"  parentId: {info['parentId']}")
            print(f"  outerHTML: {info['outerHTML'][:150]}")

        print("\n" + "=" * 60)
        print("步骤3: 尝试设置文件到各个 input")
        print("=" * 60)

        # 方法1: 直接设置到 input[name='buploader']
        print("\n方法1: 设置到 input[name='buploader']")
        try:
            buploader = page.locator("input[name='buploader']").first
            count = await buploader.count()
            print(f"  找到 {count} 个 input[name='buploader']")
            if count > 0:
                await buploader.set_input_files(TEST_VIDEO, timeout=10000)
                print("  ✓ 设置成功")
            else:
                print("  ✗ 未找到")
        except Exception as e:
            print(f"  ✗ 失败: {e}")

        # 等待看是否有反应
        print("\n等待5秒观察页面变化...")
        await page.wait_for_timeout(5000)

        # 检查页面是否有上传中的迹象
        print("\n" + "=" * 60)
        print("步骤4: 检查页面上传状态")
        print("=" * 60)

        page_text = await page.content()
        status_keywords = ["上传中", "上传完成", "处理中", "转码中", "封面上传中", "稿件标题", "视频信息"]
        for keyword in status_keywords:
            if keyword in page_text:
                print(f"  页面包含关键词: '{keyword}'")

        # 检查是否有进度条
        progress_bars = await page.query_selector_all("div[class*='progress'], div[class*='Progress'], .b-progress")
        print(f"\n  找到 {len(progress_bars)} 个可能的进度条元素")

        # 截图
        await page.screenshot(path="/tmp/bilibili_after_setfile.png", full_page=True)
        print("\n  截图已保存到 /tmp/bilibili_after_setfile.png")

        print("\n" + "=" * 60)
        print("步骤5: 尝试点击'上传视频'按钮后再设置文件")
        print("=" * 60)

        # 尝试点击上传按钮
        try:
            # 找上传按钮
            upload_btn = page.locator("button:has-text('上传视频'), div:has-text('上传视频')").first
            btn_count = await upload_btn.count()
            print(f"\n  找到 {btn_count} 个'上传视频'按钮/区域")

            if btn_count > 0:
                print("  尝试点击...")
                await upload_btn.click(timeout=5000)
                print("  ✓ 点击成功")
                await page.wait_for_timeout(2000)
        except Exception as e:
            print(f"  点击失败: {e}")

        # 方法2: 尝试触发 input 的 click 事件
        print("\n方法2: 尝试触发 input 的 click 事件")
        try:
            result = await page.evaluate("""
                () => {
                    const input = document.querySelector('input[name="buploader"]');
                    if (input) {
                        input.click();
                        return 'clicked';
                    }
                    return 'not found';
                }
            """)
            print(f"  结果: {result}")
        except Exception as e:
            print(f"  失败: {e}")

        # 方法3: 创建新的 File 对象并触发 change 事件
        print("\n方法3: 尝试通过 CDP 设置文件")
        try:
            # 获取 input 的 element handle
            input_handle = await page.query_selector("input[name='buploader']")
            if input_handle:
                await input_handle.set_input_files(TEST_VIDEO)
                print("  ✓ 通过 element handle 设置成功")
            else:
                print("  ✗ 未找到 element handle")
        except Exception as e:
            print(f"  ✗ 失败: {e}")

        print("\n等待10秒...")
        await page.wait_for_timeout(10000)

        # 再次检查状态
        print("\n" + "=" * 60)
        print("步骤6: 最终状态检查")
        print("=" * 60)
        page_text = await page.content()
        for keyword in status_keywords:
            if keyword in page_text:
                print(f"  页面包含关键词: '{keyword}'")

        await page.screenshot(path="/tmp/bilibili_final.png", full_page=True)
        print("\n  最终截图已保存到 /tmp/bilibili_final.png")

        print("\n按 Enter 键关闭浏览器...")
        input()
        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(debug_upload())
