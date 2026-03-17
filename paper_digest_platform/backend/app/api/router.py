from fastapi import APIRouter

from app.api.routes_auth import router as auth_router
from app.api.routes_push import router as push_router
from app.api.routes_settings import router as settings_router


api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(settings_router)
api_router.include_router(push_router)

