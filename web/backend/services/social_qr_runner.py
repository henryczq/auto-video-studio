import asyncio
import json
import queue

from services.social_common import prepare_sau_imports
from services.social_config import get_sau_python
from services.social_qr_store import update_qr_session


async def run_browser_qr_login(
    session_id: str, platform: str, account_name: str, result_queue: queue.Queue
):
    sau_root = prepare_sau_imports()
    sau_python = get_sau_python()
    if not sau_python.exists():
        result_queue.put(("error", f"SAU Python 不存在: {sau_python}"))
        return

    result_queue.put(("status", "正在启动浏览器登录..."))

    runner_code = r"""
import asyncio, json, sys
from pathlib import Path

sau_root = Path(sys.argv[1])
platform = sys.argv[2]
account_name = sys.argv[3]
sys.path.insert(0, str(sau_root))

from sau_cli import resolve_account_file

PLATFORM_IMPORTS = {
    "douyin": ("uploader.douyin_uploader.main", "douyin_setup"),
    "kuaishou": ("uploader.ks_uploader.main", "ks_setup"),
    "xiaohongshu": ("uploader.xiaohongshu_uploader.main", "xiaohongshu_setup"),
}

module_name, func_name = PLATFORM_IMPORTS[platform]
module = __import__(module_name, fromlist=[func_name])
setup_func = getattr(module, func_name)
account_file = resolve_account_file(platform, account_name)

async def on_qrcode(payload):
    print(json.dumps({"type": "qrcode", "payload": payload}, ensure_ascii=False), flush=True)

async def main():
    result = await setup_func(
        str(account_file),
        handle=True,
        return_detail=True,
        qrcode_callback=on_qrcode,
        headless=False,
    )
    print(json.dumps({"type": "result", "result": result}, ensure_ascii=False), flush=True)

asyncio.run(main())
"""

    process = await asyncio.create_subprocess_exec(
        str(sau_python),
        "-u",
        "-c",
        runner_code,
        str(sau_root),
        platform,
        account_name,
        cwd=str(sau_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    terminal_result_received = False

    async def finalize_from_result(result: dict):
        nonlocal terminal_result_received
        terminal_result_received = True
        if result.get("success"):
            update_qr_session(
                session_id,
                status="success",
                current_account=account_name,
                last_message=result.get("message") or "登录成功",
            )
            result_queue.put(("success", account_name))
            return

        qrcode = result.get("qrcode") or {}
        if qrcode.get("image_data_url"):
            result_queue.put(("qrcode", qrcode["image_data_url"]))
        elif qrcode.get("image_path"):
            result_queue.put(("status", f"二维码已生成: {qrcode['image_path']}"))
        update_qr_session(
            session_id,
            status="error",
            last_error=result.get("message") or "登录失败",
        )
        result_queue.put(("error", result.get("message") or "登录失败"))

    try:
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").strip()
            if not decoded:
                continue
            try:
                payload = json.loads(decoded)
            except json.JSONDecodeError:
                continue

            if payload.get("type") == "qrcode":
                qrcode_payload = payload.get("payload") or {}
                image_data_url = qrcode_payload.get("image_data_url")
                image_path = qrcode_payload.get("image_path")
                if image_data_url:
                    update_qr_session(
                        session_id,
                        last_qrcode=image_data_url,
                        last_status="浏览器已启动；如果浏览器里没显示二维码，可使用当前图片扫码",
                    )
                    result_queue.put(("qrcode", image_data_url))
                    result_queue.put(
                        ("status", "浏览器已启动；如果浏览器里没显示二维码，可使用当前图片扫码")
                    )
                elif image_path:
                    update_qr_session(
                        session_id,
                        last_qrcode_path=image_path,
                        last_status=f"浏览器已启动；如需兜底二维码，可查看: {image_path}",
                    )
                    result_queue.put(("status", f"浏览器已启动；如需兜底二维码，可查看: {image_path}"))
            elif payload.get("type") == "result":
                await finalize_from_result(payload.get("result") or {})
                break

        await process.wait()
        if process.returncode != 0 and not terminal_result_received:
            stderr = (await process.stderr.read()).decode("utf-8", errors="replace").strip()
            update_qr_session(
                session_id,
                status="error",
                last_error=stderr or f"登录进程异常退出: {process.returncode}",
            )
            result_queue.put(("error", stderr or f"登录进程异常退出: {process.returncode}"))
    except Exception as exc:
        if terminal_result_received:
            return
        update_qr_session(session_id, status="error", last_error=f"{type(exc).__name__}: {exc}")
        result_queue.put(("error", f"{type(exc).__name__}: {exc}"))


async def run_platform_qr_login(
    session_id: str, platform: str, account_name: str, result_queue: queue.Queue
):
    try:
        await run_browser_qr_login(session_id, platform, account_name, result_queue)
    except Exception as exc:
        import traceback

        result_queue.put(("error", f"{type(exc).__name__}: {str(exc)}\n{traceback.format_exc()}"))
