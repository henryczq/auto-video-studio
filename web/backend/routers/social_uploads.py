import threading

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from routers.auth import verify_token
from routers.social_shared import run_or_500
from services import social_service
from services.social_cover import generate_text_cover as _generate_text_cover


router = APIRouter()


class UploadVideoRequest(BaseModel):
    job_id: str
    account_id: str
    platform: str
    video_path: str
    title: str
    desc: str = ""
    tags: str = ""
    thumbnail: str = ""
    publish_mode: str = ""
    schedule: str = ""
    tid: str = ""


class BatchUploadVideoRequest(BaseModel):
    job_id: str
    account_ids: list[str]
    video_path: str
    title: str
    desc: str = ""
    tags: str = ""
    thumbnail: str = ""
    publish_mode: str = ""
    schedule: str = ""
    tid: str = ""


class UploadJobVideoRequest(BaseModel):
    account_id: str
    video_path: str
    title: str
    desc: str = ""
    tags: str = ""
    thumbnail: str = ""
    publish_mode: str = ""
    schedule: str = ""
    tid: str = ""


class GenerateCoverRequest(BaseModel):
    video_path: str
    timestamp: str
    title: str = ""
    font_size: str = "medium"
    font_color: str = "#ffffff"


class GenerateTextCoverRequest(BaseModel):
    thumbnail: str
    text: str
    font_size: str = "medium"
    font_color: str = "#ffffff"


def run_upload_sequence(job_id: str, req: BatchUploadVideoRequest, queued: list[dict]) -> None:
    for item in queued:
        account = item["account"]
        record = item["record"]
        platform_info = item["platform_info"]
        cli_name = platform_info.get("cli_name") if platform_info else None
        try:
            social_service.update_upload_record(
                record["id"],
                {
                    "status": "running",
                    "success": 0,
                    "error": "",
                    "output": "",
                },
            )
            social_service.upload_video(
                job_id,
                account["id"],
                req.video_path,
                req.title,
                req.desc if platform_info.get("need_desc") is not False else "",
                req.tags if platform_info.get("need_tags") is not False else "",
                req.publish_mode,
                req.schedule if platform_info.get("need_schedule") is not False else "",
                req.tid if platform_info.get("need_tid") else "",
                cli_name,
                record["id"],
                req.thumbnail,
            )
        except Exception as exc:
            social_service.update_upload_record(
                record["id"],
                {
                    "success": False,
                    "status": "failed",
                    "error": str(exc),
                    "output": "",
                },
            )


@router.post("/upload")
async def upload_video(
    req: UploadVideoRequest,
    _: bool = Depends(verify_token),
    background_tasks: BackgroundTasks = None,
):
    platform_info = social_service.get_platform_info(req.platform)
    cli_name = platform_info.get("cli_name") if platform_info else None

    if not platform_info or (not platform_info.get("support_cli") and not platform_info.get("support_web_bridge")):
        raise HTTPException(
            status_code=400, detail=f"平台 {req.platform} 暂不支持 Web 发布"
        )

    if background_tasks:
        record = social_service.add_upload_record(
            job_id=req.job_id,
            platform=req.platform,
            account_id=req.account_id,
            title=req.title,
            video_path=req.video_path,
            success=False,
            desc=req.desc,
            tags=req.tags,
            status="running",
        )
        background_tasks.add_task(
            social_service.upload_video,
            req.job_id,
            req.account_id,
            req.video_path,
            req.title,
            req.desc,
            req.tags,
            req.publish_mode,
            req.schedule,
            req.tid,
            cli_name,
            record["id"],
            req.thumbnail,
        )
        return {"status": "queued", "job_id": req.job_id, "account_id": req.account_id, "record_id": record["id"]}

    try:
        result = social_service.upload_video(
            req.job_id,
            req.account_id,
            req.video_path,
            req.title,
            req.desc,
            req.tags,
            req.publish_mode,
            req.schedule,
            req.tid,
            cli_name,
            thumbnail=req.thumbnail,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload/batch")
async def upload_video_batch(
    req: BatchUploadVideoRequest,
    _: bool = Depends(verify_token),
):
    account_ids = list(dict.fromkeys(account_id for account_id in req.account_ids if account_id))
    if not account_ids:
        raise HTTPException(status_code=400, detail="请选择至少一个发布账号")

    queued = []
    for account_id in account_ids:
        account = social_service.get_account(account_id)
        if not account:
            raise HTTPException(status_code=404, detail=f"账号不存在: {account_id}")

        platform_info = social_service.get_platform_info(account["platform"])
        if not platform_info or (
            not platform_info.get("support_cli")
            and not platform_info.get("support_web_bridge")
        ):
            raise HTTPException(
                status_code=400,
                detail=f"平台 {account['platform']} 暂不支持 Web 发布",
            )

        record = social_service.add_upload_record(
            job_id=req.job_id,
            platform=account["platform"],
            account_id=account_id,
            title=req.title,
            video_path=req.video_path,
            success=False,
            desc=req.desc if platform_info.get("need_desc") is not False else "",
            tags=req.tags if platform_info.get("need_tags") is not False else "",
            status="queued",
        )
        queued.append(
            {
                "account": account,
                "platform_info": platform_info,
                "record": record,
            }
        )

    thread = threading.Thread(
        target=run_upload_sequence,
        args=(req.job_id, req, queued),
        daemon=True,
    )
    thread.start()
    return {
        "status": "queued",
        "job_id": req.job_id,
        "count": len(queued),
        "records": [
            {
                "account_id": item["account"]["id"],
                "platform": item["account"]["platform"],
                "record_id": item["record"]["id"],
            }
            for item in queued
        ],
    }


class PreviewUploadRequest(BaseModel):
    account_id: str
    video_path: str
    title: str
    desc: str = ""
    tags: str = ""
    thumbnail: str = ""
    tid: str = ""


@router.post("/upload/preview")
async def preview_upload_video(
    job_id: str,
    req: PreviewUploadRequest,
    _: bool = Depends(verify_token),
    background_tasks: BackgroundTasks = None,
):
    """预上传视频：上传到平台但不发布/不上线，方便用户检查效果后再手动发布"""
    account = social_service.get_account(req.account_id)
    if not account:
        raise HTTPException(status_code=404, detail=f"账号不存在: {req.account_id}")

    platform_info = social_service.get_platform_info(account["platform"])
    if not platform_info or (
        not platform_info.get("support_cli") and not platform_info.get("support_web_bridge")
    ):
        raise HTTPException(
            status_code=400,
            detail=f"平台 {account['platform']} 暂不支持 Web 发布",
        )

    # 记录草稿上传
    record = social_service.add_upload_record(
        job_id=job_id,
        platform=account["platform"],
        account_id=req.account_id,
        title=req.title,
        video_path=req.video_path,
        success=False,
        desc=req.desc if platform_info.get("need_desc") is not False else "",
        tags=req.tags if platform_info.get("need_tags") is not False else "",
        status="running",
    )

    def run_preview_upload():
        try:
            # 使用 preview 模式上传：停在发布确认页面，等待用户手动发布
            result = social_service.upload_video(
                job_id,
                req.account_id,
                req.video_path,
                req.title,
                req.desc if platform_info.get("need_desc") is not False else "",
                req.tags if platform_info.get("need_tags") is not False else "",
                "",  # 不需要发布模式
                "",  # 不需要定时
                req.tid if platform_info.get("need_tid") else "",
                platform_info.get("cli_name"),
                record["id"],
                req.thumbnail,
                True,  # preview=True
            )
            # 预览模式下更新状态为 preview，不算真正发布
            social_service.update_upload_record(
                record["id"],
                {
                    "success": 0,
                    "status": "preview",
                    "output": result.get("output", ""),
                    "error": result.get("error", ""),
                },
            )
        except Exception as exc:
            social_service.update_upload_record(
                record["id"],
                {
                    "success": 0,
                    "status": "failed",
                    "error": str(exc),
                    "output": "",
                },
            )

    if background_tasks:
        background_tasks.add_task(run_preview_upload)
        return {
            "status": "queued",
            "job_id": job_id,
            "account_id": req.account_id,
            "platform": account["platform"],
            "record_id": record["id"],
            "message": "预览上传任务已提交，浏览器将打开发布页面，请检查后手动点击发布按钮",
        }

    run_preview_upload()
    return {
        "status": "completed",
        "job_id": job_id,
        "account_id": req.account_id,
        "platform": account["platform"],
        "record_id": record["id"],
        "message": "预览上传完成，请在浏览器中检查并手动发布",
    }


@router.post("/jobs/{job_id}/cover-frame")
async def generate_cover_frame(
    job_id: str,
    req: GenerateCoverRequest,
    _: bool = Depends(verify_token),
):
    try:
        return social_service.generate_cover_from_video(
            job_id,
            req.video_path,
            req.timestamp,
            req.title or None,
            req.font_size,
            req.font_color,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/jobs/{job_id}/cover-file")
async def upload_cover_file(
    job_id: str,
    file: UploadFile = File(...),
    _: bool = Depends(verify_token),
):
    try:
        content = await file.read()
        return social_service.save_uploaded_cover(
            job_id,
            file.filename or "cover",
            content,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/jobs/{job_id}/cover-text")
async def generate_text_cover_api(
    job_id: str,
    req: GenerateTextCoverRequest,
    _: bool = Depends(verify_token),
):
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"[DEBUG] cover-text called: job_id={job_id}, thumbnail={req.thumbnail!r}")
    try:
        result = _generate_text_cover(
            job_id,
            req.thumbnail,
            req.text,
            req.font_size,
            req.font_color,
        )
        logger.warning(f"[DEBUG] cover-text success: {result}")
        return result
    except Exception as e:
        logger.error(f"[DEBUG] cover-text error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/jobs/{job_id}/upload")
async def upload_job_video(
    job_id: str,
    req: UploadJobVideoRequest,
    _: bool = Depends(verify_token),
    background_tasks: BackgroundTasks = None,
):
    account = social_service.get_account(req.account_id)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    platform_info = social_service.get_platform_info(account["platform"])
    cli_name = platform_info.get("cli_name") if platform_info else None

    if not platform_info or (not platform_info.get("support_cli") and not platform_info.get("support_web_bridge")):
        raise HTTPException(
            status_code=400, detail=f"平台 {account['platform']} 暂不支持 Web 发布"
        )

    if background_tasks:
        record = social_service.add_upload_record(
            job_id=job_id,
            platform=account["platform"],
            account_id=req.account_id,
            title=req.title,
            video_path=req.video_path,
            success=False,
            desc=req.desc,
            tags=req.tags,
            status="running",
        )
        background_tasks.add_task(
            social_service.upload_video,
            job_id,
            req.account_id,
            req.video_path,
            req.title,
            req.desc,
            req.tags,
            req.publish_mode,
            req.schedule,
            req.tid,
            cli_name,
            record["id"],
            req.thumbnail,
        )
        return {"status": "queued", "job_id": job_id, "account_id": req.account_id, "record_id": record["id"]}

    try:
        result = social_service.upload_video(
            job_id,
            req.account_id,
            req.video_path,
            req.title,
            req.desc,
            req.tags,
            req.publish_mode,
            req.schedule,
            req.tid,
            cli_name,
            thumbnail=req.thumbnail,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{job_id}/upload-logs/{platform}")
async def get_upload_logs(job_id: str, platform: str, _: bool = Depends(verify_token)):
    return {"content": social_service.get_upload_log(job_id, platform)}


@router.get("/upload-records")
async def list_upload_records(
    platform: str = None,
    status: str = None,
    days: int = None,
    _: bool = Depends(verify_token),
):
    return social_service.get_upload_records(
        platform=platform, status=status, days=days
    )


@router.get("/jobs/{job_id}/upload-records")
async def list_job_upload_records(job_id: str, _: bool = Depends(verify_token)):
    return social_service.get_upload_records_for_job(job_id)


@router.get("/upload-records/{record_id}")
async def get_upload_record(record_id: str, _: bool = Depends(verify_token)):
    record = social_service.get_upload_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    job_id = record.get("job_id")
    platform = record.get("platform")
    log_content = ""
    if job_id and platform:
        log_content = social_service.get_upload_log(job_id, platform)
    return {**record, "log_content": log_content}


@router.put("/upload-records/{record_id}")
async def edit_upload_record(
    record_id: str,
    updates: dict,
    _: bool = Depends(verify_token),
):
    result = run_or_500(social_service.update_upload_record, record_id, updates)
    if result is None:
        raise HTTPException(status_code=404, detail="Record not found")
    return result


# ============== AI 封面图生成 API ==============

from pydantic import BaseModel


class GenerateAICoverRequest(BaseModel):
    title: str
    description: str = ""
    platforms: list[str] = ["gemini", "chatgpt"]
    interactive: bool = True  # 是否等待登录


class SelectAICoverRequest(BaseModel):
    filename: str


@router.post("/jobs/{job_id}/ai-cover/generate")
async def generate_ai_cover(
    job_id: str,
    req: GenerateAICoverRequest,
    _: bool = Depends(verify_token),
):
    """
    AI 生成封面图
    - 打开浏览器访问 Gemini/ChatGPT
    - 使用 AI 生成封面图
    - 返回生成的图片列表
    """
    import logging
    logger = logging.getLogger(__name__)
    try:
        from services.social_ai_cover import generate_ai_cover as _generate_ai_cover
        result = _generate_ai_cover(
            job_id=job_id,
            title=req.title,
            description=req.description,
            platforms=req.platforms,
        )
        return result
    except Exception as e:
        logger.error(f"[AI Cover] generate failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/jobs/{job_id}/ai-cover/images")
async def list_ai_cover_images(
    job_id: str,
    _: bool = Depends(verify_token),
):
    """列出当前任务的 AI 封面图"""
    from services.social_ai_cover import list_ai_cover_images as _list_images
    return _list_images(job_id)


@router.post("/jobs/{job_id}/ai-cover/select")
async def select_ai_cover(
    job_id: str,
    req: SelectAICoverRequest,
    _: bool = Depends(verify_token),
):
    """
    选择 AI 封面图
    - 将选中的图片复制为 publish_cover.jpg
    - 更新草稿中的 thumbnail 字段
    """
    from services.social_ai_cover import select_ai_cover as _select_cover
    try:
        result = _select_cover(job_id, req.filename)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/jobs/{job_id}/ai-cover/download/{filename}")
async def download_ai_cover_image(
    job_id: str,
    filename: str,
    _: bool = Depends(verify_token),
):
    """下载 AI 封面图"""
    from fastapi.responses import FileResponse
    from services.job_store import get_job_dir

    job_dir = get_job_dir(job_id).resolve()
    ai_covers_dir = job_dir / "ai_covers"
    file_path = (ai_covers_dir / filename).resolve()

    # 安全检查：确保文件在 ai_covers 目录内
    if not file_path.is_relative_to(ai_covers_dir):
        raise HTTPException(status_code=403, detail="Invalid file path")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(file_path)


# ============== nodriver 版本 AI 封面图生成 API ==============

@router.post("/jobs/{job_id}/ai-cover/generate-nodriver")
async def generate_ai_cover_nodriver(
    job_id: str,
    req: GenerateAICoverRequest,
    _: bool = Depends(verify_token),
):
    """
    使用 nodriver 生成 AI 封面图
    - nodriver 直接控制 Chrome，不易被检测
    - 可以复用 Chrome 的登录状态
    """
    import logging
    logger = logging.getLogger(__name__)
    try:
        from services.social_ai_cover_nodriver import generate_ai_cover_nodriver as _generate_nodriver
        result = _generate_nodriver(
            job_id=job_id,
            title=req.title,
            description=req.description,
            platforms=req.platforms,
        )
        return result
    except Exception as e:
        logger.error(f"[nodriver] generate failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# ============== Playwright 版本 AI 封面图生成 API ==============

@router.post("/jobs/{job_id}/ai-cover/generate-playwright")
async def generate_ai_cover_playwright(
    job_id: str,
    req: GenerateAICoverRequest,
    _: bool = Depends(verify_token),
):
    """
    使用 Playwright 生成 AI 封面图
    - Playwright 是成熟的浏览器自动化框架
    - 更稳定的元素查找和点击
    - 复用 nodriver 的 profile 登录状态
    """
    import logging
    logger = logging.getLogger(__name__)
    try:
        from services.social_ai_cover_playwright import generate_ai_cover_playwright as _generate_playwright
        result = await _generate_playwright(
            job_id=job_id,
            title=req.title,
            description=req.description,
            platforms=req.platforms,
        )
        return result
    except Exception as e:
        logger.error(f"[playwright] generate failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
