"""Paper Digest 领域模块。

该包提供：
- `run_once`：兼容旧调用签名的函数式入口
- `main`：CLI 入口（转发到 legacy 实现）
"""

from app.paper_digest.runner import build_parser, main, run_once
from app.paper_digest.diagnostics import (
    SearchRunCounts,
    SearchRunDiagnostics,
    SourceResult,
    ZeroResultExplanation,
)
from app.paper_digest.fingerprints import fingerprint, paper_fingerprint
from app.paper_digest.retrieval import (
    RetrievalResult,
    build_default_source_calls,
    merge_duplicate_papers,
    merge_paper_pair,
    run_source_searches,
)
from app.paper_digest.windowing import SearchWindow, compute_search_window

__all__ = [
    "run_once",
    "build_parser",
    "main",
    "SearchRunCounts",
    "SearchRunDiagnostics",
    "SourceResult",
    "ZeroResultExplanation",
    "fingerprint",
    "paper_fingerprint",
    "RetrievalResult",
    "build_default_source_calls",
    "merge_duplicate_papers",
    "merge_paper_pair",
    "run_source_searches",
    "SearchWindow",
    "compute_search_window",
]
