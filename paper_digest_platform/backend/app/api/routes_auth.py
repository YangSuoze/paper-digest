from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import get_auth_service, get_current_user
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    MessageResponse,
    PasswordResetCodeRequest,
    PasswordResetConfirmRequest,
    RegisterCodeRequest,
    RegisterConfirmRequest,
    UserProfile,
)
from app.services.auth_service import AuthService, UserIdentity


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register/request-code", response_model=MessageResponse)
async def request_register_code(
    payload: RegisterCodeRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> MessageResponse:
    try:
        await auth_service.request_register_code(payload.email)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"验证码发送失败，请检查系统 SMTP 配置或网络：{exc}",
        ) from exc
    return MessageResponse(message="验证码已发送，请查收邮箱")


@router.post("/register/confirm", response_model=MessageResponse)
async def confirm_register(
    payload: RegisterConfirmRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> MessageResponse:
    try:
        await auth_service.confirm_register(
            email=payload.email,
            username=payload.username,
            password=payload.password,
            code=payload.code,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return MessageResponse(message="注册成功，请登录")


@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    payload: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> LoginResponse:
    try:
        return await auth_service.login(
            username=payload.username,
            password=payload.password,
            user_agent=request.headers.get("User-Agent", ""),
            ip_address=request.client.host if request.client else "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    user: UserIdentity = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> MessageResponse:
    authorization = request.headers.get("Authorization", "")
    token = authorization.replace("Bearer", "", 1).strip()
    if token:
        await auth_service.logout(token)
    return MessageResponse(message=f"已退出登录：{user.username}")


@router.get("/me", response_model=UserProfile)
async def get_me(user: UserIdentity = Depends(get_current_user)) -> UserProfile:
    return UserProfile(id=user.id, username=user.username, email=user.email)


@router.post("/password/request-code", response_model=MessageResponse)
async def request_reset_code(
    payload: PasswordResetCodeRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> MessageResponse:
    try:
        await auth_service.request_reset_code(payload.email)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"验证码发送失败，请检查系统 SMTP 配置或网络：{exc}",
        ) from exc
    return MessageResponse(message="如果邮箱已注册，验证码已发送")


@router.post("/password/reset", response_model=MessageResponse)
async def reset_password(
    payload: PasswordResetConfirmRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> MessageResponse:
    try:
        await auth_service.reset_password(
            email=payload.email,
            code=payload.code,
            new_password=payload.new_password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return MessageResponse(message="密码已更新，请重新登录")
