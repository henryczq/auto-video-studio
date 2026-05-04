from fastapi import APIRouter, HTTPException, Depends

from routers.auth import verify_token
from services.ai_config import load_ai_config, save_ai_config
from services.ai_logging import list_ai_logs, load_ai_log
from services.ai_testing import test_ai_model

router = APIRouter(prefix="/api", tags=["ai"])


@router.get("/ai-config")
async def get_ai_config(_: bool = Depends(verify_token)):
    return load_ai_config()


@router.post("/ai-config")
async def post_ai_config(config: dict, _: bool = Depends(verify_token)):
    try:
        return save_ai_config(config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/ai-config")
async def put_ai_config(config: dict, _: bool = Depends(verify_token)):
    try:
        current = load_ai_config()
        merged = {**current, **config}
        if "models" not in config:
            merged["models"] = current.get("models") or []
        return save_ai_config(merged)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai-config/test")
async def test_ai(model: dict, _: bool = Depends(verify_token)):
    try:
        return test_ai_model(model)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ai-logs")
async def get_ai_logs(limit: int = 100, _: bool = Depends(verify_token)):
    return list_ai_logs(limit=limit)


@router.get("/ai-config/logs")
async def get_ai_config_logs(limit: int = 100, _: bool = Depends(verify_token)):
    return list_ai_logs(limit=limit)


@router.get("/ai-logs/{log_id}")
async def get_ai_log(log_id: str, _: bool = Depends(verify_token)):
    try:
        return load_ai_log(log_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="AI log not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ai-config/logs/{log_id}")
async def get_ai_config_log(log_id: str, _: bool = Depends(verify_token)):
    try:
        return load_ai_log(log_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="AI log not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
