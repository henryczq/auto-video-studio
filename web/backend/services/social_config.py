import json
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.parent.parent
SETTINGS_FILE = ROOT_DIR / "data" / "social_upload_settings.json"
PLATFORMS_FILE = ROOT_DIR / "config" / "social_platforms.json"


def load_platforms_config() -> dict:
    if not PLATFORMS_FILE.exists():
        return _default_platforms()
    return json.loads(PLATFORMS_FILE.read_text(encoding="utf-8"))


def _default_platforms() -> dict:
    return {
        "platforms": {
            "douyin": {
                "name": "抖音",
                "icon": "🎵",
                "cli_name": "douyin",
                "support_login": True,
                "support_video": True,
                "support_note": True,
                "support_schedule": True,
                "support_draft": False,
                "support_cli": True,
                "support_skill": True,
                "support_web_bridge": False,
                "need_tid": False,
                "need_desc": True,
                "need_tags": True,
                "need_schedule": True,
                "login_mode": "headed",
                "creator_url": "https://creator.douyin.com",
                "description": "抖音短视频平台",
            },
            "kuaishou": {
                "name": "快手",
                "icon": "🦊",
                "cli_name": "kuaishou",
                "support_login": True,
                "support_video": True,
                "support_note": True,
                "support_schedule": True,
                "support_draft": False,
                "support_cli": True,
                "support_skill": True,
                "support_web_bridge": False,
                "need_tid": False,
                "need_desc": True,
                "need_tags": True,
                "need_schedule": True,
                "login_mode": "headed",
                "creator_url": "https://cp.kuaishou.com/article/publish/video",
                "description": "快手短视频平台",
            },
            "xiaohongshu": {
                "name": "小红书",
                "icon": "📕",
                "cli_name": "xiaohongshu",
                "support_login": True,
                "support_video": True,
                "support_note": True,
                "support_schedule": True,
                "support_draft": True,
                "support_cli": True,
                "support_skill": True,
                "support_web_bridge": False,
                "need_tid": False,
                "need_desc": True,
                "need_tags": True,
                "need_schedule": True,
                "login_mode": "headed",
                "creator_url": "https://creator.xiaohongshu.com",
                "description": "小红书图文/视频平台",
            },
            "bilibili": {
                "name": "Bilibili",
                "icon": "📺",
                "cli_name": "bilibili",
                "support_login": True,
                "support_video": True,
                "support_note": False,
                "support_schedule": True,
                "support_draft": False,
                "support_cli": True,
                "support_skill": True,
                "support_web_bridge": False,
                "need_tid": True,
                "need_desc": True,
                "need_tags": True,
                "need_schedule": True,
                "login_mode": "terminal",
                "creator_url": "https://member.bilibili.com",
                "description": "Bilibili 视频平台，需要分区 tid",
            },
            "tencent": {
                "name": "视频号",
                "icon": "📱",
                "cli_name": "tencent",
                "support_login": True,
                "support_video": True,
                "support_note": False,
                "support_schedule": True,
                "support_draft": False,
                "support_cli": False,
                "support_skill": False,
                "support_web_bridge": True,
                "need_tid": False,
                "need_desc": True,
                "need_tags": False,
                "need_schedule": True,
                "login_mode": "headed",
                "creator_url": "https://channels.weixin.qq.com/platform/post/create",
                "description": "视频号，对应 tencent_uploader",
            },
            "baijiahao": {
                "name": "百家号",
                "icon": "📰",
                "cli_name": "baijiahao",
                "support_login": True,
                "support_video": True,
                "support_note": False,
                "support_schedule": True,
                "support_draft": False,
                "support_cli": False,
                "support_skill": False,
                "support_web_bridge": True,
                "need_tid": False,
                "need_desc": True,
                "need_tags": False,
                "need_schedule": True,
                "login_mode": "headed",
                "creator_url": "https://baijiahao.baidu.com",
                "description": "百度百家号",
            },
            "tiktok": {
                "name": "TikTok",
                "icon": "🎬",
                "cli_name": "tiktok",
                "support_login": True,
                "support_video": True,
                "support_note": False,
                "support_schedule": True,
                "support_draft": False,
                "support_cli": False,
                "support_skill": False,
                "support_web_bridge": True,
                "need_tid": False,
                "need_desc": True,
                "need_tags": True,
                "need_schedule": True,
                "login_mode": "headed",
                "creator_url": "https://www.tiktok.com/tiktokstudio/upload?lang=en",
                "description": "TikTok，当前示例走 Chrome 版实现",
            },
        },
        "default_categories": {
            "bilibili": [
                {"id": "174", "name": "生活"},
                {"id": "201", "name": "日常"},
                {"id": "249", "name": "生活>日常"},
                {"id": "20", "name": "动画"},
                {"id": "47", "name": "游戏"},
                {"id": "65", "name": "科技"},
                {"id": "36", "name": "音乐"},
                {"id": "5", "name": "娱乐"},
                {"id": "119", "name": "影视"},
                {"id": "234", "name": "美食"},
            ]
        },
    }


def get_platforms() -> list:
    config = load_platforms_config()
    return list(config.get("platforms", {}).keys())


def get_cli_platforms() -> list:
    config = load_platforms_config()
    return [
        platform_id
        for platform_id, info in config.get("platforms", {}).items()
        if info.get("support_cli", False)
    ]


def get_platform_info(platform_id: str) -> dict:
    config = load_platforms_config()
    return config.get("platforms", {}).get(platform_id, {})


def get_platforms_with_info() -> list:
    config = load_platforms_config()
    return [{"id": pid, **pinfo} for pid, pinfo in config.get("platforms", {}).items()]


def get_categories(platform_id: str) -> list:
    config = load_platforms_config()
    categories = config.get("default_categories", {}).get(platform_id, [])
    if not categories:
        if platform_id == "bilibili":
            return config.get("default_categories", {}).get("bilibili", [])
    return categories


def get_cli_name(platform_id: str) -> str:
    info = get_platform_info(platform_id)
    return info.get("cli_name", platform_id)


def get_creator_urls() -> dict:
    config = load_platforms_config()
    urls = {}
    for pid, pinfo in config.get("platforms", {}).items():
        url = pinfo.get("creator_url", "")
        if url:
            urls[pid] = {
                "name": pinfo.get("name", pid),
                "url": url,
                "icon": pinfo.get("icon", ""),
            }
    return urls


PLATFORMS = get_platforms()
CLI_PLATFORMS = get_cli_platforms()
BILIBILI_CATEGORIES = [(cat["id"], cat["name"]) for cat in get_categories("bilibili")]


def save_platforms_config(config: dict) -> dict:
    PLATFORMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PLATFORMS_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return config


def get_settings() -> dict:
    if not SETTINGS_FILE.exists():
        return {
            "sau_root": str(ROOT_DIR / "publish" / "social-auto-upload"),
            "sau_python": str(
                ROOT_DIR / "publish" / "social-auto-upload" / ".venv" / "bin" / "python"
            ),
            "sau_cli": "sau_cli.py",
            "bilibili_provider": "social-auto-upload",
        }
    settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    settings.setdefault("bilibili_provider", "social-auto-upload")
    legacy_aio_provider = "bilibili-" + "all-in-one"
    if settings.get("bilibili_provider") == legacy_aio_provider:
        settings["bilibili_provider"] = "bilibili-web-upload"
    return settings


def save_settings(settings: dict) -> dict:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return settings


def get_bilibili_provider() -> str:
    return get_settings().get("bilibili_provider", "social-auto-upload")


def get_sau_root() -> Path:
    return Path(get_settings()["sau_root"])


def get_sau_python() -> Path:
    return Path(get_settings()["sau_python"])


def get_sau_cli() -> Path:
    settings = get_settings()
    return Path(settings["sau_root"]) / settings["sau_cli"]
