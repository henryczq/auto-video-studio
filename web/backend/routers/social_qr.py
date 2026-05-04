import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from routers.auth import verify_token
from routers.social_shared import (
    initial_qr_stream_payload,
    run_or_400,
    sse_event,
)
from services import social_service


router = APIRouter()


class BilibiliLoginRequest(BaseModel):
    session_id: str
    username: str
    password: str
    mode: str = "account_password"
    sessdata: str = ""
    bili_jct: str = ""


@router.post("/qr-login/start")
async def start_qr_login_api(
    data: dict,
    _: bool = Depends(verify_token),
):
    platform = data.get("platform")
    account_name = data.get("account")
    force = bool(data.get("force"))
    if not platform:
        raise HTTPException(status_code=400, detail="platform is required")
    return run_or_400(social_service.start_qr_login, platform, account_name, force=force)


@router.get("/qr-login/stream/{session_id}")
async def qr_login_stream(session_id: str, _: bool = Depends(verify_token)):
    def event_stream():
        q = social_service.get_qr_login_queue(session_id)
        if not q:
            yield sse_event(initial_qr_stream_payload(session_id))
            return

        last_check = 0
        while True:
            try:
                if not q.empty():
                    msg_type, msg_data = q.get_nowait()
                    if msg_type == "qrcode":
                        yield sse_event({"type": "qrcode", "data": msg_data})
                    elif msg_type == "status":
                        yield sse_event({"type": "status", "data": msg_data})
                    elif msg_type == "success":
                        yield sse_event({"type": "success", "account_name": msg_data})
                        break
                    elif msg_type == "error":
                        yield sse_event({"type": "error", "message": msg_data})
                        social_service.close_qr_login_session(session_id, clear_meta=True)
                        break
                    last_check = time.time()
                else:
                    if time.time() - last_check > 30:
                        yield sse_event({"type": "ping"})
                        last_check = time.time()
                    time.sleep(0.5)
            except Exception:
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/qr-login/result/{session_id}")
async def qr_login_result(session_id: str, _: bool = Depends(verify_token)):
    return social_service.get_qr_login_result(session_id)


@router.get("/qr-login/recoverable")
async def qr_login_recoverable(
    platform: str = None,
    limit: int = 5,
    _: bool = Depends(verify_token),
):
    return {
        "items": social_service.list_recoverable_qr_candidates(platform=platform, limit=limit)
    }


@router.delete("/qr-login/recoverable")
async def delete_recoverable_qr_login(
    data: dict,
    _: bool = Depends(verify_token),
):
    platform = data.get("platform")
    temp_account = data.get("temp_account")
    session_id = data.get("session_id")
    if not platform or not temp_account:
        raise HTTPException(status_code=400, detail="platform and temp_account are required")
    result = run_or_400(
        social_service.delete_recoverable_qr_candidate,
        platform,
        temp_account,
        session_id=session_id,
    )
    return {"status": "deleted", **result}


@router.post("/qr-login/add-account")
async def add_account_from_qr_login(
    data: dict,
    _: bool = Depends(verify_token),
):
    session_id = data.get("session_id")
    account_name = data.get("account")
    label = data.get("label", "")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    return run_or_400(
        social_service.finalize_qr_login_account,
        session_id,
        account_name,
        label=label,
    )


@router.post("/qr-login/refresh-account")
async def refresh_existing_account_from_qr_login(
    data: dict,
    _: bool = Depends(verify_token),
):
    session_id = data.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    return run_or_400(
        social_service.finalize_existing_qr_login_account,
        session_id,
    )


@router.post("/qr-login/recover-account")
async def recover_account_from_qr_login(
    data: dict,
    _: bool = Depends(verify_token),
):
    platform = data.get("platform")
    temp_account = data.get("temp_account")
    account_name = data.get("account")
    label = data.get("label", "")
    if not platform or not temp_account:
        raise HTTPException(status_code=400, detail="platform and temp_account are required")
    return run_or_400(
        social_service.recover_qr_login_account,
        platform,
        temp_account,
        account_name,
        label=label,
    )


@router.post("/bilibili/login")
async def bilibili_login_api(
    req: BilibiliLoginRequest,
    _: bool = Depends(verify_token),
):
    result = await social_service.login_bilibili(
        req.session_id,
        req.username,
        req.password,
        req.mode,
        sessdata=req.sessdata,
        bili_jct=req.bili_jct,
    )
    if not result["success"]:
        return result
    return result


@router.get("/bilibili/browser-cookies")
async def bilibili_browser_cookies_api(_: bool = Depends(verify_token)):
    return social_service.read_bilibili_browser_cookies()
