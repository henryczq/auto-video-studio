# -*- coding: utf-8 -*-
"""获取B站网页投稿cookie.

运行此脚本会自动打开浏览器，让你扫码登录B站账号
登录成功后cookie会保存到 cookies/bilibili_web_uploader/account.json
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.web_uploader import bilibili_setup
from conf import COOKIE_FILE


async def main():
    COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)

    print("正在打开浏览器，请扫码登录B站...")
    print(f"Cookie将保存到: {COOKIE_FILE}")

    result = await bilibili_setup(str(COOKIE_FILE), handle=True)

    if result:
        print("\n登录成功！Cookie已保存。")
    else:
        print("\n登录遇到问题，请重试。")


if __name__ == '__main__':
    asyncio.run(main())
