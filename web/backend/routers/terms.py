from fastapi import APIRouter, Depends, HTTPException

from routers.auth import verify_token
from services.suggestions import load_terms, save_terms, add_term

router = APIRouter(prefix="/api/terms", tags=["terms"])


@router.get("")
async def get_terms(_: bool = Depends(verify_token)):
    return load_terms()


@router.post("")
async def save_all_terms(terms: dict, _: bool = Depends(verify_token)):
    try:
        save_terms(terms)
        return {"status": "saved", "terms_count": len(terms)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
