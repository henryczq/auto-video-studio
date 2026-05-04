import time
from typing import List

from services.ai_client import (
    extract_json_object,
    finalize_ai_log_ok,
    post_ai_json,
)
from services.ai_config import get_active_ai_model, load_ai_config
from services.ai_logging import write_ai_log
from services.captions import Caption
from services.terms_store import load_terms


VOICEOVER_REWRITE_PROMPT = """你是一个短视频讲解口播优化助手。

你的任务：
1. 针对每条字幕，生成 1 到 3 个更适合短视频口播的候选说法。
2. 风格要更像真人讲解：更顺口、更有节奏、略带提醒感和轻微惊讶感。
3. 不能改变该字幕对应的操作含义，不能破坏和录屏画面的同步。
4. 结果必须尽量贴合原字幕时长，避免明显变长。

优先风格：
1. 像教程讲解，不像广告。
2. 允许轻微强调、轻微惊讶、轻微起伏，但不要浮夸。
3. 优先生成“自然口播能读出来抑扬顿挫”的句子。
4. 能自然加入一点讲解提示词，但必须克制。

可少量使用的风格词：
- 注意看
- 这里很关键
- 你看
- 直接
- 马上
- 这一步
- 重点来了
- 其实
- 原来这里
- 这样一来

禁止事项：
1. 不要改变步骤顺序。
2. 不要新增画面里没出现的动作、结果、数据、评价。
3. 不要写成夸张营销腔。
4. 禁止使用“震惊、绝了、太牛了、颠覆认知、炸裂、离谱到不行”这类过火词。
5. 不要为了惊讶感硬加语气词，尤其不要每句都加。

长度与同步要求：
1. 必须按字幕逐条返回，caption_id 使用输入编号。
2. 每条最多返回 3 个候选，按推荐程度排序。
3. 候选长度尽量接近原文，原则上不要超过原文长度的 1.3 倍。
4. 时长短的字幕更保守，只做轻微润色。
5. 如果原句已经自然，可以返回与原文很接近的版本。
6. 候选要便于 TTS 读出停顿、强调和轻微语气变化。

对候选的具体要求：
1. 候选1：最稳妥，最适合直接替换。
2. 候选2：比候选1更口语化一点，带一点讲解感。
3. 候选3：在不跑偏的前提下，允许加入轻微惊讶/强调感。

输出必须是 JSON，不要输出 Markdown，不要附加解释。

输出格式：
{
  "items": [
    {
      "caption_id": 1,
      "candidates": ["候选1", "候选2"],
      "reason": "简短说明"
    }
  ]
}
"""


def _char_limit_for_caption(caption: Caption) -> int:
    duration = max(0.2, float(caption.end) - float(caption.start))
    duration_limit = int(duration * 5.6)
    original_limit = int(max(6, len(caption.text) * 1.3))
    return max(6, min(max(duration_limit, len(caption.text)), original_limit))


def _normalize_candidates(caption: Caption, raw_candidates: list[str]) -> list[str]:
    normalized: list[str] = []
    limit = _char_limit_for_caption(caption)
    for candidate in raw_candidates:
        text = str(candidate or "").strip()
        if not text:
            continue
        text = " ".join(text.split())
        if len(text) > limit:
            continue
        if text not in normalized:
            normalized.append(text)
        if len(normalized) >= 3:
            break
    if not normalized:
        normalized.append(caption.text)
    return normalized


def generate_voiceover_suggestions(captions: List[Caption]) -> List[dict]:
    if not captions:
        return []

    ai_config = load_ai_config()
    active_model = get_active_ai_model(ai_config)
    if not active_model:
        return []
    if not active_model.get("base_url") or not active_model.get("model"):
        raise ValueError("AI 模型配置不完整，请填写 Base URL 和模型名")

    terms = load_terms()
    terms_text = "\n".join(f"- {src} -> {dst}" for src, dst in terms.items()) if terms else "（无）"
    captions_text = "\n".join(
        f"【{caption.id}】{caption.start:.3f}-{caption.end:.3f} | 原文：{caption.text} | 长度上限：{_char_limit_for_caption(caption)}"
        for caption in captions
    )
    payload = {
        "model": active_model["model"],
        "messages": [
            {"role": "system", "content": VOICEOVER_REWRITE_PROMPT},
            {
                "role": "user",
                "content": (
                    "请基于下面的字幕生成逐条口播优化候选。\n\n"
                    "已知术语词库：\n"
                    f"{terms_text}\n\n"
                    "字幕列表：\n"
                    f"{captions_text}"
                ),
            },
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }

    _, content, ctx = post_ai_json(
        log_type="voiceover_suggestions",
        active_model=active_model,
        payload=payload,
        request_meta={"captions_count": len(captions)},
        allow_response_format_retry=True,
    )

    try:
        parsed = extract_json_object(content)
    except Exception as exc:
        ctx["log"].update(
            {
                "status": "error",
                "duration_ms": int((time.time() - ctx["started_at"]) * 1000),
                "error": f"AI 返回解析失败: {exc}",
                "response": ctx.get("wire_data"),
                "raw_response": ctx.get("raw_response"),
            }
        )
        write_ai_log(ctx["log"])
        raise

    raw_items = parsed if isinstance(parsed, list) else parsed.get("items", [])
    if not isinstance(raw_items, list):
        finalize_ai_log_ok(
            ctx,
            response_preview=content,
            extra={"normalized_items": []},
        )
        return []

    captions_by_id = {caption.id: caption for caption in captions}
    normalized: list[dict] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        try:
            caption_id = int(item.get("caption_id"))
        except (TypeError, ValueError):
            continue
        caption = captions_by_id.get(caption_id)
        if not caption:
            continue
        candidates = item.get("candidates") or []
        if isinstance(candidates, str):
            candidates = [candidates]
        normalized_candidates = _normalize_candidates(caption, candidates)
        normalized.append(
            {
                "caption_id": caption.id,
                "original": caption.text,
                "start": float(caption.start),
                "end": float(caption.end),
                "char_limit": _char_limit_for_caption(caption),
                "candidates": normalized_candidates,
                "reason": str(item.get("reason") or "").strip(),
            }
        )

    if not normalized:
        normalized = [
            {
                "caption_id": caption.id,
                "original": caption.text,
                "start": float(caption.start),
                "end": float(caption.end),
                "char_limit": _char_limit_for_caption(caption),
                "candidates": [caption.text],
                "reason": "",
            }
            for caption in captions
        ]

    finalize_ai_log_ok(
        ctx,
        response_preview=content,
        extra={"normalized_items": normalized[:100]},
    )
    return normalized
