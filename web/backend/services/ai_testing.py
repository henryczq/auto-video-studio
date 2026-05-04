import time
from collections.abc import Callable, Iterator
from typing import Any

# Generic function types for dependency injection.
# Other projects can pass their own HTTP client and log writer implementations.

PostJsonFn = Callable[..., tuple[dict, str, dict]]
StreamJsonFn = Callable[..., Iterator[dict]]
WriteLogFn = Callable[[dict], Any]


def build_ai_test_payload(model: dict) -> dict:
    """Build a minimal connectivity-test payload for a configured model.

    Args:
        model: Model config dict. Expected keys include:
            - model: remote model name
            - api_type: one of compatible / responses / anthropic-messages

    Returns:
        A request payload suitable for the target API type.

    Notes:
        - `responses` uses a short streaming request so we can stop early.
        - `anthropic-messages` uses Anthropic-style `system` + `max_tokens`.
    """
    api_type = model.get("api_type", "compatible")
    payload = {
        "model": model["model"],
        "messages": [{"role": "user", "content": "请只回复 OK，用于连通性测试。"}],
        "temperature": 0,
    }
    if api_type == "anthropic-messages":
        payload["system"] = "You are a helpful assistant."
        payload["max_tokens"] = 1000
    if api_type == "responses":
        payload["stream"] = True
        payload["max_output_tokens"] = 32
    return payload


def run_ai_model_test(
    model: dict,
    *,
    post_json: PostJsonFn,
    stream_json: StreamJsonFn,
    write_log: WriteLogFn | None = None,
    stop_on_first_chunk: bool = True,
) -> dict:
    """Run a model connectivity test using injected request/log functions.

    This is the reusable core entrypoint for other projects.

    Args:
        model: Model config dict. Must at least contain `base_url` and `model`.
        post_json: Callable used for non-streaming requests.
            Expected signature is compatible with this project's `post_ai_json`,
            i.e. keyword args like:
                log_type, active_model, payload, request_meta,
                allow_response_format_retry
            and return value:
                (wire_data, content, ctx)
        stream_json: Callable used for streaming requests.
            Expected signature is compatible with this project's
            `stream_ai_json`, and should yield event dicts.
        write_log: Optional log writer. If provided, successful non-streaming
            test results will be written through it.
        stop_on_first_chunk: For streaming APIs, return immediately after the
            first non-empty chunk. This is usually what a connectivity test wants.

    Returns:
        Dict like:
            {"status": "ok", "first_response": "..."}

    Raises:
        ValueError: If required model fields are missing.
        RuntimeError: If the underlying request fails.
    """
    if not model.get("base_url") or not model.get("model"):
        raise ValueError("请填写 Base URL 和模型名")

    api_type = model.get("api_type", "compatible")
    payload = build_ai_test_payload(model)

    try:
        if api_type == "responses":
            last_content = ""
            for data in stream_json(
                log_type="test",
                active_model=model,
                payload=payload,
                request_meta={"test": True},
            ):
                content = data.get("delta") or data.get("output_text") or ""
                if content:
                    last_content = str(content)
                    if stop_on_first_chunk:
                        return {"status": "ok", "first_response": last_content[:500]}
            if last_content:
                return {"status": "ok", "first_response": last_content[:500]}
            return {"status": "ok", "first_response": "已收到响应，但首段内容为空"}

        _, content, ctx = post_json(
            log_type="test",
            active_model=model,
            payload=payload,
            request_meta={"test": True},
            allow_response_format_retry=False,
        )
        text = (content or "").strip()
        ctx["log"].update(
            {
                "status": "ok",
                "duration_ms": int((time.time() - ctx["started_at"]) * 1000),
                "response": ctx.get("wire_data"),
                "response_preview": text[:500] or "[empty]",
            }
        )
        if write_log:
            write_log(ctx["log"])
        if text:
            return {"status": "ok", "first_response": text[:500]}
    except Exception as exc:
        raise RuntimeError(f"AI 测试失败: {exc}") from exc

    return {"status": "ok", "first_response": "已收到响应，但首段内容为空"}


def test_ai_model(model: dict) -> dict:
    """Project-local wrapper around `run_ai_model_test`.

    This keeps the existing call site simple inside this project while still
    allowing the core logic above to stay reusable for other projects.
    """
    from services.ai_client import post_ai_json, stream_ai_json
    from services.ai_logging import write_ai_log

    return run_ai_model_test(
        model,
        post_json=post_ai_json,
        stream_json=stream_ai_json,
        write_log=write_ai_log,
    )
