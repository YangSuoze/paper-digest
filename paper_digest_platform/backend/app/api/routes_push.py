from __future__ import annotations
import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status

from app.api.deps import get_current_user, get_dispatch_service
from app.schemas.push import (
    DispatchLogItem,
    PaperRecordItem,
    RunNowRequest,
    TestEmailRequest,
    TriggerResponse,
)
from app.services.auth_service import UserIdentity
from app.services.digest_service import DigestDispatchService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/push", tags=["push"])


@router.post("/test-email", response_model=TriggerResponse)
async def send_test_email(
    payload: TestEmailRequest,
    user: UserIdentity = Depends(get_current_user),
    dispatch_service: DigestDispatchService = Depends(get_dispatch_service),
) -> TriggerResponse:
    try:
        message = await dispatch_service.send_test_email(
            user.id, to_email=payload.to_email
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return TriggerResponse(message=message, run_type="manual_test")


@router.post("/run-now", response_model=TriggerResponse)
async def run_digest_now(
    payload: RunNowRequest = Body(default_factory=RunNowRequest),
    user: UserIdentity = Depends(get_current_user),
    dispatch_service: DigestDispatchService = Depends(get_dispatch_service),
) -> TriggerResponse:
    try:
        logger.info(
            "run digest now start user_id=%s keywords_list=%s",
            user.id,
            payload.keywords_list,
        )
        message = await dispatch_service.trigger_user_digest(
            user.id,
            run_type="manual_digest",
            force_send=True,
            keywords_list=payload.keywords_list,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return TriggerResponse(message=message, run_type="manual_digest")


@router.get("/logs", response_model=list[DispatchLogItem])
async def get_dispatch_logs(
    limit: int = Query(default=20, ge=1, le=100),
    user: UserIdentity = Depends(get_current_user),
    dispatch_service: DigestDispatchService = Depends(get_dispatch_service),
) -> list[DispatchLogItem]:
    rows = await dispatch_service.list_user_logs(user.id, limit=limit)
    return [DispatchLogItem(**row) for row in rows]


@router.get("/papers", response_model=list[PaperRecordItem])
async def get_paper_records(
    limit: int = Query(default=20, ge=1, le=100),
    user: UserIdentity = Depends(get_current_user),
    dispatch_service: DigestDispatchService = Depends(get_dispatch_service),
) -> list[PaperRecordItem]:
    rows = await dispatch_service.list_user_papers(user.id, limit=limit)
    return [PaperRecordItem(**row) for row in rows]
