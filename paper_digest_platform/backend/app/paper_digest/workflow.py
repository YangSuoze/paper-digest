from __future__ import annotations

"""执行流程入口：run_once / build_parser / main。"""
import logging
import time, os
import datetime as dt
from collections.abc import Callable
from typing import Any, List, Optional
from app.paper_digest.rendering import *
from app.paper_digest.diagnostics import explain_zero_result
from app.paper_digest.fingerprints import history_row_fingerprint
from app.paper_digest.retrieval import build_default_source_calls, run_source_searches
from app.paper_digest.windowing import compute_search_window
from app.paper_digest.core_utils import (
    prune_state,
    _load_json,
    load_config,
    _today_local,
    _history_keep_days,
    _prune_push_history,
    _coerce_weekday_set,
    _log,
    _env_get,
    _parse_date,
    _paper_uid,
    _configure_stdio,
    _save_json,
    _to_weekday,
    _to_int,
    _latest_scheduled_weekday,
    _weekday_label,
    _safe_join,
    _source_breakdown,
)
from llm_tools import LLMClient

logger = logging.getLogger(__name__)


def _history_row_uid(row: dict[str, Any]) -> str:
    try:
        fp = history_row_fingerprint(row)
        if fp:
            return fp
    except Exception:
        pass
    return str(row.get("uid") or "").strip()


def run_once(
    skip_llm: bool = False,
    run_mode: str = "daily",
    days_back: int = 7,
    shared: dict[str, Any] | None = None,
    keywords_list: List[List[str]] = None,
    state_override: Optional[dict[str, Any]] = None,
    profile: str = "",  # 用户搜索需求
    dispatch_run_type: str = "scheduled",
    progress_callback: Callable[[str, str], None] | None = None,
) -> None:
    """
    run_once 的 Docstring
    :param skip_llm: 跳过大模型处理开关。如果为 `True`，会跳过大模型偏好重排和中文总结生成，直接推送原始摘要（这能极大加快运行速度并节省 Token 成本）。 bool
    :param run_mode: 运行模式，决定了脚本本次执行的任务类型。支持两种：
        - `"daily"`：执行日常的论文搜索和推送。
        - `"weekly_summary"`：执行每周的数据总结和周报发送。 str
    :param keywords_list: 外部传入的关键词列表（优先级高于配置文件 search.keywords）。 list[list[str]] | None
    :param state_override: 外部传入的状态字典（用于数据库状态持久化，避免依赖 state.path 的 JSON 文件）。 dict[str, Any] | None
    :param dispatch_run_type: 调度来源类型（如 scheduled/manual_digest），用于控制去重策略。 str
    :param progress_callback: 进度回调，参数为 (stage, message)。 Callable[[str, str], None] | None
    """

    def _report_progress(stage: str, message: str) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(str(stage or "").strip(), str(message or "").strip())
        except Exception:
            logger.debug("progress callback failed stage=%s", stage, exc_info=True)

    # 1) 读取配置与运行上下文
    _report_progress("init", "初始化任务配置中")

    run_date = _today_local()
    email_cfg = shared
    mode = (run_mode or "daily").strip().lower()
    if mode not in {"daily", "weekly_summary"}:
        raise ValueError(
            f"Unsupported run_mode='{run_mode}' (expected daily or weekly_summary)"
        )

    timeout_s = 30

    # 2) 关键词
    if mode == "daily" and not keywords_list:
        raise ValueError("请配置关键词列表（优先使用外部传入关键词）")
    # 每个关键词最大搜索结果数
    max_total = 10

    # 3) 状态来源优先级：外部注入（数据库）> 本地 JSON
    # 平台模式：调用方传入可变状态对象（通常来自数据库）
    state = state_override if isinstance(state_override, dict) else {}
    # prune_state(state, keep_days)
    history_keep_days = 180
    state["push_history"] = _prune_push_history(
        state.get("push_history") or [],
        history_keep_days,
        today=run_date,
    )

    daily_weekdays = {1, 2, 3, 4, 5, 6, 7}
    # 4) 模式分流：daily / weekly_summary
    if mode == "daily":
        if run_date.isoweekday() not in daily_weekdays:
            days = ", ".join(_weekday_label(d) for d in sorted(daily_weekdays))
            _log(
                f"[INFO] Daily run skipped: {run_date.isoformat()} is {_weekday_label(run_date.isoweekday())}, "
                f"allowed weekdays={days}."
            )
            return
    else:
        weekly_enabled = False
        weekly_weekday = 7
        lookback_days = 7
        max_items = 120
        scheduled_date = _latest_scheduled_weekday(run_date, weekly_weekday)
        week_key = scheduled_date.strftime("%G-W%V")

        if not weekly_enabled:
            _log(
                "[INFO] Weekly summary disabled by config.schedule.weekly_summary.enabled; skip."
            )
            return
        last_week = str(state.get("last_weekly_summary_week") or "").strip()
        last_weekly_date = _parse_date(
            str(state.get("last_weekly_summary_date") or "").strip()
        )
        previous_scheduled_date = scheduled_date - dt.timedelta(days=7)
        scheduled_today = run_date == scheduled_date
        can_catch_up = (
            not scheduled_today
        ) and last_weekly_date == previous_scheduled_date
        if not scheduled_today and not can_catch_up:
            _log(
                f"[INFO] Weekly summary skipped: {run_date.isoformat()} is {_weekday_label(run_date.isoweekday())}, "
                f"configured day={_weekday_label(weekly_weekday)}."
            )
            return
        if last_week == week_key:
            _log(f"[INFO] Weekly summary already sent for {week_key}; skip.")
            return
        if can_catch_up:
            _log(
                f"[INFO] Weekly summary catch-up: {run_date.isoformat()} will send the pending "
                f"{_weekday_label(weekly_weekday)} summary for {scheduled_date.isoformat()}."
            )

        subject, text_body, html_body, inline_images = build_weekly_summary_email(
            scheduled_date,
            state.get("push_history") or [],
            lookback_days=lookback_days,
            max_items=max_items,
        )

        email_sent = False
        send_email(
            email_cfg,
            subject,
            text_body,
            html_body,
            inline_images=inline_images,
        )
        print(f"[OK] 已发送每周总结邮件：{_safe_join(email_cfg.get('to') or [])}")
        email_sent = True

        if not email_sent:
            _log("[INFO] Skip weekly state update: email not sent.")
            return

        now_ts = dt.datetime.now().isoformat(timespec="seconds")
        state["last_run"] = now_ts
        state["last_weekly_summary_at"] = now_ts
        state["last_weekly_summary_date"] = scheduled_date.isoformat()
        state["last_weekly_summary_week"] = week_key
        state["push_history"] = _prune_push_history(
            state.get("push_history") or [],
            history_keep_days,
            today=run_date,
        )
        return

    # 5) 当日幂等保护：如果今天已经发送过，则直接跳过
    if dispatch_run_type == "scheduled":
        last_email_date = str(state.get("last_scheduled_email_date") or "").strip()
        if last_email_date == run_date.isoformat():
            _log(
                f"[INFO] Daily send guard: email already sent on {last_email_date}; skip sending again today."
            )
            _report_progress("skip", "今日已发送过定时邮件，跳过执行")
            return
    pubmed_cfg = {
        "enabled": True,
        "rows": 30,
        "email": "",
        "api_key_env": "NCBI_API_KEY",
    }
    pm_email = (pubmed_cfg.get("email") or "").strip()
    pm_api_key = (pubmed_cfg.get("api_key") or "").strip()
    if not pm_api_key:
        pm_key_env = (pubmed_cfg.get("api_key_env") or "").strip()
        if pm_key_env:
            pm_api_key = _env_get(pm_key_env)
    semantic_scholar_api_key = _env_get("SEMANTIC_SCHOLAR_API_KEY")
    openalex_mailto = _env_get("OPENALEX_MAILTO")

    search_window = compute_search_window(
        run_date=run_date,
        days_back=days_back,
        state=state,
        dispatch_run_type=dispatch_run_type,
    )
    since = search_window.since
    until = search_window.until

    _log(
        f"[INFO] Run date: {run_date.isoformat()} | Window: {since.isoformat()} ~ {until.isoformat()} "
        f"| recovery={search_window.recovery_reason} | Keywords list: {keywords_list}"
    )
    _report_progress(
        "search_window",
        f"开始检索 {since.isoformat()} 至 {until.isoformat()} 论文（关键词组 {len(keywords_list or [])}）",
    )

    _report_progress("search_sources", "多来源论文检索中")
    source_calls = build_default_source_calls(
        keywords_list=keywords_list,
        since=since,
        until=until,
        timeout_s=timeout_s,
        pubmed_api_key=pm_api_key,
        pubmed_email=pm_email,
        semantic_scholar_api_key=semantic_scholar_api_key,
        openalex_mailto=openalex_mailto,
    )
    retrieval_result = run_source_searches(
        source_calls=source_calls,
        run_type=dispatch_run_type,
        since=since,
        until=until,
        recovery_reason=search_window.recovery_reason,
        query_count=len(keywords_list or []),
    )
    diagnostics = retrieval_result.diagnostics
    papers = retrieval_result.papers
    for item in diagnostics.source_results:
        _log(
            f"[INFO] Source {item.source} status={item.status} raw={item.raw_count} "
            f"candidates={item.candidate_count}"
        )
    _report_progress(
        "search_sources",
        f"多来源检索完成，候选 {diagnostics.counts.raw_fetched} 篇，去重后 {len(papers)} 篇",
    )

    # 6) 全源聚合去重已在 retrieval 管线中完成
    _report_progress("merge", "聚合去重中")
    _log(
        f"[INFO] Unique by source (after dedupe): {_source_breakdown(papers)} len={len(papers)}"
    )
    # 7) 基于历史状态去重：仅“定时调度”参与去重，手动执行不计入去重历史
    seen: dict[str, str] = {}
    if dispatch_run_type == "scheduled":
        scheduled_seen_raw = state.get("seen_scheduled", {})
        if not isinstance(scheduled_seen_raw, dict):
            scheduled_seen_raw = {}

        if not scheduled_seen_raw:
            history_rows = state.get("push_history", [])
            for row in history_rows:
                if not isinstance(row, dict):
                    continue
                row_run_type = row.get("run_type")
                if row_run_type != "scheduled":
                    continue
                uid = _history_row_uid(row)
                pushed_on = str(row.get("push_date") or "").strip()
                if not uid:
                    continue
                scheduled_seen_raw[uid] = pushed_on

        for uid_raw, date_raw in scheduled_seen_raw.items():
            uid = str(uid_raw or "").strip()
            pushed_on = date_raw
            if not uid:
                continue
            seen[uid] = str(pushed_on or "").strip()

        _log(f"[INFO] Dedupe enabled (run_type=scheduled), seen_scheduled={len(seen)}")
    else:
        _log(f"[INFO] manual run keeps full history search.")
    available_papers: list[Paper] = []
    for p in papers:
        uid = _paper_uid(p)
        if dispatch_run_type == "scheduled" and uid in seen:
            continue
        available_papers.append(p)
    diagnostics.counts.after_history_dedup = len(available_papers)
    logger.info(f"llm筛选前论文数量={len(available_papers)}")
    _report_progress("llm_rerank", "大模型偏好筛选中")
    try:
        available_papers, _ = llm_preference_rerank(available_papers, profile)
    except Exception as e:
        _log(f"[WARN] LLM偏好筛选失败 -> {e}")

    if max_total > 0 and len(available_papers) > max_total:
        available_papers = available_papers[:max_total]
    diagnostics.counts.after_relevance_filter = len(available_papers)

    new_papers = available_papers
    diagnostics.counts.delivered = len(new_papers)
    if diagnostics.counts.delivered == 0:
        diagnostics.zero_result_explanation = explain_zero_result(diagnostics)

    if dispatch_run_type == "scheduled":
        _log(
            f"[INFO] New papers llm筛选出来: {len(new_papers)} (max_total={max_total})"
        )
    else:
        _log(
            f"[INFO] Dedupe disabled; selected {len(new_papers)} papers (max_total={max_total})."
        )
    _log(f"[INFO] Selected by source: {_source_breakdown(new_papers)}")

    enriched: list[Paper] = available_papers

    # ss_enabled = True
    # api_key = "80ZnSkzYTv8bZHfiW8pL08fNA2LXGGZ55CPQSVXm"
    # enriched: list[Paper] = []
    # if ss_enabled:
    #     _report_progress("semantic_enrich", "论文信息补全中（Semantic Scholar）")
    # else:
    #     _report_progress("semantic_enrich", "跳过 Semantic Scholar 补全")
    # for p in available_papers:
    #     if ss_enabled:
    #         try:
    #             _log(f"[INFO] Enriching (Semantic Scholar): {p.title[:80]}")
    #             enriched.append(
    #                 semantic_scholar_enrich(p, api_key=api_key, timeout_s=timeout_s)
    #             )
    #         except Exception as e:
    #             _log(f"[WARN] Semantic Scholar补全失败：{p.title[:60]} -> {e}")
    #             enriched.append(p)
    #     else:
    #         enriched.append(p)
    #     time.sleep(0.5)

    # 8) 可选摘要：仅对本次入选论文生成中文总结
    summaries: dict[str, dict[str, str]] = {}
    if skip_llm:
        summarize_limit = 0
    else:
        summarize_limit = len(enriched)
    if summarize_limit > 0:
        if LLMClient is None:

            _log("[WARN] 未能导入 llm_tools.LLMClient，已跳过中文总结。")
            _report_progress("llm_summary", "未加载 LLMClient，跳过中文总结")
        else:
            _report_progress(
                "llm_summary",
                f"大模型分析总结中（共 {min(summarize_limit, len(enriched))} 篇）",
            )
            for idx, p in enumerate(enriched):
                if idx >= summarize_limit:
                    break
                uid = _paper_uid(p)
                try:
                    _report_progress(
                        "llm_summary",
                        f"大模型分析总结中（{idx + 1}/{min(summarize_limit, len(enriched))}）",
                    )
                    _log(
                        f"[INFO] Summarizing (LLM) {idx+1}/{min(summarize_limit, len(enriched))}: {p.title[:80]}"
                    )
                    summaries[uid] = llm_summarize_zh(p, user_search_intent=profile)
                except Exception as e:
                    _log(f"[WARN] LLM总结失败：{p.title[:60]} -> {e}")
                time.sleep(0.5)
    else:
        _report_progress("llm_summary", "跳过大模型总结")

    diagnostics_payload = diagnostics.to_dict()
    state["last_search_diagnostics"] = diagnostics_payload
    state["last_search_window"] = {
        "since": since.isoformat(),
        "until": until.isoformat(),
        "recovery_reason": search_window.recovery_reason,
        "run_type": dispatch_run_type,
    }

    _report_progress("render_email", "整理邮件内容中")
    subject, text_body, html_body = build_email(
        run_date,
        enriched,
        summaries,
        diagnostics=diagnostics,
    )

    email_sent = False

    _report_progress("send_email", "邮件发送中")
    send_email(email_cfg, subject, text_body, html_body)
    print(f"[OK] 已发送邮件：{_safe_join(email_cfg.get('to') or [])}")
    email_sent = True
    _report_progress("send_email", "邮件发送完成")

    # 9) 发送成功后更新状态（去重集合 + 推送历史）
    if not email_sent:
        _log(
            "[INFO] Skip state update: email not sent, keep dedupe based on pushed papers only."
        )
    else:
        history = state.get("push_history") or []
        for p in enriched:
            history.append(
                _paper_history_record(p, run_date, run_type=dispatch_run_type)
            )

        if not dispatch_run_type == "scheduled":
            _log("[INFO] Skip scheduled dedupe state update for manual dispatch.")
        else:
            for p in enriched:
                d = run_date.isoformat()
                seen[_paper_uid(p)] = d
            state["seen_scheduled"] = seen
            state["seen"] = seen

        now_ts = dt.datetime.now().isoformat(timespec="seconds")
        state["push_history"] = _prune_push_history(
            history, history_keep_days, today=run_date
        )
        state["last_run"] = now_ts
        state["last_email_at"] = now_ts
        state["last_email_date"] = run_date.isoformat()
        state["last_successful_search_date"] = run_date.isoformat()
        state["last_successful_search_window"] = {
            "since": since.isoformat(),
            "until": until.isoformat(),
            "recovery_reason": search_window.recovery_reason,
        }
        state.pop("last_search_failed_at", None)
        if dispatch_run_type == "scheduled":
            state["last_scheduled_email_date"] = run_date.isoformat()
            state["last_successful_scheduled_search_date"] = run_date.isoformat()
        # 仅文件模式写回 JSON；数据库模式由外层服务持久化 state_override。

        _report_progress("completed", "推送执行完成")


def build_parser() -> argparse.ArgumentParser:
    """CLI 入口参数定义（用于脚本独立运行/排障）。"""
    p = argparse.ArgumentParser(
        description="Daily paper digest agent (arXiv + Crossref + email)"
    )
    p.add_argument(
        "--config", default="paper_digest_config.json", help="配置文件路径（json）"
    )
    p.add_argument(
        "--mode",
        default="daily",
        choices=("daily", "weekly_summary"),
        help="运行模式：daily=工作日论文推送，weekly_summary=每周总结邮件",
    )
    p.add_argument(
        "--dry-run", action="store_true", help="只打印内容，不发送邮件，不写状态"
    )
    p.add_argument("--no-email", action="store_true", help="不发邮件（不写状态）")
    p.add_argument("--skip-llm", action="store_true", help="跳过中文总结（更快）")
    p.add_argument(
        "--skip-semantic-scholar",
        action="store_true",
        help="跳过 Semantic Scholar 补全（更快）",
    )
    return p


def main() -> None:
    """脚本入口：解析参数后执行 run_once。"""
    _configure_stdio()
    args = build_parser().parse_args()
    run_once(
        args.config,
        skip_llm=args.skip_llm,
        run_mode=args.mode,
    )


if __name__ == "__main__":
    main()


# 导出当前模块全部符号（包含下划线前缀符号，供分层模块通过 * 复用）。
__all__ = [
    name
    for name in globals().keys()
    if name
    not in {
        "__builtins__",
        "__cached__",
        "__doc__",
        "__file__",
        "__loader__",
        "__name__",
        "__package__",
        "__spec__",
        "__all__",
    }
]
