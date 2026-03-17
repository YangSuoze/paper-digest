from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logger import setup_logging
from app.core.scheduler import UserScheduler
from app.db.database import init_db
from app.services.auth_service import AuthService
from app.services.digest_service import DigestDispatchService
from app.services.email_service import EmailService
from app.services.settings_service import SettingsService


settings = get_settings()
setup_logging(settings)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("backend starting, env=%s", settings.app_env)
    await init_db()
    logger.info("database initialized: %s", settings.db_file)

    settings_service = SettingsService()
    email_service = EmailService()
    auth_service = AuthService(email_service=email_service, settings_service=settings_service)
    dispatch_service = DigestDispatchService(settings_service=settings_service, email_service=email_service)
    user_scheduler = UserScheduler(dispatch_service=dispatch_service, settings_service=settings_service)

    app.state.settings = settings
    app.state.settings_service = settings_service
    app.state.email_service = email_service
    app.state.auth_service = auth_service
    app.state.dispatch_service = dispatch_service
    app.state.user_scheduler = user_scheduler

    await user_scheduler.start()
    logger.info("scheduler started")
    try:
        yield
    finally:
        await user_scheduler.stop()
        logger.info("scheduler stopped")
        logger.info("backend stopped")


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_prefix)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start_ts = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - start_ts) * 1000
        logger.exception(
            "request failed method=%s path=%s elapsed_ms=%.2f",
            request.method,
            request.url.path,
            elapsed_ms,
        )
        raise

    elapsed_ms = (time.perf_counter() - start_ts) * 1000
    logger.info(
        "request method=%s path=%s status=%s elapsed_ms=%.2f",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response

frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
frontend_dist_dir = frontend_dir / "dist"
frontend_assets_dir = frontend_dist_dir / "assets"
if frontend_assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=frontend_assets_dir), name="assets")


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def index():
    index_file = frontend_dist_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return JSONResponse(
        {"message": "frontend build not found, run `npm run build` in paper_digest_platform/frontend"},
        status_code=404,
    )
