"""Paper Digest 领域模块。

该包提供：
- `run_once`：兼容旧调用签名的函数式入口
- `main`：CLI 入口（转发到 legacy 实现）
"""

from app.paper_digest.runner import build_parser, main, run_once

__all__ = [
    "run_once",
    "build_parser",
    "main",
]
