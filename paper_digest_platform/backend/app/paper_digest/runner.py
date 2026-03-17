from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.paper_digest import legacy_agent


@dataclass(slots=True)
class RunRequest:
    """一次论文推送执行请求。

    说明：
    - 该结构用于把平台层参数集中化，避免调用方传递大量位置参数。
    - 对旧脚本仍保持参数兼容，内部最终转发给 `legacy_agent.run_once`。
    """

    config_path: str
    dry_run: bool = False
    no_email: bool = False
    skip_llm: bool = False
    skip_semantic_scholar: bool = False
    run_mode: str = "daily"
    keywords_list: list[list[str]] | None = None
    state_override: dict[str, Any] | None = None
    persist_state_to_file: bool = True
    user_search_intent: str = ""
    dispatch_run_type: str = "scheduled"


class PaperDigestRunner:
    """论文推送执行器（平台封装层）。

    职责：
    - 为上层服务提供稳定调用 API
    - 屏蔽 legacy 脚本的组织细节
    - 便于后续逐步把 legacy 实现拆分为模块化实现
    """

    def run(self, request: RunRequest) -> None:
        """执行一次推送任务。"""
        legacy_agent.run_once(
            request.config_path,
            dry_run=request.dry_run,
            no_email=request.no_email,
            skip_llm=request.skip_llm,
            skip_semantic_scholar=request.skip_semantic_scholar,
            run_mode=request.run_mode,
            keywords_list=request.keywords_list,
            state_override=request.state_override,
            persist_state_to_file=request.persist_state_to_file,
            profile=request.user_search_intent,
            dispatch_run_type=request.dispatch_run_type,
        )


_default_runner = PaperDigestRunner()


def run_once(
    config_path: str,
    dry_run: bool = False,
    no_email: bool = False,
    skip_llm: bool = False,
    skip_semantic_scholar: bool = False,
    run_mode: str = "daily",
    keywords_list: list[list[str]] | None = None,
    state_override: dict[str, Any] | None = None,
    persist_state_to_file: bool = True,
    user_search_intent: str = "",
    dispatch_run_type: str = "scheduled",
) -> None:
    """兼容旧签名的函数式入口。"""
    request = RunRequest(
        config_path=config_path,
        dry_run=dry_run,
        no_email=no_email,
        skip_llm=skip_llm,
        skip_semantic_scholar=skip_semantic_scholar,
        run_mode=run_mode,
        keywords_list=keywords_list,
        state_override=state_override,
        persist_state_to_file=persist_state_to_file,
        user_search_intent=user_search_intent,
        dispatch_run_type=dispatch_run_type,
    )
    _default_runner.run(request)


def build_parser():
    """CLI 参数解析入口（沿用 legacy 实现）。"""
    return legacy_agent.build_parser()


def main() -> None:
    """CLI 主入口（沿用 legacy 实现）。"""
    legacy_agent.main()
