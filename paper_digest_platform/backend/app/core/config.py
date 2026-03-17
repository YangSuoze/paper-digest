from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Paper Digest Platform"
    app_env: str = "dev"
    api_prefix: str = "/api/v1"
    app_secret_key: str = Field(default="replace-this-secret-key", min_length=16)

    db_path: str = "paper_digest_platform/runtime/paper_digest_platform.db"
    runtime_dir: str = "paper_digest_platform/runtime"
    base_digest_config_path: str = "paper_digest_config.json"

    session_ttl_hours: int = 72
    verify_code_ttl_minutes: int = 10
    verify_code_cooldown_seconds: int = 60

    verify_smtp_host: str = ""
    verify_smtp_port: int = 587
    verify_smtp_use_tls: bool = True
    verify_smtp_use_ssl: bool = False
    verify_smtp_username: str = ""
    verify_smtp_password: str = ""
    verify_smtp_from_email: str = ""
    verify_smtp_timeout_seconds: int = 30

    default_daily_time: str = "09:30"
    default_timezone: str = "Asia/Shanghai"
    dispatch_max_concurrency: int = 4

    log_level: str = "INFO"
    log_file: str = "paper_digest_platform/runtime/logs/backend.log"
    log_max_bytes: int = 10485760
    log_backup_count: int = 5

    cors_origins: str = "*"

    llm_api_key: str = ""
    llm_api_base_url: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        raw = (self.cors_origins or "").strip()
        if not raw:
            return ["*"]
        if raw == "*":
            return ["*"]
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[4]

    def _resolve_path(self, raw: str) -> Path:
        path = Path(raw).expanduser()
        if path.is_absolute():
            return path.resolve()
        return (self.project_root / path).resolve()

    @property
    def db_file(self) -> Path:
        return self._resolve_path(self.db_path)

    @property
    def runtime_path(self) -> Path:
        return self._resolve_path(self.runtime_dir)

    @property
    def base_digest_config_file(self) -> Path:
        return self._resolve_path(self.base_digest_config_path)

    @property
    def log_file_path(self) -> Path:
        return self._resolve_path(self.log_file)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
