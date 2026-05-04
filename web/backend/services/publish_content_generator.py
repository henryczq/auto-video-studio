"""Generate title, description and tags from video subtitles using AI."""

import json
import re
from pathlib import Path
from typing import Optional

from services.ai_client import finalize_ai_log_ok, post_ai_json
from services.ai_config import get_active_ai_model, load_ai_config
from services.publish_settings_store import load_publish_settings
from services.captions import read_json, read_srt
from services.job_store import get_job_dir, load_job

STYLE_LABELS = {
    "tutorial": "教程型",
    "hook": "爆点型",
    "workplace": "职场效率型",
}


def _extract_text_from_srt(srt_path: str) -> str:
    """Extract plain text from SRT or JSON captions."""
    try:
        path = Path(srt_path)
        if path.suffix == ".json":
            captions = read_json(path)
        else:
            captions = read_srt(path)
        texts = [c.text for c in captions]
        text = " ".join(texts)
        text = re.sub(r'<[^>]+>', '', text)
        return text.strip()
    except Exception as exc:
        raise ValueError(f"无法读取字幕文件: {exc}")


def _get_ai_model(settings: dict) -> Optional[dict]:
    """Get AI model to use for generation."""
    ai_config = load_ai_config()
    
    # If specific model is configured, find it
    if settings.get("ai_model"):
        for model in ai_config.get("models", []):
            if model.get("name") == settings["ai_model"]:
                return model
    
    # Otherwise use active model
    return get_active_ai_model(ai_config)


def _generate_with_prompt(prompt: str, model: dict) -> str:
    """Generate content using AI model."""
    api_type = model.get("api_type", "compatible")
    
    if api_type == "anthropic-messages":
        payload = {
            "model": model["model"],
            "system": "You are a helpful assistant.",
            "messages": [
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 2048,
        }
    else:
        payload = {
            "model": model["model"],
            "messages": [
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
        }
        if api_type == "compatible":
            payload["response_format"] = {"type": "text"}
    
    _, content, ctx = post_ai_json(
        log_type="publish_content",
        active_model=model,
        payload=payload,
    )
    finalize_ai_log_ok(ctx, response_preview=content)
    
    return content.strip()


def _parse_json_response(content: str) -> dict:
    """Parse JSON response from AI, handling markdown code blocks."""
    content = content.strip()
    if not content:
        raise ValueError("AI 返回空内容，未生成可用文案。请重试一次，或切换发布内容生成模型。")
    if content.startswith("```"):
        lines = content.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        content = "\n".join(lines).strip()
    
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(content[start : end + 1])
            except json.JSONDecodeError:
                pass
        preview = content[:300].replace("\n", " ")
        raise ValueError(f"无法解析AI返回的JSON: {e}. 返回预览: {preview}")


def _normalize_tags(tags) -> list[str]:
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.replace("，", ",").split(",") if t.strip()]
    if not isinstance(tags, list):
        return []
    clean_tags = []
    seen = set()
    for tag in tags:
        text = str(tag or "").strip()
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        clean_tags.append(text)
    return clean_tags


def _normalize_version_payload(style_key: str, payload: dict, default_tags: list[str]) -> dict:
    if not isinstance(payload, dict):
        payload = {}
    tags = _normalize_tags(payload.get("tags", []))
    for tag in default_tags:
        if tag not in tags:
            tags.append(tag)
    title = str(payload.get("title", "") or "").strip()
    description = str(payload.get("description", "") or "").strip()
    return {
        "style": style_key,
        "label": str(payload.get("label") or STYLE_LABELS.get(style_key, style_key)),
        "title": title,
        "description": description,
        "tags": tags[:5],
    }


def _normalize_generation_result(result: dict, default_tags: list[str]) -> dict:
    versions = result.get("versions")
    recommended_style = str(result.get("recommended_style") or "workplace").strip()

    if isinstance(versions, dict):
        normalized_versions = {}
        for style_key in ["tutorial", "hook", "workplace"]:
            normalized_versions[style_key] = _normalize_version_payload(
                style_key,
                versions.get(style_key, {}),
                default_tags,
            )
        if not normalized_versions.get(recommended_style, {}).get("title"):
            recommended_style = "workplace"
        recommended = normalized_versions[recommended_style]
        if not recommended.get("title"):
            for fallback_key in ["workplace", "tutorial", "hook"]:
                if normalized_versions[fallback_key].get("title"):
                    recommended_style = fallback_key
                    recommended = normalized_versions[fallback_key]
                    break
        if not recommended.get("title"):
            raise ValueError("AI未返回可用标题")
        return {
            "recommended_style": recommended_style,
            "versions": normalized_versions,
            "title": recommended["title"],
            "description": recommended["description"],
            "tags": recommended["tags"],
        }

    title = str(result.get("title", "") or "").strip()
    description = str(result.get("description", "") or "").strip()
    tags = _normalize_tags(result.get("tags", []))
    for tag in default_tags:
        if tag not in tags:
            tags.append(tag)
    if not title:
        raise ValueError("AI未返回标题")
    single_version = {
        "style": "single",
        "label": "推荐",
        "title": title,
        "description": description,
        "tags": tags[:5],
    }
    return {
        "recommended_style": "single",
        "versions": {"single": single_version},
        "title": single_version["title"],
        "description": single_version["description"],
        "tags": single_version["tags"],
    }


def resolve_publish_subtitles_path(job_id: str) -> tuple[str, str]:
    job = load_job(job_id)
    if not job:
        raise ValueError("任务不存在")

    job_dir = get_job_dir(job_id)
    candidates = [
        ("裁剪后字幕", job.captions_trimmed),
        ("当前字幕（裁剪后）", "captions.trimmed.json"),
        ("当前字幕（兼容旧 SRT）", job.captions_final),
        ("当前字幕（SRT）", "captions.derived.srt"),
        ("当前字幕", "captions.working.json"),
        ("当前字幕（兼容旧文件）", job.captions_edited),
        ("原始字幕", "captions.source.json"),
        ("原始字幕", job.captions_initial),
        ("原始字幕JSON", job.captions_initial_json),
    ]
    for label, path_value in candidates:
        if not path_value:
            continue
        path = Path(path_value)
        if not path.is_absolute():
            path = job_dir / path
        if path.exists():
            return str(path), label
    raise ValueError("该任务没有可用字幕，请先完成视频处理或保存字幕")


def generate_publish_content(srt_path: str) -> dict:
    """Generate title, description and tags from subtitles.
    
    Returns:
        {
            "title": str,
            "description": str,
            "tags": list[str],
        }
    """
    settings = load_publish_settings()
    model = _get_ai_model(settings)
    
    if not model:
        raise ValueError("未配置 AI 模型，请先在 AI 配置中设置模型")
    
    # Extract subtitles text
    subtitles_text = _extract_text_from_srt(srt_path)
    if not subtitles_text:
        raise ValueError("字幕文件为空")
    
    # Truncate if too long
    if len(subtitles_text) > 3000:
        subtitles_text = subtitles_text[:3000] + "..."
    
    # Generate content using single prompt
    content_prompt = settings.get("content_prompt", "").replace("{subtitles}", subtitles_text)
    response = _generate_with_prompt(content_prompt, model)
    
    # Parse JSON response
    result = _parse_json_response(response)
    
    default_tags = settings.get("default_tags", [])
    return _normalize_generation_result(result, default_tags)


def generate_publish_content_for_job(job_id: str) -> dict:
    srt_path, source_label = resolve_publish_subtitles_path(job_id)
    result = generate_publish_content(srt_path)
    result["subtitle_source"] = source_label
    return result
