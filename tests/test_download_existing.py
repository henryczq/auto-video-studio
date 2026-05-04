#!/usr/bin/env python3
"""测试从已有的 Gemini 对话页面下载图片 - 支持 Blob URL"""

import asyncio
import base64
from pathlib import Path
from playwright.async_api import async_playwright

# 配置
CHROME_PATH = "/usr/bin/google-chrome"
NODRIVER_PROFILE = Path.home() / ".auto-video-studio" / "nodriver_profile"
DOWNLOAD_DIR = Path.home() / "Downloads"


async def download_from_existing_chat(url: str):
    """从已有的 Gemini 对话页面下载图片"""
    
    async with async_playwright() as p:
        # 启动 Chrome
        chrome_path = CHROME_PATH if Path(CHROME_PATH).exists() else None
        
        print(f"[test] Launching Chrome...")
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(NODRIVER_PROFILE),
            headless=False,
            executable_path=chrome_path,
            args=[
                "--lang=zh-CN",
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ],
            viewport={"width": 1280, "height": 800},
        )
        
        page = context.pages[0] if context.pages else await context.new_page()
        
        try:
            print(f"[test] Navigating to: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(8000)  # 等待页面完全渲染
            
            print(f"[test] Page loaded: {page.url}")
            
            # 查找所有生成的图片容器
            print("[test] Looking for generated images...")
            
            # 查找所有大图片
            all_images = await page.query_selector_all("img")
            print(f"[test] Found {len(all_images)} total images")
            
            downloaded = []
            
            for i, img in enumerate(all_images):
                try:
                    # 获取图片信息
                    info = await img.evaluate("""el => {
                        const rect = el.getBoundingClientRect();
                        return {
                            width: el.naturalWidth || el.width || rect.width,
                            height: el.naturalHeight || el.height || rect.height,
                            src: el.src || '',
                            visible: rect.width > 0 && rect.height > 0
                        };
                    }""")
                    
                    # 只处理大图片（生成的图片通常 > 500px）
                    if info['width'] >= 500 and info['height'] >= 500:
                        print(f"[test] Found large image {i+1}: {info['width']}x{info['height']}")
                        print(f"[test] Src type: {'blob' if info['src'].startswith('blob:') else 'http'}")
                        
                        # 滚动到图片位置
                        await img.scroll_into_view_if_needed()
                        await page.wait_for_timeout(1000)
                        
                        dest_path = DOWNLOAD_DIR / f"gemini_generated_{i+1}.jpg"
                        
                        # 策略1: 如果是 Blob URL，使用 Canvas 提取
                        if info['src'].startswith('blob:'):
                            print(f"[test] Using Canvas extraction for blob URL...")
                            try:
                                img_data = await img.evaluate("""el => {
                                    return new Promise((resolve, reject) => {
                                        try {
                                            const canvas = document.createElement('canvas');
                                            canvas.width = el.naturalWidth || el.width;
                                            canvas.height = el.naturalHeight || el.height;
                                            const ctx = canvas.getContext('2d');
                                            ctx.drawImage(el, 0, 0);
                                            resolve(canvas.toDataURL('image/jpeg', 0.95));
                                        } catch (e) {
                                            reject(e.toString());
                                        }
                                    });
                                }""")
                                
                                if img_data and img_data.startswith('data:image'):
                                    header, encoded = img_data.split(',', 1)
                                    data = base64.b64decode(encoded)
                                    
                                    with open(dest_path, 'wb') as f:
                                        f.write(data)
                                    
                                    if dest_path.exists() and dest_path.stat().st_size > 10000:
                                        print(f"[test] ✓ Extracted via Canvas: {dest_path.name} ({dest_path.stat().st_size} bytes)")
                                        downloaded.append(str(dest_path))
                                        continue
                            except Exception as e:
                                print(f"[test] Canvas extraction failed: {e}")
                        
                        # 策略2: 如果是 HTTP URL，直接下载
                        elif info['src'].startswith('http') and any(domain in info['src'] for domain in ["googleusercontent.com", "gstatic.com"]):
                            try:
                                import urllib.request
                                req = urllib.request.Request(info['src'], headers={
                                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                                })
                                with urllib.request.urlopen(req, timeout=30) as response:
                                    with open(dest_path, 'wb') as f:
                                        f.write(response.read())
                                
                                if dest_path.exists() and dest_path.stat().st_size > 10000:
                                    print(f"[test] ✓ Downloaded directly: {dest_path.name} ({dest_path.stat().st_size} bytes)")
                                    downloaded.append(str(dest_path))
                                    continue
                            except Exception as e:
                                print(f"[test] Direct download failed: {e}")
                        
                        # 策略3: 尝试点击下载按钮
                        try:
                            # 鼠标悬停显示下载按钮
                            await img.hover()
                            await page.wait_for_timeout(500)
                            
                            download_btn = await page.query_selector('mat-icon[fonticon="download"], [aria-label="下载"]')
                            if download_btn:
                                await download_btn.click()
                                print(f"[test] Clicked download button for image {i+1}")
                                await page.wait_for_timeout(3000)
                        except Exception as e:
                            print(f"[test] Download button click failed: {e}")
                                
                except Exception as e:
                    print(f"[test] Error processing image {i+1}: {e}")
            
            print(f"\n[test] Total downloaded: {len(downloaded)} images")
            for path in downloaded:
                print(f"  - {path}")
            
            # 检查下载目录中的新文件
            print("\n[test] Checking download directory for gemini_generated_* files...")
            new_files = list(DOWNLOAD_DIR.glob("gemini_generated_*.jpg"))
            if new_files:
                for f in sorted(new_files):
                    print(f"  - {f.name} ({f.stat().st_size} bytes)")
            else:
                print("  No gemini_generated_* files found")
            
            # 保持页面打开一段时间
            print("\n[test] Keeping browser open for 5 seconds...")
            await page.wait_for_timeout(5000)
            
        except Exception as e:
            print(f"[test] Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await context.close()
            print("[test] Browser closed")


if __name__ == "__main__":
    url = "https://gemini.google.com/app/817ab0a0728bc67e"
    asyncio.run(download_from_existing_chat(url))
