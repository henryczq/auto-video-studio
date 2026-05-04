"""Store for publish settings including AI prompts for title/description/tags generation."""

import json
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).parent.parent.parent.parent
SETTINGS_FILE = ROOT_DIR / "config" / "publish_settings.json"

DEFAULT_SETTINGS = {
    "content_prompt": """你是一名短视频运营策划。请根据以下视频字幕内容，生成适合短视频平台发布的标题、简介和标签。

字幕内容：
{subtitles}

请输出 3 套不同风格的发布文案：
- tutorial: 教程型
- hook: 爆点型
- workplace: 职场效率型

整体要求：
1. 面向抖音、快手、小红书视频号这类短视频平台，不要写成产品说明书
2. 标题要口语化、像真人会发的视频标题，优先突出结果感、实用性、节省时间、自动化体验
3. 可以自然出现“飞书机器人”“OpenClaw”，但不要堆术语，不要生硬
4. 标题尽量控制在 26 字以内，避免过长
5. 简介控制在 2-4 句话，先讲这视频解决什么问题，再讲演示了什么，最后可轻微引导互动
6. 标签最多 5 个，优先场景词、结果词、平台熟词，避免空泛大词
7. 不要输出夸张违禁词，不要标题党过度，不要虚假承诺
8. “自动提醒待办”“省事”“效率提升”这类方向可以优先考虑

标题风格参考：
- 用飞书机器人自动提醒待办，太省事了
- 我把待办提醒交给飞书机器人了
- 用 OpenClaw 搭个飞书机器人，自动管理待办

请按以下 JSON 格式返回，不要 Markdown 代码块，不要额外解释：
{{
  "recommended_style": "workplace",
  "versions": {{
    "tutorial": {{
      "label": "教程型",
      "title": "标题",
      "description": "简介",
      "tags": ["标签1", "标签2", "标签3"]
    }},
    "hook": {{
      "label": "爆点型",
      "title": "标题",
      "description": "简介",
      "tags": ["标签1", "标签2", "标签3"]
    }},
    "workplace": {{
      "label": "职场效率型",
      "title": "标题",
      "description": "简介",
      "tags": ["标签1", "标签2", "标签3"]
    }}
  }}
}}
""",

    "title_prompt": "",
    "desc_prompt": "",
    "tags_prompt": "",
    "default_tags": [],
    "ai_model": None,
}


def _ensure_config_dir():
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_publish_settings() -> dict:
    """Load publish settings from file."""
    _ensure_config_dir()
    if not SETTINGS_FILE.exists():
        return DEFAULT_SETTINGS.copy()
    
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            settings = json.load(f)
        # Merge with defaults for any missing keys
        merged = DEFAULT_SETTINGS.copy()
        merged.update(settings)
        return merged
    except (json.JSONDecodeError, IOError):
        return DEFAULT_SETTINGS.copy()


def save_publish_settings(settings: dict) -> dict:
    """Save publish settings to file."""
    _ensure_config_dir()
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
    return settings
