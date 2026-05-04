from services.social_accounts import (
    add_account,
    delete_account,
    get_account,
    list_accounts,
    load_accounts,
    save_accounts,
    update_account,
)
from services.social_bilibili import login_bilibili, read_bilibili_browser_cookies
from services.social_cli import (
    check_account_status as check_account_status_cli,
    check_cli_available,
    get_login_command,
    launch_login_terminal,
)
from services.social_config import (
    BILIBILI_CATEGORIES,
    PLATFORMS,
    get_categories,
    get_cli_name,
    get_creator_urls,
    get_platform_info,
    get_platforms,
    get_platforms_with_info,
    get_sau_cli,
    get_sau_python,
    get_sau_root,
    get_settings,
    load_platforms_config,
    save_platforms_config,
    save_settings,
)
from services.social_logs import (
    add_upload_record,
    ensure_logs_dir,
    get_account_log,
    get_upload_record,
    get_upload_log,
    get_upload_records,
    get_upload_records_for_job,
    load_upload_records,
    save_upload_records,
    update_upload_record,
)
from services.social_cover import (
    generate_cover_from_video,
    generate_text_cover,
    save_uploaded_cover,
)
from services.social_qr import (
    close_qr_login_session,
    delete_recoverable_qr_candidate,
    finalize_existing_qr_login_account,
    finalize_qr_login_account,
    get_qr_login_queue,
    get_qr_login_result,
    list_recoverable_qr_candidates,
    recover_qr_login_account,
    start_qr_login,
)
from services.social_upload_runner import upload_video as upload_video_cli
from services.social_bridge_runner import (
    bridge_publish_video,
    check_bridge_account_status,
    is_bridge_platform,
    prepare_bridge_account_cookie,
)


def check_account_status(account_id: str) -> dict:
    account = get_account(account_id)
    if not account:
        raise ValueError(f"账号不存在: {account_id}")
    if is_bridge_platform(account["platform"]):
        return check_bridge_account_status(account_id)
    return check_account_status_cli(account_id)


def upload_video(
    job_id: str,
    account_id: str,
    video_path: str,
    title: str,
    desc: str = "",
    tags: str = "",
    publish_mode: str = "",
    schedule: str = "",
    tid: str = "",
    cli_name: str = None,
    record_id: str | None = None,
    thumbnail: str = "",
    preview: bool = False,
) -> dict:
    account = get_account(account_id)
    if not account:
        raise ValueError(f"账号不存在: {account_id}")
    if is_bridge_platform(account["platform"]):
        return bridge_publish_video(
            job_id,
            account_id,
            video_path,
            title,
            desc,
            tags,
            publish_mode,
            schedule,
            tid,
            cli_name,
            record_id,
            thumbnail,
            preview,
        )
    return upload_video_cli(
        job_id,
        account_id,
        video_path,
        title,
        desc,
        tags,
        publish_mode,
        schedule,
        tid,
        cli_name,
        record_id,
        thumbnail,
        preview,
    )


def prepare_account_cookie(account_id: str) -> dict:
    account = get_account(account_id)
    if not account:
        raise ValueError(f"账号不存在: {account_id}")
    if is_bridge_platform(account["platform"]):
        return prepare_bridge_account_cookie(account_id)
    raise ValueError(f"平台 {account['platform']} 当前不走网页登录准备")

__all__ = [
    "PLATFORMS",
    "BILIBILI_CATEGORIES",
    "get_settings",
    "save_settings",
    "get_sau_root",
    "get_sau_python",
    "get_sau_cli",
    "load_accounts",
    "save_accounts",
    "add_account",
    "update_account",
    "delete_account",
    "get_account",
    "list_accounts",
    "load_upload_records",
    "save_upload_records",
    "add_upload_record",
    "get_upload_record",
    "get_upload_records",
    "get_upload_records_for_job",
    "update_upload_record",
    "generate_cover_from_video",
    "generate_text_cover",
    "save_uploaded_cover",
    "get_account_log",
    "ensure_logs_dir",
    "get_upload_log",
    "check_cli_available",
    "check_account_status",
    "get_login_command",
    "launch_login_terminal",
    "upload_video",
    "prepare_account_cookie",
    "start_qr_login",
    "get_qr_login_result",
    "finalize_existing_qr_login_account",
    "finalize_qr_login_account",
    "list_recoverable_qr_candidates",
    "delete_recoverable_qr_candidate",
    "recover_qr_login_account",
    "get_qr_login_queue",
    "close_qr_login_session",
    "login_bilibili",
    "read_bilibili_browser_cookies",
]
