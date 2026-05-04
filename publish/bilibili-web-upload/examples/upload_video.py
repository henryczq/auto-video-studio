# -*- coding: utf-8 -*-
"""B站网页投稿示例.

使用方式:
1. 直接运行会自动打开浏览器让你扫码登录
2. 登录后cookie会保存，下次运行会复用cookie

参数说明:
--login     重新登录
--file      指定视频文件路径
--title     视频标题(可选，从同名txt读取)
--tags      标签，逗号分隔(可选)
--category  分区，如 vlog, game, tech 等(默认: vlog)
--copyright 1=自制, 2=转载(默认: 1)
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.web_uploader import bilibili_setup, BilibiliWebVideo
from conf import COOKIE_FILE, VIDEO_DIR


def get_video_title(file_path: Path):
    """获取视频标题和标签，从同名txt文件读取."""
    txt_file = file_path.with_suffix('.txt')
    if txt_file.exists():
        try:
            with open(txt_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                lines = content.split('\n')
                title = lines[0]
                tags = [t.strip('#').strip() for t in lines[1].split() if t.strip('#')] if len(lines) > 1 else []
                return title, tags
        except Exception:
            pass
    return file_path.stem, []


async def upload_video(
    file_path: Path,
    title: str = None,
    tags: list = None,
    category: str = "vlog",
    copyright: int = 1,
):
    """上传单个视频."""
    if title is None:
        title, file_tags = get_video_title(file_path)
        tags = tags or file_tags

    print(f"\n开始上传: {file_path.name}")
    print(f"  标题: {title}")
    print(f"  标签: {tags}")
    print(f"  分区: {category}")
    print(f"  类型: {'自制' if copyright == 1 else '转载'}")

    uploader = BilibiliWebVideo(
        title=title,
        file_path=str(file_path),
        tags=tags,
        category=category,
        copyright=copyright,
    )
    result = await uploader.run()
    print(f"\n结果: {result}")
    return result


async def batch_upload(category: str = "vlog", copyright: int = 1):
    """批量上传 videos 目录下的所有视频."""
    if not VIDEO_DIR.exists():
        print(f"视频目录不存在: {VIDEO_DIR}")
        return

    video_extensions = {'.mp4', '.flv', '.avi', '.wmv', '.mov', '.webm', '.mpeg4', '.ts', '.mpg'}
    files = []
    for ext in video_extensions:
        files.extend(VIDEO_DIR.glob(f"*{ext}"))
        files.extend(VIDEO_DIR.glob(f"*{ext.upper()}"))

    if not files:
        print("未找到视频文件，请将视频放到 videos 目录")
        return

    print(f"找到 {len(files)} 个视频文件")

    for file_path in sorted(files):
        await upload_video(file_path, category=category, copyright=copyright)


async def main():
    import argparse

    parser = argparse.ArgumentParser(description='B站网页投稿工具')
    parser.add_argument('--login', action='store_true', help='重新登录')
    parser.add_argument('--file', type=str, help='指定视频文件路径')
    parser.add_argument('--title', type=str, help='视频标题(可选，从同名txt读取)')
    parser.add_argument('--tags', type=str, help='标签，逗号分隔(可选)')
    parser.add_argument('--category', type=str, default='vlog',
                        help='分区，如 vlog, game, tech 等(默认: vlog)')
    parser.add_argument('--copyright', type=int, default=1, choices=[1, 2],
                        help='1=自制, 2=转载(默认: 1)')
    parser.add_argument('--headless', action='store_true', default=False,
                        help='无头模式运行(不显示浏览器窗口)')
    args = parser.parse_args()

    if args.login:
        result = await bilibili_setup(str(COOKIE_FILE), handle=True)
        if result:
            print("登录成功！")
        return

    if not COOKIE_FILE.exists():
        print("Cookie不存在，正在打开浏览器登录...")
        await bilibili_setup(str(COOKIE_FILE), handle=True)

    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"视频文件不存在: {file_path}")
            return
        tags = args.tags.split(',') if args.tags else None
        await upload_video(
            file_path,
            title=args.title,
            tags=tags,
            category=args.category,
            copyright=args.copyright,
        )
    else:
        await batch_upload(category=args.category, copyright=args.copyright)


if __name__ == '__main__':
    asyncio.run(main())
