from __future__ import annotations

import logging
import html

from fastapi import APIRouter, Depends, HTTPException, Query, status
from app.api.deps import (
    get_current_user,
    get_email_service,
    get_scheduler,
    get_settings_service,
)
from app.core.config import get_settings
from app.schemas.settings import (
    DigestSettingsResponse,
    DigestSettingsUpdateRequest,
    FeedbackItem,
    FeedbackSubmitRequest,
    FeedbackSubmitResponse,
    KeywordsListResponse,
    KeywordsListRequest,
)
from app.services.auth_service import UserIdentity
from app.services.email_service import EmailService
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/me", response_model=DigestSettingsResponse)
async def get_my_settings(
    user: UserIdentity = Depends(get_current_user),
    settings_service: SettingsService = Depends(get_settings_service),
) -> DigestSettingsResponse:
    try:
        return await settings_service.get_user_settings(user.id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.put("/me", response_model=DigestSettingsResponse)
async def update_my_settings(
    payload: DigestSettingsUpdateRequest,
    user: UserIdentity = Depends(get_current_user),
    settings_service: SettingsService = Depends(get_settings_service),
    scheduler=Depends(get_scheduler),
) -> DigestSettingsResponse:

    logger.info("update user settings start user_id=%s payload=%s", user.id, payload)
    try:
        result = await settings_service.update_user_settings(user.id, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    await scheduler.refresh_user(user.id)
    return result


@router.post("/auto_generate_keywords_list", response_model=KeywordsListResponse)
async def get_my_keywords_list(
    payload: KeywordsListRequest,
    user: UserIdentity = Depends(get_current_user),
    settings_service: SettingsService = Depends(get_settings_service),
) -> KeywordsListResponse:

    logger.info(
        "auto generate keywords start user_id=%s query=%s",
        user.id,
        payload.user_query,
    )
    try:
        result = await settings_service.generate_keywords_list_by_user_query(
            user_query=payload.user_query
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return result


@router.post("/feedback", response_model=FeedbackSubmitResponse)
async def submit_feedback(
    payload: FeedbackSubmitRequest,
    user: UserIdentity = Depends(get_current_user),
    settings_service: SettingsService = Depends(get_settings_service),
    email_service: EmailService = Depends(get_email_service),
) -> FeedbackSubmitResponse:
    content = str(payload.content or "").strip()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="反馈内容不能为空"
        )

    settings = get_settings()
    sender = settings_service.shared_sender_email()
    if not sender:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="系统发件邮箱未配置，暂时无法接收反馈",
        )

    smtp_cfg = {
        "smtp_host": str(settings.verify_smtp_host or "").strip(),
        "smtp_port": int(settings.verify_smtp_port or 587),
        "use_tls": bool(settings.verify_smtp_use_tls),
        "use_ssl": bool(settings.verify_smtp_use_ssl),
        "username": str(settings.verify_smtp_username or "").strip(),
        "password": str(settings.verify_smtp_password or ""),
        "from": sender,
        "timeout_s": int(settings.verify_smtp_timeout_seconds or 30),
    }

    subject = f"[Paper Digest 用户反馈] {user.username} ({user.email})"
    text_body = (
        "收到一条用户反馈：\n\n"
        f"用户ID：{user.id}\n"
        f"用户名：{user.username}\n"
        f"用户邮箱：{user.email}\n\n"
        "反馈内容：\n"
        f"{content}\n"
    )
    html_body = (
        "<html><body style='font-family:Arial,sans-serif;color:#1f2329;'>"
        "<h3 style='margin:0 0 12px;'>收到新的用户反馈</h3>"
        f"<p><b>用户ID：</b>{user.id}</p>"
        f"<p><b>用户名：</b>{html.escape(user.username)}</p>"
        f"<p><b>用户邮箱：</b>{html.escape(user.email)}</p>"
        "<p><b>反馈内容：</b></p>"
        f"<div style='white-space:pre-wrap;padding:10px 12px;border:1px solid #f2d3d9;border-radius:10px;background:#fff7f8;'>{html.escape(content)}</div>"
        "</body></html>"
    )

    email_sent = False
    email_error = ""
    try:
        await email_service.send_email(
            smtp_cfg=smtp_cfg,
            to_emails=[sender],
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )
        email_sent = True
    except Exception as exc:
        email_error = str(exc)
        logger.warning(
            "submit feedback email failed user_id=%s error=%s", user.id, email_error
        )

    item = await settings_service.add_user_feedback(
        user_id=user.id,
        username=user.username,
        user_email=user.email,
        content=content,
        email_sent=email_sent,
        email_error=email_error,
    )
    if not email_sent:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="反馈已记录，但发送到管理员邮箱失败，请稍后重试",
        )

    return FeedbackSubmitResponse(
        message="反馈已提交，感谢你的建议！",
        item=FeedbackItem(**item),
    )


@router.get("/feedback", response_model=list[FeedbackItem])
async def list_feedback(
    limit: int = Query(default=20, ge=1, le=100),
    user: UserIdentity = Depends(get_current_user),
    settings_service: SettingsService = Depends(get_settings_service),
) -> list[FeedbackItem]:
    rows = await settings_service.list_user_feedback(user.id, limit=limit)
    return [FeedbackItem(**row) for row in rows]
