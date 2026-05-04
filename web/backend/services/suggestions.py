import re
from typing import List

from services.ai_config import get_active_ai_model, load_ai_config
from services.ai_suggestions import generate_ai_suggestions
from services.captions import Caption
from services.terms_store import add_term, load_terms, save_terms


def generate_suggestions(captions: List[Caption], terms: dict) -> List[dict]:
    if not captions:
        return []

    ai_config = load_ai_config()
    if get_active_ai_model(ai_config):
        try:
            return generate_ai_suggestions(captions, terms, ai_config)
        except Exception as exc:
            print(f"AI suggestions failed, fallback to rules: {exc}")

    suggestions = []
    existing_targets = set(terms.values())
    existing_sources = set(terms.keys())

    for caption in captions:
        text = caption.text

        for source, target in terms.items():
            if source in text and source != target:
                continue

        words = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z]+", text)
        for word in words:
            if word.lower() in ["gint", "scale", "agent", "nimax", "nimax", "飞速"]:
                continue

            if 2 <= len(word) <= 15 and not word.isdigit():
                if word not in existing_sources and word not in existing_targets:
                    if re.match(r"^[\u4e00-\u9fff]+$", word):
                        candidates = []
                        for t in ["飞书", "Agent", "minimax", "OpenClaw"]:
                            if t not in existing_targets:
                                candidates.append(t)

                        if candidates:
                            suggestions.append(
                                {
                                    "caption_id": caption.id,
                                    "original": caption.text,
                                    "src": word,
                                    "dst": candidates[0],
                                    "candidates": candidates[:2],
                                    "confidence": 0.8,
                                    "reason": "可能是专有名词误识别",
                                    "accepted": False,
                                }
                            )

    seen = set()
    unique = []
    for suggestion in suggestions:
        key = (suggestion["caption_id"], suggestion["src"])
        if key not in seen:
            seen.add(key)
            unique.append(suggestion)

    return unique[:20]
