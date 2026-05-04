import json
import time
import urllib.error
import urllib.request
from typing import Any, Iterator

from services.ai_config import build_api_url
from services.ai_logging import redact_headers, write_ai_log


def _responses_input_from_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for message in messages or []:
        role = str(message.get("role") or "user").strip()
        content = message.get("content") or ""
        if isinstance(content, list):
            text = "\n".join(
                str(item.get("text") or "")
                for item in content
                if isinstance(item, dict)
            ).strip()
        else:
            text = str(content).strip()
        if not text:
            continue
        items.append(
            {
                "role": role,
                "content": [{"type": "input_text", "text": text}],
            }
        )
    return items


def _anthropic_content_blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, list):
        blocks: list[dict[str, Any]] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = str(item.get("text") or "").strip()
                if text:
                    blocks.append({"type": "text", "text": text})
        return blocks
    text = str(content or "").strip()
    return [{"type": "text", "text": text}] if text else []


def _anthropic_payload_from_messages(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    messages = normalized.get("messages") or []
    anthropic_messages: list[dict[str, Any]] = []
    system_parts: list[str] = []

    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").strip()
        content_blocks = _anthropic_content_blocks(message.get("content"))
        if not content_blocks:
            continue
        text_content = "\n".join(
            str(block.get("text") or "").strip()
            for block in content_blocks
            if isinstance(block, dict)
        ).strip()
        if role == "system":
            if text_content:
                system_parts.append(text_content)
            continue
        anthropic_messages.append({"role": role, "content": content_blocks})

    normalized["messages"] = anthropic_messages
    if system_parts:
        normalized["system"] = "\n\n".join(part for part in system_parts if part)
    normalized.setdefault("max_tokens", 1000)
    return normalized


def _normalize_payload_for_api_type(payload: dict[str, Any], api_type: str) -> dict[str, Any]:
    normalized = dict(payload)
    if api_type == "responses":
        if "input" not in normalized and "messages" in normalized:
            normalized["input"] = _responses_input_from_messages(normalized.get("messages") or [])
        normalized.pop("messages", None)
    elif api_type == "anthropic-messages":
        normalized = _anthropic_payload_from_messages(normalized)
    return normalized


def _extract_responses_content(data: dict[str, Any]) -> str:
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    output = data.get("output") or []
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        output = [output]

    texts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content") or []
        if isinstance(content, dict):
            content = [content]
        for part in content:
            if not isinstance(part, dict):
                continue
            text_value = part.get("text")
            if isinstance(text_value, str) and text_value:
                texts.append(text_value)
                continue
            nested_text = part.get("output_text")
            if isinstance(nested_text, str) and nested_text:
                texts.append(nested_text)
    return "\n".join(texts).strip()


def _read_sse_lines(res) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for raw_line in res:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line or line.startswith(":") or line.startswith("event:"):
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        if line == "[DONE]":
            break
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _decode_streaming_response_payload(events: list[dict[str, Any]], api_type: str) -> tuple[dict, str]:
    if api_type == "responses":
        parts: list[str] = []
        done_text = ""
        last_event: dict[str, Any] = {}
        for item in events:
            if not isinstance(item, dict):
                continue
            last_event = item
            delta = item.get("delta")
            if isinstance(delta, str) and delta:
                parts.append(delta)
                continue
            event_type = item.get("type")
            if event_type == "response.output_text.done":
                text = item.get("text")
                if isinstance(text, str) and text:
                    done_text = text
        content = "".join(parts).strip() or done_text.strip()
        payload = last_event if isinstance(last_event, dict) else {}
        if content:
            payload = {**payload, "output_text": content}
        return payload, content

    last_payload = events[-1] if events else {}
    if api_type == "anthropic-messages":
        content = ""
        for item in events:
            if not isinstance(item, dict):
                continue
            delta = item.get("delta") or {}
            text = ""
            if isinstance(delta, dict):
                text = str(delta.get("text") or "")
            if not text and item.get("type") == "content_block_delta":
                delta = item.get("delta") or {}
                if isinstance(delta, dict):
                    text = str(delta.get("text") or "")
            if text:
                content += text
        return last_payload, content

    content = ""
    for item in events:
        if not isinstance(item, dict):
            continue
        delta = item.get("choices", [{}])[0].get("delta", {})
        text = (
            delta.get("content")
            or delta.get("reasoning_content")
            or item.get("choices", [{}])[0].get("message", {}).get("content")
            or ""
        )
        if text:
            content += text
    return last_payload, content


def extract_json_object(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        content = content.removeprefix("```json").removeprefix("```").strip()
        if content.endswith("```"):
            content = content[:-3].strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            return json.loads(content[start : end + 1])
        raise


def _decode_response_payload(data: dict, api_type: str) -> tuple[dict, str]:
    if api_type == "anthropic-messages":
        blocks = data.get("content") or []
        if isinstance(blocks, dict):
            blocks = [blocks]
        text_parts: list[str] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text = str(block.get("text") or "")
                if text:
                    text_parts.append(text)
        content = "\n".join(part for part in text_parts if part).strip()
        return data, content
    if api_type == "responses":
        content = _extract_responses_content(data)
        try:
            return json.loads(content), content
        except json.JSONDecodeError:
            return data, content
    content = data["choices"][0]["message"]["content"]
    return data, content


def _post_ai_streaming_retry(
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    api_type: str,
    log: dict[str, Any],
    started_at: float,
    error_prefix: str,
) -> tuple[dict, str, dict]:
    retry_payload = dict(payload)
    retry_payload["stream"] = True
    log["request"]["payload_with_stream"] = retry_payload
    retry_req = urllib.request.Request(
        url,
        data=json.dumps(retry_payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(retry_req, timeout=120) as res:
            events = _read_sse_lines(res)
            wire_data, content = _decode_streaming_response_payload(events, api_type)
            raw_response = "\n".join(json.dumps(item, ensure_ascii=False) for item in events)
            return wire_data, content, {
                "log": log,
                "raw_response": raw_response,
                "wire_data": wire_data,
                "started_at": started_at,
            }
    except Exception as retry_exc:
        log.update(
            {
                "status": "error",
                "duration_ms": int((time.time() - started_at) * 1000),
                "error": f"{error_prefix}: {retry_exc}",
            }
        )
        write_ai_log(log)
        raise RuntimeError(f"{error_prefix}: {retry_exc}") from retry_exc


def post_ai_json(
    *,
    log_type: str,
    active_model: dict,
    payload: dict,
    request_meta: dict | None = None,
    allow_response_format_retry: bool = True,
) -> tuple[dict, str, dict]:
    started_at = time.time()
    api_type = active_model.get("api_type", "compatible")
    headers = {"Content-Type": "application/json"}
    if active_model.get("api_key"):
        headers["Authorization"] = f"Bearer {active_model['api_key']}"
    url = build_api_url(active_model["base_url"], api_type)
    log = {
        "type": log_type,
        "status": "pending",
        "model_name": active_model.get("name"),
        "model": active_model.get("model"),
        "api_type": api_type,
        "url": url,
        "request": {
            "headers": redact_headers(headers),
            "payload": payload,
            **(request_meta or {}),
        },
    }
    normalized_payload = _normalize_payload_for_api_type(payload, api_type)
    log["request"]["payload"] = normalized_payload

    req = urllib.request.Request(
        url,
        data=json.dumps(normalized_payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            if normalized_payload.get("stream"):
                events = _read_sse_lines(res)
                wire_data, content = _decode_streaming_response_payload(events, api_type)
                raw_response = "\n".join(json.dumps(item, ensure_ascii=False) for item in events)
                data = wire_data
            else:
                raw_response = res.read().decode("utf-8")
                wire_data = json.loads(raw_response)
                data, content = _decode_response_payload(wire_data, api_type)
                if api_type == "responses" and not str(content or "").strip():
                    return _post_ai_streaming_retry(
                        url=url,
                        headers=headers,
                        payload=normalized_payload,
                        api_type=api_type,
                        log=log,
                        started_at=started_at,
                        error_prefix="AI 请求空响应，流式重试失败",
                    )
            return data, content, {
                "log": log,
                "raw_response": raw_response,
                "wire_data": wire_data,
                "started_at": started_at,
            }
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if api_type == "responses" and "Stream must be set to true" in detail:
            return _post_ai_streaming_retry(
                url=url,
                headers=headers,
                payload=normalized_payload,
                api_type=api_type,
                log=log,
                started_at=started_at,
                error_prefix="AI 请求流式重试失败",
            )
        if allow_response_format_retry and "response_format" in detail:
            retry_payload = dict(payload)
            retry_payload.pop("response_format", None)
            retry_payload = _normalize_payload_for_api_type(retry_payload, api_type)
            log["request"]["payload_without_response_format"] = retry_payload
            retry_req = urllib.request.Request(
                url,
                data=json.dumps(retry_payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(retry_req, timeout=120) as res:
                    raw_response = res.read().decode("utf-8")
                    wire_data = json.loads(raw_response)
                    data, content = _decode_response_payload(wire_data, api_type)
                    return data, content, {
                        "log": log,
                        "raw_response": raw_response,
                        "wire_data": wire_data,
                        "started_at": started_at,
                    }
            except Exception as retry_exc:
                log.update(
                    {
                        "status": "error",
                        "duration_ms": int((time.time() - started_at) * 1000),
                        "error": f"AI 请求重试失败: {retry_exc}",
                    }
                )
                write_ai_log(log)
                raise RuntimeError(f"AI 请求重试失败: {retry_exc}") from retry_exc
        log.update(
            {
                "status": "error",
                "duration_ms": int((time.time() - started_at) * 1000),
                "error": f"HTTP {exc.code} {detail}",
            }
        )
        write_ai_log(log)
        raise RuntimeError(f"AI 请求失败: HTTP {exc.code} {detail}") from exc
    except Exception as exc:
        log.update(
            {
                "status": "error",
                "duration_ms": int((time.time() - started_at) * 1000),
                "error": str(exc),
            }
        )
        write_ai_log(log)
        raise


def finalize_ai_log_ok(
    context: dict[str, Any],
    *,
    response_preview: str,
    extra: dict | None = None,
) -> dict:
    log = context["log"]
    log.update(
        {
            "status": "ok",
            "duration_ms": int((time.time() - context["started_at"]) * 1000),
            "response": context.get("wire_data"),
            "response_preview": response_preview[:500],
            **(extra or {}),
        }
    )
    return write_ai_log(log)


def stream_ai_json(
    *,
    log_type: str,
    active_model: dict,
    payload: dict,
    request_meta: dict | None = None,
) -> Iterator[dict]:
    started_at = time.time()
    api_type = active_model.get("api_type", "compatible")
    headers = {"Content-Type": "application/json"}
    if active_model.get("api_key"):
        headers["Authorization"] = f"Bearer {active_model['api_key']}"
    url = build_api_url(active_model["base_url"], api_type)

    log = {
        "type": log_type,
        "status": "pending",
        "model_name": active_model.get("name"),
        "model": active_model.get("model"),
        "api_type": api_type,
        "url": url,
        "request": {
            "headers": redact_headers(headers),
            "payload": payload,
            **(request_meta or {}),
        },
    }
    normalized_payload = _normalize_payload_for_api_type(payload, api_type)
    log["request"]["payload"] = normalized_payload

    req = urllib.request.Request(
        url,
        data=json.dumps(normalized_payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    first_content = None
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            for raw_line in res:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    break
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if api_type == "anthropic-messages":
                    content = data.get("content", [{}])[0].get("text") or ""
                elif api_type == "responses":
                    content = (
                        data.get("delta")
                        or data.get("output_text")
                        or _extract_responses_content(data)
                        or ""
                    )
                else:
                    delta = data.get("choices", [{}])[0].get("delta", {})
                    content = (
                        delta.get("content")
                        or delta.get("reasoning_content")
                        or data.get("choices", [{}])[0].get("message", {}).get("content")
                        or ""
                    )

                if content:
                    if first_content is None:
                        first_content = content[:500]
                    yield data

    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        log.update(
            {
                "status": "error",
                "duration_ms": int((time.time() - started_at) * 1000),
                "error": f"HTTP {exc.code} {detail}",
            }
        )
        write_ai_log(log)
        raise RuntimeError(f"AI 流式请求失败: HTTP {exc.code} {detail}") from exc
    except Exception as exc:
        log.update(
            {
                "status": "error",
                "duration_ms": int((time.time() - started_at) * 1000),
                "error": str(exc),
            }
        )
        write_ai_log(log)
        raise

    log.update(
        {
            "status": "ok",
            "duration_ms": int((time.time() - started_at) * 1000),
            "response_preview": first_content or "[DONE]",
        }
    )
    write_ai_log(log)
