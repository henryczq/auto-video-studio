import json
import time
from typing import List

from services.ai_client import (
    extract_json_object,
    finalize_ai_log_ok,
    post_ai_json,
)
from services.ai_config import DEFAULT_AI_PROMPT, get_active_ai_model
from services.ai_logging import write_ai_log
from services.captions import Caption


def generate_ai_suggestions(
    captions: List[Caption], terms: dict, config: dict
) -> List[dict]:
    active_model = get_active_ai_model(config)
    if not active_model:
        return []
    if not active_model.get("base_url") or not active_model.get("model"):
        raise ValueError("AI 模型配置不完整，请填写 Base URL 和模型名")

    caption_text = "\n".join(f"【{caption.id}】{caption.text}" for caption in captions)
    terms_text = json.dumps(terms, ensure_ascii=False, indent=2)
    user_content = (
        "下面是当前替换词库，可作为已知术语参考：\n"
        f"{terms_text}\n\n"
        "下面是字幕文本：\n"
        f"{caption_text}"
    )
    api_type = active_model.get("api_type", "compatible")
    if api_type == "anthropic-messages":
        payload = {
            "model": active_model["model"],
            "system": config.get("prompt") or DEFAULT_AI_PROMPT,
            "messages": [
                {"role": "user", "content": user_content},
            ],
            "max_tokens": 4096,
        }
    else:
        payload = {
            "model": active_model["model"],
            "messages": [
                {"role": "system", "content": config.get("prompt") or DEFAULT_AI_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.1,
        }
        if api_type == "compatible":
            payload["response_format"] = {"type": "json_object"}

    _, content, ctx = post_ai_json(
        log_type="suggestions",
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

    raw_suggestions = (
        parsed if isinstance(parsed, list) else parsed.get("suggestions", [])
    )
    if not isinstance(raw_suggestions, list):
        finalize_ai_log_ok(
            ctx,
            response_preview=content,
            extra={"normalized_suggestions": []},
        )
        return []

    captions_by_id = {caption.id: caption for caption in captions}
    normalized = []
    for item in raw_suggestions:
        if not isinstance(item, dict):
            continue
        suspect = str(item.get("suspect") or "").strip()
        candidates = item.get("candidates") or item.get("candidate") or []
        if isinstance(candidates, str):
            candidates = [candidates]
        candidates = [
            str(candidate).strip()
            for candidate in candidates
            if str(candidate).strip()
        ]
        if not suspect or not candidates:
            continue

        caption_id = item.get("caption_id")
        try:
            caption_id = int(caption_id)
        except (TypeError, ValueError):
            caption_id = None
        caption = captions_by_id.get(caption_id) if caption_id else None
        if caption is None or suspect not in caption.text:
            caption = next((caption for caption in captions if suspect in caption.text), None)
        if caption is None:
            continue

        normalized.append(
            {
                "caption_id": caption.id,
                "original": caption.text,
                "src": suspect,
                "dst": candidates[0] if candidates else "",
                "candidates": candidates[:3],
                "confidence": item.get("confidence", 0.85),
                "reason": str(item.get("reason") or "AI 建议").strip(),
                "accepted": False,
            }
        )

    result = normalized[:20]
    finalize_ai_log_ok(
        ctx,
        response_preview=content,
        extra={"normalized_suggestions": result},
    )
    return result
