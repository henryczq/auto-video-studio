#!/usr/bin/env python3
"""Bridge webapp job outputs to social-auto-upload uploaders that lack CLI support."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
SOCIAL_AUTO_UPLOAD_DIR = ROOT_DIR / "publish" / "social-auto-upload"
if str(SOCIAL_AUTO_UPLOAD_DIR) not in sys.path:
    sys.path.insert(0, str(SOCIAL_AUTO_UPLOAD_DIR))
BILIBILI_WEB_UPLOAD_DIR = ROOT_DIR / "publish" / "bilibili-web-upload"


VIDEO_TYPE_MAP = {
    "processed": "processed_video",
    "final_subtitles_video": "final_subtitles_video",
    "final_replace_audio_subtitled": "final_replace_audio",
}

DEFAULT_ACCOUNT_FILES = {
    "tencent": SOCIAL_AUTO_UPLOAD_DIR / "cookies" / "tencent_uploader" / "account.json",
    "baijiahao": SOCIAL_AUTO_UPLOAD_DIR / "cookies" / "baijiahao_uploader" / "account.json",
    "tiktok": SOCIAL_AUTO_UPLOAD_DIR / "cookies" / "tk_uploader" / "account.json",
    "bilibili": BILIBILI_WEB_UPLOAD_DIR / "cookies" / "bilibili_web_uploader" / "account.json",
}

UPLOADER_MODULES: dict[str, object] = {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Use webapp outputs with 视频号 / 百家号 / TikTok / B站 web uploaders."
    )
    parser.add_argument(
        "--platform",
        required=True,
        choices=sorted(DEFAULT_ACCOUNT_FILES.keys()),
        help="目标平台: tencent / baijiahao / tiktok / bilibili",
    )
    parser.add_argument("--job-id", help="webapp 任务 ID，例如 caf36f68")
    parser.add_argument(
        "--video-type",
        choices=sorted(VIDEO_TYPE_MAP.keys()),
        default="final_subtitles_video",
        help="从 webapp 任务里选择哪个视频产物",
    )
    parser.add_argument("--video-path", help="直接指定视频文件，优先级高于 --job-id/--video-type")
    parser.add_argument("--title", help="发布标题；不填则优先读 job 草稿，再退回文件名")
    parser.add_argument(
        "--tags",
        default="",
        help="标签，逗号或空格分隔。视频号/TikTok 使用，百家号当前上传器基本忽略。",
    )
    parser.add_argument("--desc", default="", help="预留字段，当前这 3 个上传器不会直接使用")
    parser.add_argument(
        "--schedule",
        default="",
        help="定时发布时间，格式如 2026-04-13T16:00 或 2026-04-13 16:00；留空则立即发布",
    )
    parser.add_argument("--thumbnail", help="封面图路径；视频号 / TikTok / B站网页投稿支持传入")
    parser.add_argument("--account-file", help="cookie 文件路径")
    parser.add_argument(
        "--check-cookie",
        action="store_true",
        help="只校验 cookie 是否可用，不执行发布。",
    )
    parser.add_argument(
        "--setup-cookie",
        action="store_true",
        help="只做 cookie 登录/刷新。适合首次扫码或 cookie 失效时运行。",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="默认有界面运行；传入后改为无头模式。",
    )
    parser.add_argument("--chrome-path", help="可选，自定义 Chrome/Chromium 可执行文件")
    parser.add_argument(
        "--category",
        default="",
        help="视频号或 B站分类，视频号传中文名，B站可传 vlog 等页面分区文本",
    )
    parser.add_argument(
        "--draft",
        action="store_true",
        help="仅视频号支持，保存草稿而不是直接发表。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅 B站网页投稿支持：上传并填写表单，但不点击立即投稿。",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="预览模式：上传并填写表单，停在发布确认页面，等待用户手动点击发布。",
    )
    return parser.parse_args()


def resolve_job_dir(job_id: str) -> Path:
    job_dir = ROOT_DIR / "videos" / "web_jobs" / job_id
    if not job_dir.exists():
        raise FileNotFoundError(f"任务目录不存在: {job_dir}")
    return job_dir


def load_job_json(job_dir: Path) -> dict:
    job_json = job_dir / "job.json"
    if not job_json.exists():
        raise FileNotFoundError(f"缺少任务描述文件: {job_json}")
    return json.loads(job_json.read_text(encoding="utf-8"))


def resolve_job_output(job: dict, job_dir: Path, video_type: str) -> Path:
    field = VIDEO_TYPE_MAP[video_type]
    raw_value = job.get(field)
    if not raw_value:
        raise FileNotFoundError(f"任务当前没有可用产物: {video_type}")
    path = Path(raw_value)
    if not path.is_absolute():
        path = job_dir / path
    if not path.exists():
        raise FileNotFoundError(f"视频文件不存在: {path}")
    return path.resolve()


def load_publish_draft(job_id: str) -> dict:
    drafts_path = ROOT_DIR / "data" / "publish_drafts.json"
    if not drafts_path.exists():
        return {}
    try:
        data = json.loads(drafts_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    draft = data.get(job_id)
    return draft if isinstance(draft, dict) else {}


def resolve_title(args: argparse.Namespace, video_path: Path) -> str:
    if args.title:
        return args.title.strip()
    if args.job_id:
        draft = load_publish_draft(args.job_id)
        title = str(draft.get("title", "")).strip()
        if title:
            return title
    return video_path.stem[:30]


def parse_tags(raw: str) -> list[str]:
    normalized = raw.replace("，", ",").replace("#", "")
    parts: list[str] = []
    if "," in normalized:
        parts = [piece.strip() for piece in normalized.split(",")]
    else:
        parts = [piece.strip() for piece in normalized.split()]
    seen: list[str] = []
    for item in parts:
        if item and item not in seen:
            seen.append(item)
    return seen


def parse_schedule(raw: str) -> datetime | int:
    value = raw.strip()
    if not value:
        return 0
    normalized = value.replace("T", " ")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            f"无法识别定时时间: {raw}；请使用 YYYY-MM-DDTHH:MM 或 YYYY-MM-DD HH:MM"
        ) from exc


def resolve_account_file(args: argparse.Namespace) -> Path:
    path = Path(args.account_file).expanduser() if args.account_file else DEFAULT_ACCOUNT_FILES[args.platform]
    return path.resolve()


def resolve_thumbnail(args: argparse.Namespace, job_dir: Path | None) -> Path | None:
    if not args.thumbnail:
        return None
    path = Path(args.thumbnail).expanduser()
    if not path.is_absolute() and job_dir is not None:
        path = job_dir / path
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(f"封面图不存在: {path}")
    return path


def get_uploader_module(platform: str):
    if platform in UPLOADER_MODULES:
        return UPLOADER_MODULES[platform]

    module_name = {
        "tencent": "uploader.tencent_uploader.main",
        "baijiahao": "uploader.baijiahao_uploader.main",
        "tiktok": "uploader.tk_uploader.main_chrome",
        "bilibili": "src.web_uploader",
    }[platform]

    try:
        if platform == "bilibili" and str(BILIBILI_WEB_UPLOAD_DIR) not in sys.path:
            sys.path.insert(0, str(BILIBILI_WEB_UPLOAD_DIR))
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == "playwright":
            raise RuntimeError(
                "当前 social-auto-upload 环境缺少 playwright。"
                "这 3 个桥接平台依赖 playwright，不走 patchright。"
            ) from exc
        raise

    UPLOADER_MODULES[platform] = module
    return module


def configure_runtime(args: argparse.Namespace) -> None:
    module = get_uploader_module(args.platform)
    if args.platform == "bilibili":
        module.HEADLESS = args.headless
    else:
        module.LOCAL_CHROME_HEADLESS = args.headless
    if args.chrome_path:
        module.LOCAL_CHROME_PATH = args.chrome_path


async def setup_cookie(platform: str, account_file: Path) -> bool:
    account_file.parent.mkdir(parents=True, exist_ok=True)
    module = get_uploader_module(platform)
    if platform == "tencent":
        return await module.weixin_setup(str(account_file), handle=True)
    if platform == "baijiahao":
        return await module.baijiahao_setup(str(account_file), handle=True)
    if platform == "tiktok":
        return await module.tiktok_setup(str(account_file), handle=True)
    if platform == "bilibili":
        return await module.bilibili_setup(str(account_file), handle=True)
    raise ValueError(f"不支持的平台: {platform}")


async def ensure_cookie_valid(platform: str, account_file: Path) -> bool:
    module = get_uploader_module(platform)
    if platform == "tencent":
        return await module.weixin_setup(str(account_file), handle=False)
    if platform == "baijiahao":
        return await module.baijiahao_setup(str(account_file), handle=False)
    if platform == "tiktok":
        return await module.tiktok_setup(str(account_file), handle=False)
    if platform == "bilibili":
        return await module.bilibili_setup(str(account_file), handle=False)
    raise ValueError(f"不支持的平台: {platform}")


async def publish_video(
    args: argparse.Namespace,
    *,
    video_path: Path,
    title: str,
    tags: list[str],
    publish_date: datetime | int,
    account_file: Path,
    thumbnail_path: Path | None,
) -> None:
    module = get_uploader_module(args.platform)
    if args.platform == "tencent":
        app = module.TencentVideo(
            title=title,
            file_path=str(video_path),
            tags=tags,
            publish_date=publish_date,
            account_file=str(account_file),
            category=args.category or None,
            is_draft=args.draft,
            is_preview=args.preview,
            thumbnail_path=str(thumbnail_path) if thumbnail_path else None,
        )
        await app.main()
        return

    if args.platform == "baijiahao":
        app = module.BaiJiaHaoVideo(
            title=title,
            file_path=str(video_path),
            tags=tags,
            publish_date=publish_date,
            account_file=str(account_file),
        )
        await app.main()
        return

    if args.platform == "tiktok":
        app = module.TiktokVideo(
            title=title,
            file_path=str(video_path),
            tags=tags,
            publish_date=publish_date,
            account_file=str(account_file),
            thumbnail_path=str(thumbnail_path) if thumbnail_path else None,
        )
        await app.main()
        return

    if args.platform == "bilibili":
        app = module.BilibiliWebVideo(
            title=title,
            file_path=str(video_path),
            tags=tags,
            publish_date=publish_date if publish_date != 0 else None,
            account_file=str(account_file),
            category=args.category or "vlog",
            copyright=1,
            description=args.desc or title,
            thumbnail_path=str(thumbnail_path) if thumbnail_path else None,
            headless=args.headless,
            local_chrome_path=args.chrome_path or None,
            dry_run=args.dry_run or args.preview,
        )
        result = await app.run()
        if not result.get("success"):
            raise RuntimeError(result.get("message") or "B站网页投稿失败")
        return

    raise ValueError(f"不支持的平台: {args.platform}")


async def async_main() -> int:
    args = parse_args()
    account_file = resolve_account_file(args)
    configure_runtime(args)
    if args.check_cookie:
        cookie_valid = await ensure_cookie_valid(args.platform, account_file)
        if cookie_valid:
            print(f"[bridge] cookie valid: {account_file}")
            return 0
        print(f"[bridge] cookie invalid: {account_file}", file=sys.stderr)
        return 1

    if args.setup_cookie:
        print("[bridge] 即将启动网页登录，请在浏览器中完成登录；完成后需要在 Playwright Inspector 中 Resume。")
        await setup_cookie(args.platform, account_file)
        print(f"[bridge] cookie 已处理: {account_file}")
        return 0

    if not args.video_path and not args.job_id:
        raise SystemExit("发布模式下必须提供 --video-path 或 --job-id")

    job_dir: Path | None = None
    if args.video_path:
        video_path = Path(args.video_path).expanduser().resolve()
        if not video_path.exists():
            raise FileNotFoundError(f"视频文件不存在: {video_path}")
    else:
        job_dir = resolve_job_dir(args.job_id)
        job = load_job_json(job_dir)
        video_path = resolve_job_output(job, job_dir, args.video_type)

    thumbnail_path = resolve_thumbnail(args, job_dir)
    title = resolve_title(args, video_path)
    tags = parse_tags(args.tags)
    publish_date = parse_schedule(args.schedule)

    cookie_valid = await ensure_cookie_valid(args.platform, account_file)
    if not cookie_valid:
        raise RuntimeError(
            "cookie 不存在或已失效。先执行:\n"
            f"  python tools/bridge_publish.py --platform {args.platform} --setup-cookie"
        )

    print(f"[bridge] platform: {args.platform}")
    print(f"[bridge] account_file: {account_file}")
    print(f"[bridge] video_path: {video_path}")
    print(f"[bridge] title: {title}")
    print(f"[bridge] tags: {tags}")
    if thumbnail_path:
        print(f"[bridge] thumbnail: {thumbnail_path}")
    if publish_date != 0:
        print(f"[bridge] schedule: {publish_date.isoformat(sep=' ', timespec='minutes')}")
    if args.platform in {"tencent", "bilibili"} and args.category:
        print(f"[bridge] category: {args.category}")
    if args.platform == "tencent" and (args.draft or args.preview):
        print("[bridge] mode: draft")
    if args.platform == "bilibili" and args.dry_run:
        print("[bridge] mode: dry-run")

    await publish_video(
        args,
        video_path=video_path,
        title=title,
        tags=tags,
        publish_date=publish_date,
        account_file=account_file,
        thumbnail_path=thumbnail_path,
    )
    print("[bridge] publish finished")
    return 0


def main() -> int:
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        print("[bridge] interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"[bridge] error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
