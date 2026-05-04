import re
from dataclasses import dataclass
from typing import Any, Iterable

from services.ai_client import extract_json_object, post_ai_json, finalize_ai_log_ok
from services.ai_config import (
    DEFAULT_TTS_SEGMENT_PROMPT,
    get_active_ai_model,
    load_ai_config,
)
from services.terms_store import load_terms


DEFAULT_SEGMENT_MODE = "ai"
DEFAULT_SEGMENT_MAX_CHARS = 140
DEFAULT_SEGMENT_MAX_SECONDS = 14.0
DEFAULT_SEGMENT_MAX_GAP = 0.8
DEFAULT_SEGMENT_MIN_SECONDS = 0.45
DEFAULT_SEGMENT_MIN_CHARS = 6

SEGMENT_SYSTEM_PROMPT = DEFAULT_TTS_SEGMENT_PROMPT

SHORT_PREFIXES = (
    "然后",
    "所以",
    "首先",
    "当然",
    "但是",
    "不过",
    "如果",
    "如果说",
    "而且",
    "并且",
    "那",
    "那种",
    "反正",
)


@dataclass
class TtsChunk:
    start: float
    end: float
    text: str
    source_ids: list[int]


def tts_chunks_to_json(chunks: list[TtsChunk]) -> list[dict[str, Any]]:
    return [
        {
            "start": float(chunk.start),
            "end": float(chunk.end),
            "text": str(chunk.text),
            "source_ids": [int(item) for item in chunk.source_ids],
        }
        for chunk in chunks
    ]


def json_to_tts_chunks(data: list[dict[str, Any]]) -> list[TtsChunk]:
    chunks: list[TtsChunk] = []
    for item in data:
        chunks.append(
            TtsChunk(
                start=float(item["start"]),
                end=float(item["end"]),
                text=str(item.get("text") or "").strip(),
                source_ids=[int(value) for value in (item.get("source_ids") or [])],
            )
        )
    return chunks


def _normalize_tts_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return text
    text = text.replace("skill站点", "skill 站点")
    text = text.replace("clawHub", "ClawHub")
    text = text.replace("minimax", "Minimax")
    text = text.replace("Openclaw", "OpenClaw")
    return text


def _make_chunk(captions: list[Any], text: str | None = None) -> TtsChunk:
    merged_text = text if text is not None else "".join(item.text for item in captions)
    return TtsChunk(
        start=float(captions[0].start),
        end=float(captions[-1].end),
        text=_normalize_tts_text(merged_text),
        source_ids=[int(item.id) for item in captions],
    )


def _merge_two_chunks(left: TtsChunk, right: TtsChunk) -> TtsChunk:
    merged_ids = list(dict.fromkeys([*left.source_ids, *right.source_ids]))
    merged_text = _normalize_tts_text(f"{left.text}{right.text}")
    return TtsChunk(
        start=min(float(left.start), float(right.start)),
        end=max(float(left.end), float(right.end)),
        text=merged_text,
        source_ids=merged_ids,
    )


def coalesce_short_tts_chunks(
    chunks: list[TtsChunk],
    min_seconds: float = DEFAULT_SEGMENT_MIN_SECONDS,
    min_chars: int = DEFAULT_SEGMENT_MIN_CHARS,
) -> list[TtsChunk]:
    if not chunks:
        return []

    merged = list(chunks)
    idx = 0
    while idx < len(merged):
        chunk = merged[idx]
        duration = float(chunk.end) - float(chunk.start)
        text_len = len((chunk.text or "").strip())
        if duration >= min_seconds and text_len >= min_chars:
            idx += 1
            continue

        if len(merged) == 1:
            break

        if idx == 0:
            merged[1] = _merge_two_chunks(chunk, merged[1])
            merged.pop(idx)
            continue

        if idx == len(merged) - 1:
            merged[idx - 1] = _merge_two_chunks(merged[idx - 1], chunk)
            merged.pop(idx)
            idx = max(0, idx - 1)
            continue

        prev_gap = abs(float(chunk.start) - float(merged[idx - 1].end))
        next_gap = abs(float(merged[idx + 1].start) - float(chunk.end))
        if prev_gap <= next_gap:
            merged[idx - 1] = _merge_two_chunks(merged[idx - 1], chunk)
            merged.pop(idx)
            idx = max(0, idx - 1)
        else:
            merged[idx + 1] = _merge_two_chunks(chunk, merged[idx + 1])
            merged.pop(idx)

    return merged


def build_rule_tts_chunks(
    captions: Iterable[Any],
    max_chars: int = DEFAULT_SEGMENT_MAX_CHARS,
    max_seconds: float = DEFAULT_SEGMENT_MAX_SECONDS,
    max_gap: float = DEFAULT_SEGMENT_MAX_GAP,
) -> list[TtsChunk]:
    items = list(captions)
    if not items:
        return []

    chunks: list[TtsChunk] = []
    current: list[Any] = [items[0]]

    def should_merge(current_items: list[Any], nxt: Any) -> bool:
        current_text = "".join(item.text for item in current_items)
        next_text = "".join(item.text for item in current_items + [nxt])
        next_duration = float(nxt.end) - float(current_items[0].start)
        gap = float(nxt.start) - float(current_items[-1].end)
        if gap > max_gap:
            return False
        if len(next_text) > max_chars or next_duration > max_seconds:
            return False
        if len(current_text) < 24:
            return True
        if len(str(nxt.text).strip()) <= 12:
            return True
        if any(str(nxt.text).strip().startswith(prefix) for prefix in SHORT_PREFIXES):
            return True
        if re.search(r"[，,、：:；;]$", current_text):
            return True
        return False

    for caption in items[1:]:
        if should_merge(current, caption):
            current.append(caption)
            continue
        chunks.append(_make_chunk(current))
        current = [caption]

    if current:
        chunks.append(_make_chunk(current))
    return chunks


def _request_ai_tts_segments(captions: list[Any]) -> list[dict]:
    ai_config = load_ai_config()
    active_model = get_active_ai_model(ai_config)
    if not active_model:
        raise ValueError("未启用 AI 模型")
    if not active_model.get("base_url") or not active_model.get("model"):
        raise ValueError("AI 模型配置不完整，请填写 Base URL 和模型名")

    terms = load_terms()
    caption_text = "\n".join(
        f"【{int(c.id)}】{float(c.start):.3f}-{float(c.end):.3f} {c.text}" for c in captions
    )
    terms_text = (
        "\n".join(f"- {src} -> {dst}" for src, dst in terms.items())
        if terms
        else "（当前没有已知术语词库，可根据上下文自行判断）"
    )
    user_content = (
        "下面是按时间顺序排列的字幕。请返回适合 TTS 的合并分段结果。\n\n"
        "已知术语/替换词库（如果字幕里有明显误识别，请优先参考这里进行高置信修正，但只修改 TTS 文本，不修改显示字幕）：\n"
        f"{terms_text}\n\n"
        "字幕原文：\n"
        f"{caption_text}"
    )
    payload = {
        "model": active_model["model"],
        "messages": [
            {"role": "system", "content": ai_config.get("tts_segment_prompt") or SEGMENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    data, content, ctx = post_ai_json(
        log_type="tts_segmentation",
        active_model=active_model,
        payload=payload,
        request_meta={"captions_count": len(captions)},
    )

    parsed = extract_json_object(content)
    segments = parsed if isinstance(parsed, list) else parsed.get("segments", [])
    finalize_ai_log_ok(ctx, response_preview=content, extra={"normalized_segments": segments})
    if not isinstance(segments, list):
        raise ValueError("AI 分段返回格式错误")
    return segments


def build_ai_tts_chunks(
    captions: Iterable[Any],
    max_chars: int = DEFAULT_SEGMENT_MAX_CHARS,
    max_seconds: float = DEFAULT_SEGMENT_MAX_SECONDS,
) -> list[TtsChunk]:
    items = list(captions)
    if not items:
        return []

    raw_segments = _request_ai_tts_segments(items)
    captions_by_id = {int(item.id): item for item in items}
    used_ids: set[int] = set()
    chunks: list[TtsChunk] = []

    for segment in raw_segments:
        if not isinstance(segment, dict):
            continue
        caption_ids = segment.get("caption_ids") or segment.get("ids") or []
        try:
            normalized_ids = [int(x) for x in caption_ids]
        except Exception:
            continue
        if not normalized_ids:
            continue
        segment_captions = [captions_by_id[x] for x in normalized_ids if x in captions_by_id]
        if not segment_captions:
            continue
        if [int(x.id) for x in segment_captions] != normalized_ids:
            continue
        if any(int(x.id) in used_ids for x in segment_captions):
            continue
        segment_text = str(segment.get("text") or "").strip()
        if not segment_text:
            segment_text = "".join(item.text for item in segment_captions)
        duration = float(segment_captions[-1].end) - float(segment_captions[0].start)
        if len(segment_text) > max_chars or duration > max_seconds:
            chunks.extend(build_rule_tts_chunks(segment_captions, max_chars=max_chars, max_seconds=max_seconds))
        else:
            chunks.append(_make_chunk(segment_captions, text=segment_text))
        used_ids.update(int(x.id) for x in segment_captions)

    remaining = [item for item in items if int(item.id) not in used_ids]
    if remaining:
        chunks.extend(build_rule_tts_chunks(remaining, max_chars=max_chars, max_seconds=max_seconds))

    chunks.sort(key=lambda item: item.start)
    return chunks


def build_tts_chunks(
    captions: Iterable[Any],
    segment_mode: str = DEFAULT_SEGMENT_MODE,
    max_chars: int = DEFAULT_SEGMENT_MAX_CHARS,
    max_seconds: float = DEFAULT_SEGMENT_MAX_SECONDS,
    max_gap: float = DEFAULT_SEGMENT_MAX_GAP,
) -> tuple[list[TtsChunk], str]:
    items = list(captions)
    if not items:
        return [], "empty"

    mode = (segment_mode or DEFAULT_SEGMENT_MODE).strip()
    if mode == "rule":
        return coalesce_short_tts_chunks(
            build_rule_tts_chunks(items, max_chars=max_chars, max_seconds=max_seconds, max_gap=max_gap)
        ), "rule"

    try:
        return coalesce_short_tts_chunks(
            build_ai_tts_chunks(items, max_chars=max_chars, max_seconds=max_seconds)
        ), "ai"
    except Exception as exc:
        print(f"AI tts segmentation failed, fallback to rules: {exc}")
        return coalesce_short_tts_chunks(
            build_rule_tts_chunks(items, max_chars=max_chars, max_seconds=max_seconds, max_gap=max_gap)
        ), "rule_fallback"
