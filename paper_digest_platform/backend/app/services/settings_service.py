from __future__ import annotations

import json
import re
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings
from app.db.database import get_conn
from app.schemas.settings import (
    DigestSettingsResponse,
    DigestSettingsUpdateRequest,
    KeywordsListResponse,
)
from llm_tools import LLMClient

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean_keywords(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in values:
        clean = (item or "").strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def _normalize_keyword_group(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def _parse_keyword_line(line: str) -> list[str]:
    text = str(line or "").strip()
    if not text:
        return []
    parts = re.split(r"\s*(?:&&|&|＆＆|＆|,|，|;|；)\s*", text)
    return _normalize_keyword_group(parts)


def _normalize_keywords_list(raw: Any) -> list[list[str]]:
    if not isinstance(raw, list):
        return []

    seen_groups: set[tuple[str, ...]] = set()
    out: list[list[str]] = []
    for item in raw:
        group: list[str]
        if isinstance(item, list):
            group = _normalize_keyword_group(item)
        else:
            group = _parse_keyword_line(str(item or ""))

        if not group:
            continue

        group_key = tuple(token.lower() for token in group)
        if group_key in seen_groups:
            continue
        seen_groups.add(group_key)
        out.append(group)
    return out


def _flatten_keywords_list(keywords_list: list[list[str]]) -> list[str]:
    return [" && ".join(group) for group in keywords_list if group]


class SettingsService:
    def __init__(self) -> None:
        self._settings = get_settings()

    def shared_sender_email(self) -> str:
        return (
            str(self._settings.verify_smtp_from_email or "").strip()
            or str(self._settings.verify_smtp_username or "").strip()
        )

    def shared_smtp_ready(self) -> bool:
        sender = self.shared_sender_email()
        return bool(
            str(self._settings.verify_smtp_host or "").strip()
            and int(self._settings.verify_smtp_port or 0) > 0
            and str(self._settings.verify_smtp_username or "").strip()
            and str(self._settings.verify_smtp_password or "").strip()
            and sender
        )

    def default_keywords(self) -> list[list[str]]:
        return [
            ["cuffless blood pressure wearable sensor"],
            ["noninvasive glucose estimation wearable sensor"],
        ]

    async def create_default_settings(self, user_id: int, email: str) -> None:
        now = _now_iso()
        keywords = self.default_keywords()
        async with get_conn() as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO user_settings (
                  user_id, smtp_host, smtp_port, use_tls, use_ssl, smtp_username, smtp_password,
                  from_email, target_email, daily_send_time, timezone, keywords_json, active,
                  created_at, updated_at
                ) VALUES (?, '', 587, 1, 0, '', '', '', ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    user_id,
                    email,
                    self._settings.default_daily_time,
                    self._settings.default_timezone,
                    json.dumps(keywords, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            await conn.execute(
                """
                INSERT OR IGNORE INTO user_digest_state (user_id, state_json, created_at, updated_at)
                VALUES (?, '{}', ?, ?)
                """,
                (user_id, now, now),
            )

    async def get_user_settings(self, user_id: int) -> DigestSettingsResponse:
        row = await self.get_user_settings_row(user_id)
        return self._row_to_schema(row)

    async def get_user_settings_row(self, user_id: int) -> dict[str, Any]:
        user_email = ""
        async with get_conn() as conn:
            cursor = await conn.execute(
                "SELECT * FROM user_settings WHERE user_id=?", (user_id,)
            )
            row = await cursor.fetchone()
            if row is not None:
                return dict(row)

            cursor = await conn.execute(
                "SELECT email FROM users WHERE id=?",
                (user_id,),
            )
            user_row = await cursor.fetchone()
            if user_row is None:
                raise ValueError("用户不存在")
            user_email = str(user_row["email"] or "").strip()

        # settings 缺失时自动补建，防止历史脏数据导致页面报错
        await self.create_default_settings(user_id, user_email)

        async with get_conn() as conn:
            cursor = await conn.execute(
                "SELECT * FROM user_settings WHERE user_id=?",
                (user_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError("用户配置不存在")
            return dict(row)

    async def update_user_settings(
        self,
        user_id: int,
        payload: DigestSettingsUpdateRequest,
    ) -> DigestSettingsResponse:
        keywords_list = _normalize_keywords_list(payload.keywords_list)
        if not keywords_list:
            raise ValueError("keywords_list 不能为空")
        user_search_intent = str(payload.user_search_intent or "").strip()

        now = _now_iso()
        async with get_conn() as conn:
            # 1. 先检查用户设置是否存在
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM user_settings WHERE user_id = ?", (user_id,)
            )
            count = await cursor.fetchone()
            exists = count[0] > 0
            if exists:
                # 2. 如果存在，执行更新
                cursor = await conn.execute(
                    """
                    UPDATE user_settings
                    SET target_email=?, daily_send_time=?, timezone=?, keywords_json=?, active=?, updated_at=?, user_search_intent=?
                    WHERE user_id=?
                    """,
                    (
                        payload.target_email,
                        payload.daily_send_time,
                        payload.timezone.strip() or self._settings.default_timezone,
                        json.dumps(keywords_list, ensure_ascii=False),
                        1 if payload.active else 0,
                        now,
                        user_search_intent,
                        user_id,
                    ),
                )
                logger.info(f"成功更新 {cursor.rowcount} 行")
            else:
                # 3. 如果不存在，执行插入
                cursor = await conn.execute(
                    """
                    INSERT INTO user_settings (
                        user_id, target_email, daily_send_time, timezone, 
                        keywords_json, active, updated_at, user_search_intent, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        payload.target_email,
                        payload.daily_send_time,
                        payload.timezone.strip() or self._settings.default_timezone,
                        json.dumps(keywords_list, ensure_ascii=False),
                        1 if payload.active else 0,
                        now,
                        user_search_intent,
                        now,  # created_at 使用相同的时间戳
                    ),
                )
                logger.info(f"成功为 user_id {user_id} 创建设置记录")
        return await self.get_user_settings(user_id)

    async def list_active_schedules(self) -> list[dict[str, Any]]:
        async with get_conn() as conn:
            cursor = await conn.execute(
                """
                SELECT user_id, daily_send_time, timezone, active
                FROM user_settings
                WHERE active=1
                """
            )
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_user_dispatch_profile(self, user_id: int) -> dict[str, Any]:
        user_email = ""
        async with get_conn() as conn:
            cursor = await conn.execute(
                """
                SELECT
                  u.id AS user_id,
                  u.username,
                  u.email,
                  s.target_email,
                  s.daily_send_time,
                  s.timezone,
                  s.keywords_json,
                  s.active,
                  s.user_search_intent
                FROM users u
                JOIN user_settings s ON s.user_id=u.id
                WHERE u.id=?
                """,
                (user_id,),
            )
            row = await cursor.fetchone()
            if row is not None:
                out = dict(row)
                try:
                    raw_keywords = json.loads(out.get("keywords_json") or "[]")
                except Exception:
                    raw_keywords = []
                keywords_list = _normalize_keywords_list(raw_keywords)
                out["keywords_list"] = keywords_list
                out["smtp_host"] = str(self._settings.verify_smtp_host or "").strip()
                out["smtp_port"] = int(self._settings.verify_smtp_port or 587)
                out["use_tls"] = bool(self._settings.verify_smtp_use_tls)
                out["use_ssl"] = bool(self._settings.verify_smtp_use_ssl)
                out["smtp_username"] = str(
                    self._settings.verify_smtp_username or ""
                ).strip()
                out["smtp_password"] = str(self._settings.verify_smtp_password or "")
                out["from_email"] = self.shared_sender_email()
                return out

            cursor = await conn.execute(
                "SELECT email FROM users WHERE id=?",
                (user_id,),
            )
            user_row = await cursor.fetchone()
            if user_row is None:
                raise ValueError("用户不存在")
            user_email = str(user_row["email"] or "").strip()

        # settings 缺失时自动补建，防止调度或手动推送报“用户不存在”
        await self.create_default_settings(user_id, user_email)
        return await self.get_user_dispatch_profile(user_id)

    async def add_dispatch_log(
        self, user_id: int, run_type: str, status: str, message: str
    ) -> None:
        async with get_conn() as conn:
            await conn.execute(
                """
                INSERT INTO dispatch_logs (user_id, run_type, status, message, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, run_type, status, message[:1000], _now_iso()),
            )

    async def list_dispatch_logs(
        self, user_id: int, limit: int = 20
    ) -> list[dict[str, Any]]:
        size = max(1, min(limit, 100))
        async with get_conn() as conn:
            cursor = await conn.execute(
                """
                SELECT id, run_type, status, message, created_at
                FROM dispatch_logs
                WHERE user_id=?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, size),
            )
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def add_paper_records(
        self,
        user_id: int,
        run_type: str,
        records: list[dict[str, Any]],
    ) -> int:
        payloads: list[tuple[Any, ...]] = []
        now = _now_iso()
        for row in records:
            uid = str(row.get("uid") or "").strip()
            push_date = str(row.get("push_date") or "").strip()
            if not uid or not push_date:
                continue
            keywords = _clean_keywords(
                [str(item) for item in (row.get("keywords") or [])]
            )
            payloads.append(
                (
                    user_id,
                    uid,
                    push_date,
                    str(row.get("title") or "").strip(),
                    str(row.get("url") or "").strip(),
                    str(row.get("venue") or "").strip(),
                    str(row.get("publisher") or "").strip(),
                    str(row.get("source") or "").strip(),
                    str(row.get("published_date") or "").strip(),
                    json.dumps(keywords, ensure_ascii=False),
                    run_type,
                    now,
                )
            )

        if not payloads:
            return 0

        async with get_conn() as conn:
            before = conn.total_changes
            await conn.executemany(
                """
                INSERT OR IGNORE INTO paper_records (
                  user_id, uid, push_date, title, url, venue, publisher,
                  source, published_date, keywords_json, run_type, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payloads,
            )
            inserted = int(conn.total_changes - before)
        return inserted

    async def list_paper_records(
        self, user_id: int, limit: int = 20
    ) -> list[dict[str, Any]]:
        size = max(1, min(limit, 100))
        async with get_conn() as conn:
            cursor = await conn.execute(
                """
                SELECT
                  id,
                  uid,
                  push_date,
                  title,
                  url,
                  venue,
                  publisher,
                  source,
                  published_date,
                  keywords_json,
                  run_type,
                  created_at
                FROM paper_records
                WHERE user_id=?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, size),
            )
            rows = await cursor.fetchall()

        out: list[dict[str, Any]] = []
        for row in rows:
            payload = dict(row)
            try:
                raw_keywords = json.loads(payload.get("keywords_json") or "[]")
                keywords = (
                    _clean_keywords([str(item) for item in raw_keywords])
                    if isinstance(raw_keywords, list)
                    else []
                )
            except Exception:
                keywords = []
            payload["keywords"] = keywords
            payload.pop("keywords_json", None)
            out.append(payload)
        return out

    async def get_user_digest_state(self, user_id: int) -> dict[str, Any]:
        async with get_conn() as conn:
            cursor = await conn.execute(
                "SELECT state_json FROM user_digest_state WHERE user_id=?",
                (user_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                now = _now_iso()
                await conn.execute(
                    """
                    INSERT INTO user_digest_state (user_id, state_json, created_at, updated_at)
                    VALUES (?, '{}', ?, ?)
                    """,
                    (user_id, now, now),
                )
                return {}

            raw = str(dict(row).get("state_json") or "{}").strip()
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
            return {}

    async def save_user_digest_state(self, user_id: int, state: dict[str, Any]) -> None:
        payload = state if isinstance(state, dict) else {}
        now = _now_iso()
        async with get_conn() as conn:
            await conn.execute(
                """
                INSERT INTO user_digest_state (user_id, state_json, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                  state_json=excluded.state_json,
                  updated_at=excluded.updated_at
                """,
                (user_id, json.dumps(payload, ensure_ascii=False), now, now),
            )

    async def add_user_feedback(
        self,
        *,
        user_id: int,
        username: str,
        user_email: str,
        content: str,
        email_sent: bool,
        email_error: str = "",
    ) -> dict[str, Any]:
        cleaned_content = str(content or "").strip()
        if not cleaned_content:
            raise ValueError("反馈内容不能为空")
        if len(cleaned_content) > 4000:
            raise ValueError("反馈内容不能超过 4000 字")

        now = _now_iso()
        async with get_conn() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO user_feedback (
                  user_id, username_snapshot, user_email_snapshot,
                  content, email_sent, email_error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    str(username or "").strip()[:128],
                    str(user_email or "").strip()[:255],
                    cleaned_content,
                    1 if email_sent else 0,
                    str(email_error or "").strip()[:1000],
                    now,
                ),
            )
            feedback_id = int(cursor.lastrowid)

        return {
            "id": feedback_id,
            "user_id": user_id,
            "username": str(username or "").strip(),
            "user_email": str(user_email or "").strip(),
            "content": cleaned_content,
            "email_sent": bool(email_sent),
            "email_error": str(email_error or "").strip(),
            "created_at": now,
        }

    async def list_user_feedback(
        self,
        user_id: int,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        size = max(1, min(limit, 100))
        async with get_conn() as conn:
            cursor = await conn.execute(
                """
                SELECT
                  id,
                  user_id,
                  username_snapshot AS username,
                  user_email_snapshot AS user_email,
                  content,
                  email_sent,
                  email_error,
                  created_at
                FROM user_feedback
                WHERE user_id=?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, size),
            )
            rows = await cursor.fetchall()

        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["email_sent"] = bool(item.get("email_sent", 0))
            item["email_error"] = str(item.get("email_error") or "")
            out.append(item)
        return out

    def _row_to_schema(self, row: dict[str, Any]) -> DigestSettingsResponse:
        try:
            raw_keywords = json.loads(row.get("keywords_json") or "[]")
        except Exception:
            raw_keywords = []
        keywords_list = _normalize_keywords_list(raw_keywords)
        return DigestSettingsResponse(
            sender_email=self.shared_sender_email(),
            smtp_ready=self.shared_smtp_ready(),
            target_email=str(row.get("target_email") or ""),
            daily_send_time=str(
                row.get("daily_send_time") or self._settings.default_daily_time
            ),
            timezone=str(row.get("timezone") or self._settings.default_timezone),
            keywords_list=keywords_list,
            keywords=_flatten_keywords_list(keywords_list),
            active=bool(row.get("active", 1)),
            updated_at=str(row.get("updated_at") or ""),
            user_search_intent=str(row.get("user_search_intent") or ""),
        )

    async def generate_keywords_list_by_user_query(
        self, user_query: str
    ) -> KeywordsListResponse:
        input_text = f"""请根据用户的查询意图，生成一个适合的关键词列表，用于英文学术文献搜索。要求如下：
- 关键词列表是一个二维列表 List[List[str]]。
- 返回格式必须是纯文本的 JSON 数组
```
{{
"keywords_list": [
  ["keyword",...],
  ["keyword",...],
  ...
]
}}
```
- 例如用户想搜索AI或大模型医学报告生成相关的研究，那么因为要推荐英文论文，所以关键词必须是英文的，例如输出
{{
"keywords_list": [
  ["report generation","llm"],
  ["report generation","AI"],
  ["report generation","artificial intelligence"],
  ["radiology report generation"],
]
}}
该此表的含义是：每个keywords之间是或关系，keywords内的词是与关系，这个查询类似：
(report generation AND llm) OR (report generation AND AI) OR (report generation AND artificial intelligence) OR (radiology report generation)
代表论文的标题或摘要中必须要同时包含keywords内的词，且满足至少有一个keywords组满足即可。
要求要生成尽量符合用户意图的keywords_list，且帮助用户覆盖更多相关的论文，但不要生成过多无关的关键词。请直接返回JSON，不要添加任何多余的文本说明。

用户的查询意图为：{user_query}
"""
        try:
            res = await LLMClient().aquery(
                query=input_text, json_mode=True, model_name="qwen3-max"
            )
            res = json.loads(res)
            keywords_list = res.get("keywords_list")
            return KeywordsListResponse(keywords_list=keywords_list)
        except Exception as exc:
            logger.error(f"生成关键词列表失败: {exc}")
            return KeywordsListResponse(keywords_list=[])
