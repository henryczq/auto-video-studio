from fastapi import APIRouter

from routers import social_accounts, social_qr, social_uploads


router = APIRouter(prefix="/api/social", tags=["social"])
router.include_router(social_accounts.router)
router.include_router(social_uploads.router)
router.include_router(social_qr.router)
