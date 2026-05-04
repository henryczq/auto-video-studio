import json
import re
import uuid
from pathlib import Path
from typing import Optional


AI_CONFIG_FILE = Path(__file__).parent.parent.parent.parent / "data" / "ai_models.json"

DEFAULT_AI_PROMPT = """你是一个字幕错词校对助手。请根据整段字幕上下文，找出可能由语音识别导致的错词，尤其关注产品名、英文名、专有名词、人名和术语。

请只返回 JSON，不要返回 Markdown。格式如下：
{
  "suggestions": [
    {
      "caption_id": 1,
      "suspect": "字幕里的错误文本",
      "candidates": ["建议替换文本"],
      "reason": "简短原因"
    }
  ]
}

要求：
1. caption_id 必须使用字幕前的编号。
2. suspect 必须是原字幕里真实出现的连续文本。
3. candidates 给 1-3 个候选，最推荐的放第一个。
4. 没有把握就不要提建议。
5. 不要建议标点符号、语气词或无需修改的自然表达。"""

DEFAULT_TTS_SEGMENT_PROMPT = """你是一个中文口播 TTS 断句助手。

目标：
1. 保留原字幕作为显示字幕，不修改显示字幕内容。
2. 仅为 TTS 生成更自然的“合并分段”结果，让语音更连贯、更像正常人口播。
3. 在不改变原意的前提下，允许只对 TTS 文本纠正明显的语音识别错误，让配音文本更准确、更适合朗读。

要求：
1. 只在自然语气连续时合并相邻字幕，不要为了凑时长生硬拼接。
2. 单段尽量只表达一个完整小意图；信息密度过高时宁可拆开，也不要让一段太满。
3. 尽量避免把“然后、所以、首先、当然、但是、如果说、反正、最后”等连接句单独成段；如有需要，可并入前后更自然的语句。
4. 单段尽量控制在 4 到 14 秒；太短会碎，太长会让 TTS 一口气念不顺。
5. 可以为 TTS 文本补充自然标点、空格、英文大小写和术语格式，让语音停顿更自然。
6. 优先补充这些标点：逗号、句号、问号；不要乱加过多标点，不要让朗读过碎。
7. 英文名、品牌名、产品名、术语尽量规范，如 OpenClaw、ClawHub、Mix、Skyline、Agent、飞书 等；必要时可在中英文之间补空格。
8. 如果提供了“已知术语/替换词库”，请优先参考这些术语；当字幕里出现明显的 ASR 错误、近音词、专有名词误识别时，可在 TTS 文本中修正成更合理的说法。
9. 对明显错误的处理要保守，只修正把握较高的内容；没把握时保留原文，不要瞎猜。
10. 不要改写原意，不要凭空新增信息；如果原字幕明显有语病，只做最小必要润色，让它更适合念出来。
11. 避免输出纯粘连长句；生成的 text 应该是“能直接拿去配音”的版本。
12. 不要输出任何系统提示、英文模板前缀、控制语或与朗读无关的文本。
13. 输出必须是 JSON，不要输出 Markdown，不要附加解释。

格式：
{
  "segments": [
    {
      "caption_ids": [1, 2],
      "text": "适合 TTS 的自然文本"
    }
  ]
}
"""


def default_ai_config() -> dict:
    return {
        "active_id": "",
        "prompt": DEFAULT_AI_PROMPT,
        "tts_segment_prompt": DEFAULT_TTS_SEGMENT_PROMPT,
        "models": [],
    }


def load_ai_config() -> dict:
    if not AI_CONFIG_FILE.exists():
        return default_ai_config()
    config = json.loads(AI_CONFIG_FILE.read_text(encoding="utf-8"))
    defaults = default_ai_config()
    return {
        "active_id": config.get("active_id") or defaults["active_id"],
        "prompt": config.get("prompt") or defaults["prompt"],
        "tts_segment_prompt": config.get("tts_segment_prompt")
        or defaults["tts_segment_prompt"],
        "models": config.get("models") or [],
    }


def save_ai_config(config: dict) -> dict:
    normalized = {
        "active_id": config.get("active_id") or "",
        "prompt": config.get("prompt") or DEFAULT_AI_PROMPT,
        "tts_segment_prompt": config.get("tts_segment_prompt") or DEFAULT_TTS_SEGMENT_PROMPT,
        "models": [],
    }
    for model in config.get("models") or []:
        model_id = model.get("id") or str(uuid.uuid4())[:8]
        normalized["models"].append(
            {
                "id": model_id,
                "name": model.get("name") or model.get("model") or "AI 模型",
                "base_url": (model.get("base_url") or "").strip(),
                "api_key": model.get("api_key") or "",
                "model": (model.get("model") or "").strip(),
                "api_type": (model.get("api_type") or "compatible").strip(),
            }
        )
    if normalized["active_id"] and not any(
        item["id"] == normalized["active_id"] for item in normalized["models"]
    ):
        normalized["active_id"] = ""
    AI_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    AI_CONFIG_FILE.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return normalized


def get_active_ai_model(config: dict) -> Optional[dict]:
    active_id = config.get("active_id")
    models = config.get("models") or []
    for model in models:
        if model.get("id") == active_id:
            return model
    for model in models:
        if model.get("base_url") and model.get("model"):
            return model
    return None


def chat_completions_url(base_url: str) -> str:
    base_url = base_url.rstrip("/")
    if base_url.endswith("/chat/completions"):
        return base_url
    if re.search(r"/v\d+$", base_url):
        return f"{base_url}/chat/completions"
    return f"{base_url}/v1/chat/completions"


def build_api_url(base_url: str, api_type: str) -> str:
    base_url = base_url.rstrip("/")
    if api_type == "responses":
        if base_url.endswith("/responses"):
            return base_url
        if re.search(r"/v\d+$", base_url):
            return f"{base_url}/responses"
        return f"{base_url}/v1/responses"
    if api_type == "anthropic-messages":
        if base_url.endswith("/messages"):
            return base_url
        if base_url.endswith("/v1"):
            return f"{base_url}/messages"
        return f"{base_url}/v1/messages"
    return chat_completions_url(base_url)
