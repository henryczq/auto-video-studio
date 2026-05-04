import json

from fastapi import HTTPException

from services import social_service


def raise_http_error(status_code: int, exc: Exception):
    raise HTTPException(status_code=status_code, detail=str(exc))


def run_or_400(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        raise_http_error(400, exc)


def run_or_500(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        raise_http_error(500, exc)


def sse_event(payload: dict) -> str:
    return "data: " + json.dumps(payload) + "\n\n"


def initial_qr_stream_payload(session_id: str) -> dict:
    result = social_service.get_qr_login_result(session_id)
    result_type = result.get("type")
    if result_type == "success":
        return {"type": "success", "account_name": result.get("account")}
    if result_type == "status":
        return {"type": "status", "data": result.get("data")}
    if result_type == "qrcode":
        return {"type": "qrcode", "data": result.get("data")}
    if result_type == "pending":
        return {"type": "status", "data": "浏览器登录仍在进行，请继续在浏览器中完成"}
    return {"type": "error", "message": result.get("message") or "Session not found"}
