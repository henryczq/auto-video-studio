import asyncio
import datetime
import queue
import shutil
import uuid

from services.social_accounts import add_account, load_accounts, update_account
from services.social_common import (
    build_temp_account_alias,
    get_sau_cookie_path,
    is_account_cookie_valid,
    normalize_account_alias,
)
from services.social_qr_runner import run_platform_qr_login
from services.social_qr_store import (
    cleanup_stale_qr_sessions,
    close_qr_login_session,
    delete_recoverable_qr_login as delete_recoverable_qr_login_record,
    delete_qr_session_meta,
    find_latest_recoverable_qr_login,
    get_qr_login_queue,
    get_qr_session_meta,
    list_recoverable_qr_logins,
    load_persisted_qr_sessions,
    recover_qr_session_from_cookie,
    register_qr_login_queue,
    update_qr_session,
)


def start_qr_login(platform: str, account_name: str | None = None, force: bool = False) -> dict:
    cleanup_stale_qr_sessions()
    session_id = str(uuid.uuid4())
    result_queue = queue.Queue()
    normalized_account = normalize_account_alias(account_name)
    temp_account = (
        build_temp_account_alias(platform)
        if normalized_account and force
        else (normalized_account or build_temp_account_alias(platform))
    )

    register_qr_login_queue(session_id, result_queue)
    update_qr_session(
        session_id,
        platform=platform,
        status="pending",
        temp_account=temp_account,
        current_account=temp_account,
        requested_account=normalized_account,
        force=bool(force),
        last_status="正在启动浏览器登录...",
    )

    if normalized_account and not force and is_account_cookie_valid(platform, normalized_account):
        update_qr_session(
            session_id,
            status="success",
            current_account=normalized_account,
            last_message="检测到该账号已登录，无需重新扫码",
        )
        result_queue.put(("status", "检测到该账号已登录，无需重新扫码"))
        result_queue.put(("success", normalized_account))
        return {"session_id": session_id, "temp_account": normalized_account, "recovered": False}

    if not normalized_account:
        recovered = find_latest_recoverable_qr_login(platform)
        if recovered:
            temp_account = recovered["temp_account"]
            update_qr_session(
                session_id,
                status="success",
                temp_account=temp_account,
                current_account=temp_account,
                recovered_from_cookie=True,
                last_message="检测到上次登录已成功，已恢复待保存状态",
            )
            result_queue.put(("status", "检测到上次登录已成功，已恢复待保存状态"))
            result_queue.put(("success", temp_account))
            return {
                "session_id": session_id,
                "temp_account": temp_account,
                "recovered": True,
                "recovered_candidate": recovered,
            }

    if platform in {"douyin", "kuaishou", "xiaohongshu"}:
        asyncio.create_task(run_platform_qr_login(session_id, platform, temp_account, result_queue))
    elif platform == "bilibili":
        result_queue.put(("status", "等待提交 B 站登录..."))
        update_qr_session(
            session_id,
            status="pending",
            last_status="等待提交 B 站登录...",
        )
    else:
        result_queue.put(("error", f"平台 {platform} 暂不支持扫码登录"))
        update_qr_session(
            session_id,
            status="error",
            last_error=f"平台 {platform} 暂不支持扫码登录",
        )

    return {"session_id": session_id, "temp_account": temp_account, "recovered": False}


def get_qr_login_result(session_id: str) -> dict:
    result_queue = get_qr_login_queue(session_id)
    meta = recover_qr_session_from_cookie(session_id)
    if not result_queue and not meta:
        return {"type": "error", "message": "session 不存在或已过期"}

    try:
        if not result_queue:
            raise queue.Empty
        msg_type, data = result_queue.get_nowait()
        meta = get_qr_session_meta(session_id)

        if msg_type == "qrcode":
            return {"type": "qrcode", "data": data}
        if msg_type == "status":
            return {"type": "status", "data": data}
        if msg_type == "success":
            return {"type": "success", "account": data, "meta": meta}
        if msg_type == "error":
            return {"type": "error", "message": data}
    except queue.Empty:
        meta = recover_qr_session_from_cookie(session_id, meta)
        status = meta.get("status", "unknown")
        if status == "success":
            return {"type": "success", "account": meta.get("current_account"), "meta": meta}
        if status == "error":
            return {"type": "error", "message": meta.get("last_error") or "登录失败"}
        if meta.get("last_qrcode"):
            return {"type": "qrcode", "data": meta.get("last_qrcode"), "meta": meta}
        if meta.get("last_status"):
            return {"type": "status", "data": meta.get("last_status"), "meta": meta}
        return {"type": "pending"}


def finalize_qr_login_account(session_id: str, account_name: str, label: str = "") -> dict:
    meta = recover_qr_session_from_cookie(session_id)
    if not meta:
        raise ValueError("session 不存在或已过期")

    platform = meta.get("platform")
    temp_account = meta.get("current_account") or meta.get("temp_account")
    if not platform:
        raise ValueError("无法确定平台")

    normalized_account = normalize_account_alias(account_name)
    if not normalized_account:
        raise ValueError("请输入保存名称")

    temp_cookie_path = get_sau_cookie_path(platform, temp_account)
    final_cookie_path = get_sau_cookie_path(platform, normalized_account)
    if meta.get("status") != "success" and not (
        temp_cookie_path.exists() and is_account_cookie_valid(platform, temp_account)
    ):
        raise ValueError("登录尚未完成，请先在浏览器中完成登录")
    if not temp_cookie_path.exists() and not final_cookie_path.exists():
        raise ValueError("登录结果未找到，请重新登录")
    if final_cookie_path.exists() and final_cookie_path != temp_cookie_path:
        raise ValueError(f"账号已存在: {platform}/{normalized_account}")
    if temp_cookie_path.exists() and temp_cookie_path != final_cookie_path:
        final_cookie_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temp_cookie_path), str(final_cookie_path))

    account = add_account(platform, normalized_account, label=label)
    close_qr_login_session(session_id, clear_meta=True)
    return account


def finalize_existing_qr_login_account(session_id: str) -> dict:
    meta = recover_qr_session_from_cookie(session_id)
    if not meta:
        raise ValueError("session 不存在或已过期")

    platform = meta.get("platform")
    temp_account = meta.get("current_account") or meta.get("temp_account")
    final_account = meta.get("requested_account")
    if not platform or not temp_account or not final_account:
        raise ValueError("无法确定当前账号")

    temp_cookie_path = get_sau_cookie_path(platform, temp_account)
    final_cookie_path = get_sau_cookie_path(platform, final_account)
    if meta.get("status") != "success" and not (
        temp_cookie_path.exists() and is_account_cookie_valid(platform, temp_account)
    ):
        raise ValueError("登录尚未完成，请先在浏览器中完成登录")
    if not temp_cookie_path.exists():
        raise ValueError("登录结果未找到，请重新扫码登录")

    final_cookie_path.parent.mkdir(parents=True, exist_ok=True)
    if final_cookie_path.exists() and final_cookie_path != temp_cookie_path:
        final_cookie_path.unlink()
    if temp_cookie_path != final_cookie_path:
        shutil.move(str(temp_cookie_path), str(final_cookie_path))

    close_qr_login_session(session_id, clear_meta=True)
    existing_account = next(
        (item for item in load_accounts() if item.get("platform") == platform and item.get("account") == final_account),
        None,
    )
    if existing_account:
        return update_account(
            existing_account["id"],
            {
                "last_check_status": "valid",
                "last_check_at": datetime.datetime.now().isoformat(),
                "last_error": "",
            },
        )
    account = add_account(platform, final_account)
    update_account(
        account["id"],
        {
            "last_check_status": "valid",
            "last_check_at": datetime.datetime.now().isoformat(),
            "last_error": "",
        },
    )
    return account


def list_recoverable_qr_candidates(platform: str | None = None, limit: int = 5) -> list[dict]:
    return list_recoverable_qr_logins(platform=platform, limit=limit)


def delete_recoverable_qr_candidate(
    platform: str,
    temp_account: str,
    session_id: str | None = None,
) -> dict:
    return delete_recoverable_qr_login_record(platform, temp_account, session_id=session_id)


def recover_qr_login_account(
    platform: str,
    temp_account: str,
    account_name: str,
    label: str = "",
) -> dict:
    normalized_platform = (platform or "").strip()
    normalized_temp_account = normalize_account_alias(temp_account)
    normalized_account = normalize_account_alias(account_name)

    if not normalized_platform:
        raise ValueError("platform is required")
    if not normalized_temp_account.startswith("tmp_"):
        raise ValueError("临时账号不存在或不可恢复")
    if not normalized_account:
        raise ValueError("请输入保存名称")

    temp_cookie_path = get_sau_cookie_path(normalized_platform, normalized_temp_account)
    final_cookie_path = get_sau_cookie_path(normalized_platform, normalized_account)
    if not temp_cookie_path.exists():
        raise ValueError("待恢复的登录结果不存在")
    if not is_account_cookie_valid(normalized_platform, normalized_temp_account):
        raise ValueError("待恢复的登录结果已失效，请重新登录")
    if final_cookie_path.exists() and final_cookie_path != temp_cookie_path:
        raise ValueError(f"账号已存在: {normalized_platform}/{normalized_account}")

    final_cookie_path.parent.mkdir(parents=True, exist_ok=True)
    if temp_cookie_path != final_cookie_path:
        shutil.move(str(temp_cookie_path), str(final_cookie_path))

    account = add_account(normalized_platform, normalized_account, label=label)

    for session_id, meta in list(load_persisted_qr_sessions().items()):
        meta_platform = meta.get("platform")
        meta_account = meta.get("current_account") or meta.get("temp_account")
        if meta_platform == normalized_platform and meta_account == normalized_temp_account:
            close_qr_login_session(session_id, clear_meta=False)
            delete_qr_session_meta(session_id)

    return account
