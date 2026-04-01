from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiosqlite

from app.core.config import get_settings

"""
数据库 Schema 定义
用户表（users）:
用途：存储用户基本信息
id：自增主键
username/email：唯一约束，防止重复注册
password_hash：存储加密后的密码（不能存明文）
created_at/updated_at：审计字段

邮箱验证码表（email_codes）:
用途：管理邮箱验证码
id：自增主键
email
purpose：验证码用途（注册、找回密码、修改邮箱等）
code_hash：存储验证码的哈希值（不存明文）
expires_at：过期时间，可用于清理任务
consumed：是否已使用（0=未使用，1=已使用）
复合索引：加速查找未使用的有效验证码

用户设置表（user_settings）：
用途：存储用户的个性化配置
user_id 作为主键，确保每个用户只有一条配置
SMTP 相关字段：邮件发送配置：（所有用户都一样，用户不能自定义）
- smtp_host
- smtp_port
- use_tls
- use_ssl
- smtp_username
- smtp_password
- from_email
target_email：用户接收论文的邮箱地址
daily_send_time：每日发送时间（如 09:30）
timezone
keywords_json：关键词列表（JSON 格式） DEFAULT '[]'
active
created_at、updated_at
ON DELETE CASCADE：删除用户时自动删除配置（FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE）

用户会话表（user_sessions）：
用途：管理用户登录会话（类似 JWT 或 Session）
token_hash：存储 token 的哈希值（不存明文）
user_id：关联的用户 ID，用于关联会话
expires_at：会话过期时间
created_at
user_agent/ip_address：记录登录信息，便于安全审计
复合索引：快速查找用户的有效会话

发送日志表（dispatch_logs）
用途：记录邮件发送历史
run_type：运行类型（定时/手动/测试）
status：发送状态（success/failed/partial）
message：详细信息（错误原因、发送数量等）
索引：快速查询用户的发送历史

论文记录表（paper_records）
用途：存储推送的论文记录
id INTEGER PRIMARY KEY AUTOINCREMENT,
user_id INTEGER NOT NULL,
uid 论文唯一标识（如 DOI、arXiv ID）
push_date 推送日期（用于去重）
title 论文标题,
url 论文url,
venue TEXT NOT NULL DEFAULT '',
publisher 出版商,
source 论文来源,
published_date 发布日期,
keywords_json 匹配的关键词列表
run_type TEXT NOT NULL DEFAULT '',
created_at TEXT NOT NULL,
FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
UNIQUE(user_id, uid, push_date) 唯一约束：防止同一天重复推送同一篇论文
复合索引：快速查询用户某天的推送记录

用户摘要状态表（user_digest_state）
用途：存储用户摘要生成的中间状态
state_json：JSON 格式的状态数据
例如：上次推送的论文 ID、已发送的论文列表等
用于实现增量推送，避免重复

用户反馈表（user_feedback）
用途：存储用户反馈
username_snapshot/email_snapshot：快照用户名和邮箱（防止用户改名后丢失）
email_sent：是否已发送反馈邮件通知
email_error：邮件发送失败原因
"""
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
        # SCHEMA_SQL 这个模块定义了一个完整的数据库 Schema（表结构），并通过 init_db() 函数异步创建这些表和索引。
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
