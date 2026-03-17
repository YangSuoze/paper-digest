from __future__ import annotations

from dataclasses import dataclass

from app.core.config import get_settings
from app.core.security import (
    hash_password,
    hash_session_token,
    hash_verify_code,
    new_expire_time,
    new_session_expire,
    parse_iso,
    to_iso,
    utc_now,
    verify_password,
    generate_session_token,
    generate_verify_code,
)
from app.db.database import get_conn
from app.schemas.auth import LoginResponse, UserProfile
from app.services.email_service import EmailService
from app.services.settings_service import SettingsService


@dataclass
class UserIdentity:
    id: int
    username: str
    email: str


class AuthService:
    def __init__(self, *, email_service: EmailService, settings_service: SettingsService) -> None:
        self._settings = get_settings()
        self._email_service = email_service
        self._settings_service = settings_service

    async def request_register_code(self, email: str) -> None:
        normalized_email = email.strip().lower()
        await self._assert_email_not_used(normalized_email)
        await self._issue_code(email=normalized_email, purpose="register")

    async def confirm_register(self, *, email: str, username: str, password: str, code: str) -> None:
        normalized_email = email.strip().lower()
        normalized_username = username.strip().lower()
        await self._assert_email_not_used(normalized_email)
        await self._assert_username_not_used(normalized_username)
        await self._verify_code(email=normalized_email, purpose="register", code=code)

        now = to_iso(utc_now())
        async with get_conn() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO users (username, email, password_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (normalized_username, normalized_email, hash_password(password), now, now),
            )
            user_id = int(cursor.lastrowid)
        await self._settings_service.create_default_settings(user_id, normalized_email)

    async def request_reset_code(self, email: str) -> None:
        normalized_email = email.strip().lower()
        exists = await self._has_email(normalized_email)
        if not exists:
            return
        await self._issue_code(email=normalized_email, purpose="reset")

    async def reset_password(self, *, email: str, code: str, new_password: str) -> None:
        normalized_email = email.strip().lower()
        await self._verify_code(email=normalized_email, purpose="reset", code=code)
        now = to_iso(utc_now())
        async with get_conn() as conn:
            cursor = await conn.execute(
                "SELECT id FROM users WHERE email=?",
                (normalized_email,),
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError("账号不存在")
            user_id = int(row["id"])
            await conn.execute(
                "UPDATE users SET password_hash=?, updated_at=? WHERE id=?",
                (hash_password(new_password), now, user_id),
            )
            await conn.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))

    async def login(
        self,
        *,
        username: str,
        password: str,
        user_agent: str = "",
        ip_address: str = "",
    ) -> LoginResponse:
        normalized_username = username.strip().lower()
        async with get_conn() as conn:
            cursor = await conn.execute(
                "SELECT id, username, email, password_hash FROM users WHERE username=?",
                (normalized_username,),
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError("用户名或密码错误")

            if not verify_password(password, str(row["password_hash"])):
                raise ValueError("用户名或密码错误")

            token = generate_session_token()
            token_hash = hash_session_token(token)
            expires_at = new_session_expire(self._settings.session_ttl_hours)
            await conn.execute(
                """
                INSERT INTO user_sessions (token_hash, user_id, expires_at, created_at, user_agent, ip_address)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    token_hash,
                    int(row["id"]),
                    expires_at,
                    to_iso(utc_now()),
                    user_agent[:255],
                    ip_address[:128],
                ),
            )

        profile = UserProfile(id=int(row["id"]), username=str(row["username"]), email=str(row["email"]))
        return LoginResponse(token=token, expires_at=expires_at, user=profile)

    async def logout(self, token: str) -> None:
        token_hash = hash_session_token(token)
        async with get_conn() as conn:
            await conn.execute("DELETE FROM user_sessions WHERE token_hash=?", (token_hash,))

    async def get_user_by_token(self, token: str) -> UserIdentity:
        token_hash = hash_session_token(token)
        now = utc_now()
        async with get_conn() as conn:
            cursor = await conn.execute(
                """
                SELECT s.expires_at, u.id, u.username, u.email
                FROM user_sessions s
                JOIN users u ON u.id=s.user_id
                WHERE s.token_hash=?
                """,
                (token_hash,),
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError("登录状态无效")
            expires = parse_iso(str(row["expires_at"]))
            if expires <= now:
                await conn.execute("DELETE FROM user_sessions WHERE token_hash=?", (token_hash,))
                raise ValueError("登录状态已过期")
            return UserIdentity(id=int(row["id"]), username=str(row["username"]), email=str(row["email"]))

    async def _issue_code(self, *, email: str, purpose: str) -> None:
        now = utc_now()
        cooldown_seconds = max(1, int(self._settings.verify_code_cooldown_seconds))
        code_id = 0
        code = generate_verify_code()
        code_hash = hash_verify_code(email, purpose, code)
        expires_at = new_expire_time(self._settings.verify_code_ttl_minutes)
        created_at = to_iso(now)
        async with get_conn() as conn:
            cursor = await conn.execute(
                """
                SELECT created_at
                FROM email_codes
                WHERE email=? AND purpose=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (email, purpose),
            )
            last = await cursor.fetchone()
            if last is not None:
                last_at = parse_iso(str(last["created_at"]))
                elapsed = (now - last_at).total_seconds()
                if elapsed < cooldown_seconds:
                    remaining = int(cooldown_seconds - elapsed)
                    raise ValueError(f"请求过于频繁，请在 {remaining} 秒后重试")

            cursor = await conn.execute(
                """
                INSERT INTO email_codes (email, purpose, code_hash, expires_at, consumed, created_at)
                VALUES (?, ?, ?, ?, 0, ?)
                """,
                (email, purpose, code_hash, expires_at, created_at),
            )
            code_id = int(cursor.lastrowid)

        try:
            await self._email_service.send_verification_code(email, code, purpose)
        except Exception:
            if code_id > 0:
                async with get_conn() as conn:
                    await conn.execute("DELETE FROM email_codes WHERE id=?", (code_id,))
            raise

    async def _verify_code(self, *, email: str, purpose: str, code: str) -> None:
        async with get_conn() as conn:
            cursor = await conn.execute(
                """
                SELECT id, code_hash, expires_at
                FROM email_codes
                WHERE email=? AND purpose=? AND consumed=0
                ORDER BY id DESC
                LIMIT 1
                """,
                (email, purpose),
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError("验证码不存在或已失效")

            expires_at = parse_iso(str(row["expires_at"]))
            if expires_at <= utc_now():
                raise ValueError("验证码已过期")

            expected_hash = str(row["code_hash"])
            current_hash = hash_verify_code(email, purpose, code.strip())
            if expected_hash != current_hash:
                raise ValueError("验证码错误")

            await conn.execute("UPDATE email_codes SET consumed=1 WHERE id=?", (int(row["id"]),))

    async def _assert_email_not_used(self, email: str) -> None:
        if await self._has_email(email):
            raise ValueError("该邮箱已注册")

    async def _assert_username_not_used(self, username: str) -> None:
        async with get_conn() as conn:
            cursor = await conn.execute("SELECT id FROM users WHERE username=?", (username,))
            row = await cursor.fetchone()
        if row is not None:
            raise ValueError("用户名已存在")

    async def _has_email(self, email: str) -> bool:
        async with get_conn() as conn:
            cursor = await conn.execute("SELECT id FROM users WHERE email=?", (email,))
            row = await cursor.fetchone()
        return row is not None
