from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiosqlite

from app.core.config import get_settings


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS email_codes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL,
  purpose TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  consumed INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_email_codes_lookup
  ON email_codes(email, purpose, consumed, created_at DESC);

CREATE TABLE IF NOT EXISTS user_settings (
  user_id INTEGER PRIMARY KEY,
  smtp_host TEXT NOT NULL DEFAULT '',
  smtp_port INTEGER NOT NULL DEFAULT 587,
  use_tls INTEGER NOT NULL DEFAULT 1,
  use_ssl INTEGER NOT NULL DEFAULT 0,
  smtp_username TEXT NOT NULL DEFAULT '',
  smtp_password TEXT NOT NULL DEFAULT '',
  from_email TEXT NOT NULL DEFAULT '',
  target_email TEXT NOT NULL DEFAULT '',
  daily_send_time TEXT NOT NULL DEFAULT '09:30',
  timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
  keywords_json TEXT NOT NULL DEFAULT '[]',
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  user_agent TEXT NOT NULL DEFAULT '',
  ip_address TEXT NOT NULL DEFAULT '',
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_sessions_user
  ON user_sessions(user_id, expires_at);

CREATE TABLE IF NOT EXISTS dispatch_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  run_type TEXT NOT NULL,
  status TEXT NOT NULL,
  message TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_dispatch_logs_user
  ON dispatch_logs(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS paper_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  uid TEXT NOT NULL,
  push_date TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  url TEXT NOT NULL DEFAULT '',
  venue TEXT NOT NULL DEFAULT '',
  publisher TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT '',
  published_date TEXT NOT NULL DEFAULT '',
  keywords_json TEXT NOT NULL DEFAULT '[]',
  run_type TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
  UNIQUE(user_id, uid, push_date)
);

CREATE INDEX IF NOT EXISTS idx_paper_records_user_date
  ON paper_records(user_id, push_date DESC, id DESC);

CREATE TABLE IF NOT EXISTS user_digest_state (
  user_id INTEGER PRIMARY KEY,
  state_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  username_snapshot TEXT NOT NULL DEFAULT '',
  user_email_snapshot TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL,
  email_sent INTEGER NOT NULL DEFAULT 0,
  email_error TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_feedback_user
  ON user_feedback(user_id, id DESC);
"""


async def init_db() -> None:
    settings = get_settings()
    db_file = settings.db_file
    db_file.parent.mkdir(parents=True, exist_ok=True)
    settings.runtime_path.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(db_file) as conn:
        await conn.executescript(SCHEMA_SQL)
        await conn.commit()


@asynccontextmanager
async def get_conn() -> AsyncIterator[aiosqlite.Connection]:
    settings = get_settings()
    conn = await aiosqlite.connect(settings.db_file)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
    finally:
        await conn.close()
