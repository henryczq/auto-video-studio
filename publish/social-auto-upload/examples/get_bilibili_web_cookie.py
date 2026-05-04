# -*- coding: utf-8 -*-
"""
获取B站网页投稿cookie

运行此脚本会自动打开浏览器，让你扫码登录B站账号
登录成功后cookie会保存到 cookies/bilibili_web_uploader/account.json
"""
import asyncio
from pathlib import Path

from conf import BASE_DIR
from uploader.bilibili_web_uploader.main import bilibili_setup


async def main():
    account_file = Path(BASE_DIR) / "cookies" / "bilibili_web_uploader" / "account.json"
    account_file.parent.mkdir(parents=True, exist_ok=True)

    print("正在打开浏览器，请扫码登录B站...")
    print(f"Cookie将保存到: {account_file}")

    result = await bilibili_setup(str(account_file), handle=True)

    if result:
        print("\n登录成功！Cookie已保存。")
    else:
        print("\n登录遇到问题，请重试。")


if __name__ == '__main__':
    asyncio.run(main())
