from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.paper_digest import legacy_agent


def run_once(
    skip_llm: bool = False,
    skip_semantic_scholar: bool = False,
    run_mode: str = "daily",
    days_back: int = 7,
    shared: dict[str, Any] | None = None,
    keywords_list: list[list[str]] | None = None,
    state_override: dict[str, Any] | None = None,
    persist_state_to_file: bool = True,
    user_search_intent: str = "",
    dispatch_run_type: str = "scheduled",
    progress_callback: Callable[[str, str], None] | None = None,
) -> None:
    """兼容旧签名的函数式入口。"""
    legacy_agent.run_once(
        skip_llm=skip_llm,
        skip_semantic_scholar=skip_semantic_scholar,
        run_mode=run_mode,
        days_back=days_back,
        shared=shared,
        keywords_list=keywords_list,
        state_override=state_override,
        persist_state_to_file=persist_state_to_file,
        profile=user_search_intent,
        dispatch_run_type=dispatch_run_type,
        progress_callback=progress_callback,
    )


def build_parser():
    """CLI 参数解析入口（沿用 legacy 实现）。"""
    return legacy_agent.build_parser()


def main() -> None:
    """CLI 主入口（沿用 legacy 实现）。"""
    legacy_agent.main()
