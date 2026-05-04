# -*- coding: utf-8 -*-
"""
B站网页投稿示例

使用方式:
1. 直接运行会自动打开浏览器让你扫码登录
2. 登录后cookie会保存，下次运行会复用cookie

依赖:
- 需要将视频文件放到 videos 目录
- 可选：创建同名 .txt 文件，第一行标题，第二行标签(空格分隔，带不带#都行)
  例如: video.mp4 + video.txt
        标题内容
        #标签1 #标签2

定时发布说明:
- 如果不想定时发布，传 publish_date=0
"""
import asyncio
from pathlib import Path

from conf import BASE_DIR
from uploader.bilibili_web_uploader.main import bilibili_setup, BilibiliWebVideo
from utils.files_times import generate_schedule_time_next_day, get_title_and_hashtags


def get_video_files():
    """获取视频目录下的所有视频文件"""
    videos_dir = Path(BASE_DIR) / "videos"
    if not videos_dir.exists():
        return []

    video_extensions = {'.mp4', '.flv', '.avi', '.wmv', '.mov', '.webm', '.mpeg4', '.ts', '.mpg'}
    files = []
    for ext in video_extensions:
        files.extend(videos_dir.glob(f"*{ext}"))
        files.extend(videos_dir.glob(f"*{ext.upper()}"))
    return sorted(files)


def get_video_title(file_path: Path):
    """获取视频标题"""
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


async def login_account(account_file):
    """登录并保存cookie"""
    cookie_file = Path(account_file)
    cookie_file.parent.mkdir(parents=True, exist_ok=True)

    is_valid = await bilibili_setup(str(cookie_file), handle=True)
    if is_valid:
        print(f"登录成功，cookie已保存到: {cookie_file}")
    return is_valid


async def upload_single_video(file_path: Path, account_file: str, title: str = None,
                              tags: list = None, category: str = "vlog", copyright: int = 1,
                              schedule_time=None):
    """上传单个视频"""
    if title is None:
        title, file_tags = get_video_title(file_path)
        tags = tags or file_tags

    print(f"\n开始上传: {file_path.name}")
    print(f"  标题: {title}")
    print(f"  标签: {tags}")

    app = BilibiliWebVideo(
        title=title,
        file_path=str(file_path),
        tags=tags,
        publish_date=schedule_time or 0,
        account_file=account_file,
        category=category,
        copyright=copyright,
    )
    await app.main()


async def batch_upload(account_file: str, schedule_time=None):
    """批量上传 videos 目录下的所有视频"""
    files = get_video_files()
    if not files:
        print("未找到视频文件，请将视频放到 videos 目录")
        return

    print(f"找到 {len(files)} 个视频文件")

    for file_path in files:
        await upload_single_video(file_path, account_file, schedule_time=schedule_time)


async def main():
    import argparse

    parser = argparse.ArgumentParser(description='B站网页投稿工具')
    parser.add_argument('--login', action='store_true', help='重新登录')
    parser.add_argument('--file', type=str, help='指定视频文件路径')
    parser.add_argument('--title', type=str, help='视频标题')
    parser.add_argument('--tags', type=str, help='标签，逗号分隔')
    parser.add_argument('--category', type=str, default='vlog', help='分区，如 vlog, game 等')
    parser.add_argument('--copyright', type=int, default=1, help='1=自制, 2=转载')
    parser.add_argument('--account', type=str, default='cookies/bilibili_web_uploader/account.json',
                        help='cookie保存路径')
    args = parser.parse_args()

    account_file = str(Path(BASE_DIR) / args.account)

    if args.login:
        await login_account(account_file)
        return

    if not Path(account_file).exists():
        print("Cookie不存在，正在打开浏览器登录...")
        await login_account(account_file)

    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"视频文件不存在: {file_path}")
            return
        tags = args.tags.split(',') if args.tags else None
        await upload_single_video(file_path, account_file, args.title, tags, args.category, args.copyright)
    else:
        await batch_upload(account_file)


if __name__ == '__main__':
    asyncio.run(main())
