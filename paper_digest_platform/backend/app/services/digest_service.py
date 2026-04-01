from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import tempfile
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.email_service import EmailService
from app.services.settings_service import SettingsService


logger = logging.getLogger(__name__)


class DigestDispatchService:
    def __init__(
        self, *, settings_service: SettingsService, email_service: EmailService
    ) -> None:
        self._settings = get_settings()
        self._settings_service = settings_service
        self._email_service = email_service
        self._semaphore = asyncio.Semaphore(
            max(1, int(self._settings.dispatch_max_concurrency))
        )
        self._task_lock = threading.Lock()
        self._manual_tasks: dict[str, dict[str, Any]] = {}
        self._manual_task_keep_hours = 24
        self._manual_task_keep_max = 200

    async def trigger_user_digest(
        self,
        user_id: int,
        *,
        run_type: str,
        force_send: bool = False,
        keywords_list: list[list[str]] | None = None,
        progress_callback: Callable[[str, str], None] | None = None,
    ) -> str:
        self._emit_progress(progress_callback, "prepare", "读取推送配置中")
        logger.info(
            "digest trigger start user_id=%s run_type=%s force_send=%s keywords_list=%s",
            user_id,
            run_type,
            force_send,
            keywords_list,
        )
        profile = await self._settings_service.get_user_dispatch_profile(user_id)
        require_active = run_type == "scheduled"
        effective_keywords_list = self._effective_keywords_list(profile, keywords_list)
        logger.info(
            "digest trigger effective keywords user_id=%s groups=%s",
            user_id,
            effective_keywords_list,
        )

        self._validate_profile(
            profile,
            for_digest=True,
            require_active=require_active,
            keywords_list=effective_keywords_list,
        )

        runtime_config = await asyncio.to_thread(
            self._build_runtime_config,
            profile,
            force_send,
            effective_keywords_list,
            run_type,
        )

        state_snapshot = await self._settings_service.get_user_digest_state(user_id)
        history_before = await asyncio.to_thread(
            self._history_key_set_from_state, state_snapshot
        )
        history_row_count_before = await asyncio.to_thread(
            self._history_row_count_from_state, state_snapshot
        )
        try:
            async with self._semaphore:
                await asyncio.to_thread(
                    self._run_agent_with_runtime_config,
                    runtime_config,
                    effective_keywords_list,
                    state_snapshot,
                    user_search_intent=profile.get("user_search_intent", ""),
                    dispatch_run_type=run_type,
                    progress_callback=progress_callback,
                )
        except Exception as exc:
            message = f"推送失败：{exc}"
            self._emit_progress(progress_callback, "failed", message)
            logger.exception(
                "digest trigger failed user_id=%s run_type=%s", user_id, run_type
            )
            await self._settings_service.add_dispatch_log(
                user_id, run_type, "failed", message
            )
            raise RuntimeError(message) from exc

        await self._settings_service.save_user_digest_state(user_id, state_snapshot)
        new_records = await asyncio.to_thread(
            self._collect_new_history_records_from_state,
            state_snapshot,
            history_before,
        )
        history_row_count_after = await asyncio.to_thread(
            self._history_row_count_from_state, state_snapshot
        )
        pushed_count = max(0, history_row_count_after - history_row_count_before)
        inserted_count = await self._settings_service.add_paper_records(
            user_id, run_type, new_records
        )
        message = (
            f"推送成功；本次推送 {pushed_count} 篇，新增论文 {len(new_records)} 篇，入库 {inserted_count} 条"
        )
        logger.info(
            "digest trigger success user_id=%s run_type=%s pushed=%s new_records=%s inserted=%s",
            user_id,
            run_type,
            pushed_count,
            len(new_records),
            inserted_count,
        )
        await self._settings_service.add_dispatch_log(
            user_id, run_type, "success", message
        )
        self._emit_progress(progress_callback, "completed", message)
        return message

    async def submit_manual_digest_task(
        self,
        user_id: int,
        *,
        keywords_list: list[list[str]] | None = None,
    ) -> dict[str, Any]:
        profile = await self._settings_service.get_user_dispatch_profile(user_id)
        effective_keywords_list = self._effective_keywords_list(profile, keywords_list)
        self._validate_profile(
            profile,
            for_digest=True,
            require_active=False,
            keywords_list=effective_keywords_list,
        )

        now = self._now_iso()
        task_id = uuid.uuid4().hex
        task = {
            "task_id": task_id,
            "user_id": user_id,
            "run_type": "manual_digest",
            "status": "queued",
            "progress_stage": "queued",
            "progress_message": "任务已排队，等待执行",
            "result_message": "",
            "error_message": "",
            "created_at": now,
            "updated_at": now,
            "started_at": "",
            "finished_at": "",
        }
        with self._task_lock:
            self._manual_tasks[task_id] = task
            self._prune_manual_tasks_locked()

        logger.info(
            "manual digest task queued user_id=%s task_id=%s groups=%s",
            user_id,
            task_id,
            len(effective_keywords_list),
        )
        asyncio.create_task(
            self._run_manual_digest_task(
                task_id=task_id,
                user_id=user_id,
                keywords_list=effective_keywords_list,
            )
        )
        return task.copy()

    def get_manual_digest_task(
        self,
        *,
        user_id: int,
        task_id: str,
    ) -> dict[str, Any] | None:
        with self._task_lock:
            task = self._manual_tasks.get(task_id)
            if not task:
                return None
            if int(task.get("user_id") or 0) != int(user_id):
                return None
            return task.copy()

    async def _run_manual_digest_task(
        self,
        *,
        task_id: str,
        user_id: int,
        keywords_list: list[list[str]],
    ) -> None:
        started_at = self._now_iso()
        self._update_task(
            task_id,
            status="running",
            progress_stage="running",
            progress_message="任务启动，准备检索论文",
            started_at=started_at,
        )

        try:
            message = await self.trigger_user_digest(
                user_id,
                run_type="manual_digest",
                force_send=True,
                keywords_list=keywords_list,
                progress_callback=lambda stage, msg: self._set_task_progress(
                    task_id, stage, msg
                ),
            )
        except Exception as exc:
            error_message = str(exc)
            self._update_task(
                task_id,
                status="failed",
                progress_stage="failed",
                progress_message="执行失败",
                error_message=error_message,
                finished_at=self._now_iso(),
            )
            logger.warning(
                "manual digest task failed user_id=%s task_id=%s error=%s",
                user_id,
                task_id,
                error_message,
            )
            return

        self._update_task(
            task_id,
            status="success",
            progress_stage="completed",
            progress_message="执行完成",
            result_message=message,
            finished_at=self._now_iso(),
        )
        logger.info("manual digest task success user_id=%s task_id=%s", user_id, task_id)

    async def send_test_email(
        self, user_id: int, *, to_email: str | None = None
    ) -> str:
        logger.info("test email start user_id=%s", user_id)
        profile = await self._settings_service.get_user_dispatch_profile(user_id)
        self._validate_profile(profile, for_digest=False, require_active=False)
        recipient = (to_email or "").strip() or str(
            profile.get("target_email") or ""
        ).strip()
        if not recipient:
            raise ValueError("请先设置目标邮箱")
        smtp_cfg = self._shared_smtp_cfg()

        try:
            await self._email_service.send_test_email(
                smtp_cfg=smtp_cfg,
                to_email=recipient,
                username=str(profile.get("username") or ""),
            )
        except Exception as exc:
            message = f"测试邮件发送失败：{exc}"
            logger.exception(
                "test email failed user_id=%s recipient=%s", user_id, recipient
            )
            await self._settings_service.add_dispatch_log(
                user_id, "manual_test", "failed", message
            )
            raise RuntimeError(message) from exc

        message = f"测试邮件已发送到 {recipient}"
        logger.info("test email success user_id=%s recipient=%s", user_id, recipient)
        await self._settings_service.add_dispatch_log(
            user_id, "manual_test", "success", message
        )
        return message

    async def list_user_logs(
        self, user_id: int, limit: int = 20
    ) -> list[dict[str, Any]]:
        return await self._settings_service.list_dispatch_logs(user_id, limit=limit)

    async def list_user_papers(
        self, user_id: int, limit: int = 20
    ) -> list[dict[str, Any]]:
        return await self._settings_service.list_paper_records(user_id, limit=limit)

    def _validate_profile(
        self,
        profile: dict[str, Any],
        *,
        for_digest: bool,
        require_active: bool = True,
        keywords_list: list[list[str]] | None = None,
    ) -> None:
        if require_active and not bool(profile.get("active", 1)):
            raise ValueError("当前账户推送已停用")
        if not str(profile.get("target_email") or "").strip():
            raise ValueError("请先设置目标邮箱")
        shared = self._shared_smtp_cfg()
        missing = [
            label
            for key, label in {
                "smtp_host": "SMTP 主机",
                "username": "SMTP 用户名",
                "password": "SMTP 密码",
                "from": "发件邮箱",
            }.items()
            if not str(shared.get(key) or "").strip()
        ]
        if missing:
            raise ValueError("系统 SMTP 未配置完整：" + "、".join(missing))
        if for_digest:
            keywords_source = keywords_list
            if not keywords_source:
                raise ValueError("请先配置关键词")

    def _normalize_keyword_group(self, values: list[Any]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(text)
        return out

    def _parse_keyword_line(self, line: str) -> list[str]:
        text = str(line or "").strip()
        if not text:
            return []
        parts = re.split(r"\s*(?:&&|&|＆＆|＆|,|，|;|；)\s*", text)
        return self._normalize_keyword_group(parts)

    def _normalize_keywords_list(self, raw: Any) -> list[list[str]]:
        if not isinstance(raw, list):
            return []

        seen_groups: set[tuple[str, ...]] = set()
        out: list[list[str]] = []
        for item in raw:
            group: list[str]
            if isinstance(item, list):
                group = self._normalize_keyword_group(item)
            else:
                group = self._parse_keyword_line(str(item or ""))

            if not group:
                continue

            group_key = tuple(token.lower() for token in group)
            if group_key in seen_groups:
                continue
            seen_groups.add(group_key)
            out.append(group)
        return out

    def _effective_keywords_list(
        self,
        profile: dict[str, Any],
        keywords_override: list[list[str]] | None,
    ) -> list[list[str]]:
        if keywords_override is not None:
            cleaned = self._normalize_keywords_list(keywords_override)
            if cleaned:
                return cleaned

        profile_keywords_list = self._normalize_keywords_list(
            profile.get("keywords_list")
        )
        if profile_keywords_list:
            return profile_keywords_list

        legacy_keywords = self._normalize_keywords_list(profile.get("keywords") or [])
        if legacy_keywords:
            return legacy_keywords

        # 保留兼容：若 profile 里有 keywords_json（字符串），尝试兜底解析
        try:
            raw_json = profile.get("keywords_json")
            parsed = json.loads(raw_json) if isinstance(raw_json, str) else []
            parsed_keywords = self._normalize_keywords_list(parsed)
            if parsed_keywords:
                return parsed_keywords
        except Exception:
            pass

        # 返回空列表，让上层统一抛出“请先配置关键词”
        if not keywords_override:
            logger.warning(
                "empty keywords_list for user_id=%s profile_keys=%s",
                profile.get("user_id"),
                sorted(list(profile.keys())),
            )
        return []

    def _effective_keywords(
        self,
        profile: dict[str, Any],
        keywords_override: list[str] | None,
    ) -> list[str]:
        """保留旧接口：把一维关键词转换后返回扁平结果。"""
        source = (
            keywords_override
            if keywords_override is not None
            else (profile.get("keywords") or [])
        )
        cleaned = self._normalize_keyword_group([str(item) for item in source])
        if not cleaned:
            raise ValueError("请先配置关键词")
        return cleaned

    def _shared_smtp_cfg(self) -> dict[str, object]:
        return {
            "smtp_host": str(self._settings.verify_smtp_host or "").strip(),
            "smtp_port": int(self._settings.verify_smtp_port or 587),
            "use_tls": bool(self._settings.verify_smtp_use_tls),
            "use_ssl": bool(self._settings.verify_smtp_use_ssl),
            "username": str(self._settings.verify_smtp_username or "").strip(),
            "password": str(self._settings.verify_smtp_password or ""),
            "from": (
                str(self._settings.verify_smtp_from_email or "").strip()
                or str(self._settings.verify_smtp_username or "").strip()
            ),
            "timeout_s": int(self._settings.verify_smtp_timeout_seconds or 30),
        }

    def _build_runtime_config(
        self,
        profile: dict[str, Any],
        force_send: bool,
        keywords_list: list[list[str]],
        run_type: str,
    ) -> dict[str, Any]:
        shared = self._shared_smtp_cfg()
        normalized_run_type = str(run_type or "").strip().lower()
        days_back = 90 if normalized_run_type == "manual_digest" else 7
        logger.info(
            "build runtime config user_id=%s run_type=%s days_back=%s",
            profile.get("user_id"),
            normalized_run_type,
            days_back,
        )

        cfg: dict[str, Any] = {
            "search": {
                "days_back": days_back,
                "timeout_s": 30,
                "max_total_papers": 10,
                "max_results_per_keyword": 30,
                "keywords_list": keywords_list,
                "global_min_relevance": 0.2,
            },
            "sources": {
                "arxiv": {"enabled": True},
                "crossref": {"enabled": True, "mailto": ""},
                "pubmed": {
                    "enabled": True,
                    "rows": 30,
                    "email": "",
                    "api_key_env": "NCBI_API_KEY",
                },
                "ieee": {
                    "enabled": True,
                    "rows": 30,
                    "api_key_env": "IEEE_XPLORE_API_KEY",
                },
                "semantic_scholar": {
                    "enabled": True,
                    "api_key_env": "SEMANTIC_SCHOLAR_API_KEY",
                },
            },
            "llm": {
                "deployment": "ali",
                "model": "qwen-plus",
                "temperature": 0.2,
                "summary_style": "magazine",
                "max_summaries": 0,
            },
            "email": {
                "smtp_host": str(shared.get("smtp_host") or "").strip(),
                "smtp_port": int(shared.get("smtp_port") or 587),
                "use_tls": bool(shared.get("use_tls", True)),
                "use_ssl": bool(shared.get("use_ssl", False)),
                "username": str(shared.get("username") or "").strip(),
                "password": str(shared.get("password") or ""),
                "from": str(shared.get("from") or "").strip(),
                "to": [str(profile.get("target_email") or "").strip()],
            },
            "schedule": {
                "daily_weekdays": [1, 2, 3, 4, 5],
                "weekly_summary": {
                    "enabled": False,
                    "weekday": 7,
                    "lookback_days": 7,
                    "max_items": 120,
                },
            },
            "state": {
                "keep_days": 60,
                "history_keep_days": 180,
                "single_push_per_day": True,
            },
        }

        if force_send:
            cfg["schedule"]["daily_weekdays"] = [1, 2, 3, 4, 5, 6, 7]
            cfg["state"]["single_push_per_day"] = False

        return copy.deepcopy(cfg)

    def _run_agent_with_runtime_config(
        self,
        runtime_config: dict[str, Any],
        keywords_list: list[list[str]],
        state_snapshot: dict[str, Any],
        user_search_intent: str,
        dispatch_run_type: str,
        progress_callback: Callable[[str, str], None] | None = None,
    ) -> None:
        try:
            from app.paper_digest.runner import run_once
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "缺少运行依赖，请在 backend 目录执行 `pip install -r requirements.txt`"
            ) from exc

        tmp_config_path: Path | None = None
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            prefix="paper_digest_runtime_",
            encoding="utf-8",
            delete=False,
        ) as tmp:
            json.dump(runtime_config, tmp, ensure_ascii=False, indent=2)
            tmp_config_path = Path(tmp.name)

        try:
            run_once(
                str(tmp_config_path),
                dry_run=False,
                no_email=False,
                skip_llm=False,
                skip_semantic_scholar=False,
                run_mode="daily",
                keywords_list=keywords_list,
                state_override=state_snapshot,
                persist_state_to_file=False,
                user_search_intent=user_search_intent,
                dispatch_run_type=dispatch_run_type,
                progress_callback=progress_callback,
            )
        finally:
            if tmp_config_path and tmp_config_path.exists():
                tmp_config_path.unlink(missing_ok=True)

    def _emit_progress(
        self,
        progress_callback: Callable[[str, str], None] | None,
        stage: str,
        message: str,
    ) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(stage, message)
        except Exception:
            logger.debug("emit progress failed stage=%s", stage, exc_info=True)

    def _set_task_progress(self, task_id: str, stage: str, message: str) -> None:
        with self._task_lock:
            task = self._manual_tasks.get(task_id)
            if not task:
                return
            if str(task.get("status") or "") not in {"queued", "running"}:
                return
            task["progress_stage"] = str(stage or "").strip() or "running"
            task["progress_message"] = str(message or "").strip() or "任务执行中"
            task["updated_at"] = self._now_iso()

    def _update_task(self, task_id: str, **fields: Any) -> None:
        with self._task_lock:
            task = self._manual_tasks.get(task_id)
            if not task:
                return
            task.update(fields)
            task["updated_at"] = self._now_iso()

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    def _prune_manual_tasks_locked(self) -> None:
        now = datetime.now(timezone.utc)
        expire_before = now - timedelta(hours=max(1, self._manual_task_keep_hours))

        expired_ids: list[str] = []
        for task_id, task in self._manual_tasks.items():
            updated_at_raw = str(task.get("updated_at") or "").strip()
            try:
                updated_at = datetime.fromisoformat(updated_at_raw)
            except Exception:
                updated_at = now
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            if updated_at < expire_before:
                expired_ids.append(task_id)

        for task_id in expired_ids:
            self._manual_tasks.pop(task_id, None)

        if len(self._manual_tasks) <= self._manual_task_keep_max:
            return

        ordered = sorted(
            self._manual_tasks.items(),
            key=lambda item: str(item[1].get("updated_at") or ""),
            reverse=True,
        )
        keep_ids = {
            task_id for task_id, _ in ordered[: max(1, self._manual_task_keep_max)]
        }
        for task_id in list(self._manual_tasks.keys()):
            if task_id not in keep_ids:
                self._manual_tasks.pop(task_id, None)

    def _history_key_set_from_state(
        self, state: dict[str, Any]
    ) -> set[tuple[str, str]]:
        rows = self._load_state_history_rows(state)
        return {
            (str(row.get("uid") or "").strip(), str(row.get("push_date") or "").strip())
            for row in rows
            if str(row.get("uid") or "").strip()
            and str(row.get("push_date") or "").strip()
        }

    def _history_row_count_from_state(self, state: dict[str, Any]) -> int:
        return len(self._load_state_history_rows(state))

    def _collect_new_history_records_from_state(
        self,
        state: dict[str, Any],
        history_before: set[tuple[str, str]],
    ) -> list[dict[str, Any]]:
        rows = self._load_state_history_rows(state)
        fresh: list[dict[str, Any]] = []
        for row in rows:
            uid = str(row.get("uid") or "").strip()
            push_date = str(row.get("push_date") or "").strip()
            if not uid or not push_date:
                continue
            if (uid, push_date) in history_before:
                continue
            fresh.append(row)
        return fresh

    def _load_state_history_rows(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        history = (state or {}).get("push_history") or []
        if not isinstance(history, list):
            return []
        return [row for row in history if isinstance(row, dict)]
