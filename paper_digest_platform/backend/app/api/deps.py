from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request, status

from app.services.auth_service import AuthService, UserIdentity
from app.services.digest_service import DigestDispatchService
from app.services.email_service import EmailService
from app.services.settings_service import SettingsService


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


def get_settings_service(request: Request) -> SettingsService:
    return request.app.state.settings_service


def get_dispatch_service(request: Request) -> DigestDispatchService:
    return request.app.state.dispatch_service


def get_email_service(request: Request) -> EmailService:
    return request.app.state.email_service


def get_scheduler(request: Request):
    return request.app.state.user_scheduler


async def get_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserIdentity:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效 token")
    token = authorization[len(prefix) :].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效 token")
    try:
        return await auth_service.get_user_by_token(token)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
