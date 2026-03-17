from __future__ import annotations

import logging
import os
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import get_settings
from app.services.digest_service import DigestDispatchService
from app.services.settings_service import SettingsService


logger = logging.getLogger(__name__)


class UserScheduler:
    def __init__(
        self,
        *,
        dispatch_service: DigestDispatchService,
        settings_service: SettingsService,
    ) -> None:
        self._settings = get_settings()
        self._dispatch_service = dispatch_service
        self._settings_service = settings_service
        self._scheduler = AsyncIOScheduler(
            job_defaults={"coalesce": True, "max_instances": 1}
        )
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._scheduler.start()
        self._started = True
        logger.info("user scheduler started pid=%s", os.getpid())
        await self.refresh_all()

    async def stop(self) -> None:
        if not self._started:
            return
        self._scheduler.shutdown(wait=False)
        self._started = False
        logger.info("user scheduler shutdown")

    async def refresh_all(self) -> None:
        removed = 0
        for job in self._scheduler.get_jobs():
            if job.id.startswith("user-digest-"):
                self._scheduler.remove_job(job.id)
                removed += 1

        schedules = await self._settings_service.list_active_schedules()
        scheduled = 0
        for row in schedules:
            self._schedule_user(
                user_id=int(row["user_id"]),
                daily_send_time=str(
                    row.get("daily_send_time") or self._settings.default_daily_time
                ),
                timezone_name=str(
                    row.get("timezone") or self._settings.default_timezone
                ),
            )
            scheduled += 1
        logger.info("scheduler refreshed, removed=%s scheduled=%s", removed, scheduled)

    async def refresh_user(self, user_id: int) -> None:
        self.remove_user(user_id)
        profile = await self._settings_service.get_user_dispatch_profile(user_id)
        if not bool(profile.get("active", 1)):
            logger.info("user schedule disabled, user_id=%s", user_id)
            return
        self._schedule_user(
            user_id=user_id,
            daily_send_time=str(
                profile.get("daily_send_time") or self._settings.default_daily_time
            ),
            timezone_name=str(
                profile.get("timezone") or self._settings.default_timezone
            ),
        )
        logger.info("user schedule refreshed, user_id=%s", user_id)

    def remove_user(self, user_id: int) -> None:
        job_id = self._job_id(user_id)
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
            logger.info("user schedule removed, user_id=%s", user_id)

    def _schedule_user(
        self, *, user_id: int, daily_send_time: str, timezone_name: str
    ) -> None:
        hour, minute = self._parse_time(daily_send_time)
        timezone = self._safe_timezone(timezone_name)
        trigger = CronTrigger(hour=hour, minute=minute, timezone=timezone)
        self._scheduler.add_job(
            self._dispatch_job,
            trigger=trigger,
            args=[user_id],
            id=self._job_id(user_id),
            replace_existing=True,
            misfire_grace_time=1800,
        )
        logger.info(
            "scheduled user job, user_id=%s time=%02d:%02d timezone=%s",
            user_id,
            hour,
            minute,
            timezone.key,
        )

    async def _dispatch_job(self, user_id: int) -> None:
        await self._run_dispatch(user_id)

    async def _run_dispatch(self, user_id: int) -> None:
        logger.info("scheduled dispatch started, user_id=%s pid=%s", user_id, os.getpid())
        try:
            await self._dispatch_service.trigger_user_digest(
                user_id, run_type="scheduled", force_send=False
            )
            logger.info("scheduled dispatch finished, user_id=%s", user_id)
        except Exception as exc:
            logger.warning(
                "scheduled dispatch failed, user_id=%s error=%s", user_id, exc
            )

    def _safe_timezone(self, name: str) -> ZoneInfo:
        try:
            return ZoneInfo(name)
        except Exception:
            return ZoneInfo(self._settings.default_timezone)

    def _parse_time(self, value: str) -> tuple[int, int]:
        parts = value.split(":")
        if len(parts) != 2:
            return (9, 30)
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except Exception:
            return (9, 30)
        hour = min(max(0, hour), 23)
        minute = min(max(0, minute), 59)
        return (hour, minute)

    @staticmethod
    def _job_id(user_id: int) -> str:
        return f"user-digest-{user_id}"
