from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("utf-8")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("utf-8"))


def hash_password(password: str, *, iterations: int = 210_000) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, iter_text, salt_text, digest_text = encoded.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iter_text)
        salt = _unb64(salt_text)
        expected = _unb64(digest_text)
    except Exception:
        return False
    current = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(current, expected)


def generate_session_token() -> str:
    return secrets.token_urlsafe(48)


def hash_session_token(token: str) -> str:
    key = get_settings().app_secret_key.encode("utf-8")
    return hmac.new(
        key=key, msg=token.encode("utf-8"), digestmod=hashlib.sha256
    ).hexdigest()


def generate_verify_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_verify_code(email: str, purpose: str, code: str) -> str:
    settings = get_settings()
    msg = f"{email.lower()}::{purpose.lower()}::{code}".encode("utf-8")
    return hmac.new(
        settings.app_secret_key.encode("utf-8"), msg, hashlib.sha256
    ).hexdigest()


def new_expire_time(minutes: int) -> str:
    return to_iso(utc_now() + timedelta(minutes=max(1, minutes)))


def new_session_expire(hours: int) -> str:
    return to_iso(utc_now() + timedelta(hours=max(1, hours)))
