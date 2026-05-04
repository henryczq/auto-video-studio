from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from routers.auth import verify_token
from routers.social_shared import run_or_400, run_or_500
from services import social_service


router = APIRouter()


@router.get("/settings")
async def get_social_settings(_: bool = Depends(verify_token)):
    return social_service.get_settings()


@router.post("/settings")
async def save_social_settings(settings: dict, _: bool = Depends(verify_token)):
    return run_or_500(social_service.save_settings, settings)


@router.get("/cli-status")
async def get_cli_status(_: bool = Depends(verify_token)):
    return social_service.check_cli_available()


@router.get("/platforms")
async def get_platforms(_: bool = Depends(verify_token)):
    return {"platforms": social_service.get_platforms_with_info()}


@router.get("/platforms/creator-urls")
async def get_creator_urls(_: bool = Depends(verify_token)):
    return social_service.get_creator_urls()


@router.get("/bilibili-categories")
async def get_bilibili_categories(_: bool = Depends(verify_token)):
    return {"categories": social_service.get_categories("bilibili")}


@router.get("/platforms/config")
async def get_platforms_config(_: bool = Depends(verify_token)):
    return social_service.load_platforms_config()


@router.put("/platforms/config")
async def save_platforms_config(config: dict, _: bool = Depends(verify_token)):
    return social_service.save_platforms_config(config)


@router.get("/accounts")
async def list_accounts(_: bool = Depends(verify_token)):
    return social_service.load_accounts()


@router.post("/accounts")
async def create_account(data: dict, _: bool = Depends(verify_token)):
    return run_or_400(
        social_service.add_account,
        platform=data["platform"],
        account=data["account"],
        label=data.get("label", ""),
    )


@router.put("/accounts/{account_id}")
async def edit_account(account_id: str, data: dict, _: bool = Depends(verify_token)):
    return run_or_400(social_service.update_account, account_id, data)


@router.delete("/accounts/{account_id}")
async def remove_account(account_id: str, _: bool = Depends(verify_token)):
    run_or_400(social_service.delete_account, account_id)
    return {"status": "deleted", "account_id": account_id}


@router.post("/accounts/{account_id}/check")
async def check_login(account_id: str, _: bool = Depends(verify_token)):
    return await run_in_threadpool(run_or_400, social_service.check_account_status, account_id)


@router.post("/accounts/{account_id}/prepare-cookie")
async def prepare_cookie(account_id: str, _: bool = Depends(verify_token)):
    return await run_in_threadpool(run_or_400, social_service.prepare_account_cookie, account_id)


@router.post("/accounts/{account_id}/login-command")
async def get_login_cmd(
    account_id: str, headed: bool = True, _: bool = Depends(verify_token)
):
    return {"command": run_or_400(social_service.get_login_command, account_id, headed)}


@router.post("/accounts/{account_id}/login-terminal")
async def launch_login_terminal(
    account_id: str, headed: bool = True, _: bool = Depends(verify_token)
):
    return await run_in_threadpool(
        run_or_400,
        social_service.launch_login_terminal,
        account_id,
        headed,
    )


@router.get("/accounts/{account_id}/logs")
async def get_logs(account_id: str, _: bool = Depends(verify_token)):
    return {"content": social_service.get_account_log(account_id)}


@router.post("/accounts/{account_id}/open-creator")
async def open_creator(account_id: str, _: bool = Depends(verify_token)):
    from services.social_browser import open_creator_page
    return await run_in_threadpool(run_or_400, open_creator_page, account_id)
