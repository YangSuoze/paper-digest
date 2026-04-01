from __future__ import annotations

"""执行流程入口：run_once / build_parser / main。"""
import logging
import time, os
import datetime as dt
from collections.abc import Callable
from typing import Any, List, Optional
from app.paper_digest.rendering import *
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


def run_once(
    config_path: str,
    dry_run: bool = False,
    no_email: bool = False,
    skip_llm: bool = False,
    skip_semantic_scholar: bool = False,
    run_mode: str = "daily",
    keywords_list: List[List[str]] = None,
    state_override: Optional[dict[str, Any]] = None,
    persist_state_to_file: bool = True,
    profile: str = "",  # 用户搜索需求
    dispatch_run_type: str = "scheduled",
    progress_callback: Callable[[str, str], None] | None = None,
) -> None:
    """
    run_once 的 Docstring

    :param config_path: 配置文件的路径（通常是 `.json` 文件）。包含了所有搜索关键词、API Keys、大模型配置、发件邮箱配置等。
    :type config_path: str
    :param dry_run: 试运行模式开关。如果为 `True`，脚本只会执行搜索、过滤和生成邮件内容，在终端打印出来，但**绝不发送邮件，也不修改本地历史状态文件**。
    :type dry_run: bool
    :param no_email: 不发邮件开关。同上，完成所有处理但不发送邮件，也不更新本地已读状态（通常用于调试抓取和摘要生成）。
    :type no_email: bool
    :param skip_llm: 跳过大模型处理开关。如果为 `True`，会跳过大模型偏好重排和中文总结生成，直接推送原始摘要（这能极大加快运行速度并节省 Token 成本）。
    :type skip_llm: bool
    :param skip_semantic_scholar: 跳过 Semantic Scholar 数据补全开关。如果为 `True`，将不调用 Semantic Scholar API 来补全缺失的摘要、作者或期刊信息。
    :type skip_semantic_scholar: bool
    :param run_mode: 运行模式，决定了脚本本次执行的任务类型。支持两种：
        - `"daily"`：执行日常的论文搜索和推送。
        - `"weekly_summary"`：执行每周的数据总结和周报发送。
    :type run_mode: str
    :param keywords_list: 外部传入的关键词列表（优先级高于配置文件 search.keywords）。
    :type keywords_list: list[list[str]] | None
    :param state_override: 外部传入的状态字典（用于数据库状态持久化，避免依赖 state.path 的 JSON 文件）。
    :type state_override: dict[str, Any] | None
    :param persist_state_to_file: 是否将状态写回 state.path 指向的 JSON 文件。
    :type persist_state_to_file: bool
    :param dispatch_run_type: 调度来源类型（如 scheduled/manual_digest），用于控制去重策略。
    :type dispatch_run_type: str
    :param progress_callback: 进度回调，参数为 (stage, message)。
    :type progress_callback: Callable[[str, str], None] | None
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
    cfg = load_config(config_path)
    config_dir = os.path.dirname(os.path.abspath(config_path))

    run_date = _today_local()
    search_cfg = cfg.get("search") or {}
    schedule_cfg = cfg.get("schedule") or {}
    sources_cfg = cfg.get("sources") or {}
    email_cfg = cfg.get("email") or {}
    llm_cfg = cfg.get("llm") or {}
    state_cfg = cfg.get("state") or {}
    mode = (run_mode or "daily").strip().lower()
    if mode not in {"daily", "weekly_summary"}:
        raise ValueError(
            f"Unsupported run_mode='{run_mode}' (expected daily or weekly_summary)"
        )
    normalized_run_type = str(dispatch_run_type or "scheduled").strip().lower()
    scheduled_dispatch = normalized_run_type == "scheduled"

    days_back = int(search_cfg.get("days_back") or 1)
    since = run_date - dt.timedelta(days=days_back)
    until = run_date
    timeout_s = int(search_cfg.get("timeout_s") or 30)

    # 2) 关键词
    if mode == "daily" and not keywords_list:
        raise ValueError("请配置关键词列表（优先使用外部传入关键词）")

    max_total = int(search_cfg.get("max_total_papers") or 10)
    max_per_keyword = int(search_cfg.get("max_results_per_keyword") or 30)

    # 3) 状态来源优先级：外部注入（数据库）> 本地 JSON
    state_path = (state_cfg.get("path") or "paper_digest_state.json").strip()
    if not os.path.isabs(state_path):
        state_path = os.path.join(config_dir, state_path)
    keep_days = int(state_cfg.get("keep_days") or 60)
    if state_override is None:
        # 历史脚本模式：读 JSON 状态文件
        state = prune_state(load_state(state_path), keep_days)
    else:
        # 平台模式：调用方传入可变状态对象（通常来自数据库）
        state = state_override if isinstance(state_override, dict) else {}
        prune_state(state, keep_days)
    history_keep_days = _history_keep_days(state_cfg, keep_days)
    state["push_history"] = _prune_push_history(
        state.get("push_history") or [],
        history_keep_days,
        today=run_date,
    )

    daily_weekdays = _coerce_weekday_set(
        schedule_cfg.get("daily_weekdays"), {1, 2, 3, 4, 5}
    )
    # 4) 模式分流：daily / weekly_summary
    if mode == "daily":
        if run_date.isoweekday() not in daily_weekdays and not dry_run and not no_email:
            days = ", ".join(_weekday_label(d) for d in sorted(daily_weekdays))
            _log(
                f"[INFO] Daily run skipped: {run_date.isoformat()} is {_weekday_label(run_date.isoweekday())}, "
                f"allowed weekdays={days}."
            )
            return
    else:
        weekly_cfg = schedule_cfg.get("weekly_summary") or {}
        weekly_enabled_raw = weekly_cfg.get("enabled")
        weekly_enabled = (
            True if weekly_enabled_raw is None else bool(weekly_enabled_raw)
        )
        weekly_weekday = _to_weekday(weekly_cfg.get("weekday"), 7)
        lookback_days = max(1, _to_int(weekly_cfg.get("lookback_days"), 7))
        max_items = max(1, _to_int(weekly_cfg.get("max_items"), 120))
        scheduled_date = _latest_scheduled_weekday(run_date, weekly_weekday)
        week_key = scheduled_date.strftime("%G-W%V")

        if not weekly_enabled and not dry_run:
            _log(
                "[INFO] Weekly summary disabled by config.schedule.weekly_summary.enabled; skip."
            )
            return
        if not dry_run and not no_email:
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
        if dry_run:
            print(subject)
            print(text_body)
            return

        email_sent = False
        if no_email:
            print("[INFO] no_email=True, weekly summary generated but email not sent.")
        else:
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
        if persist_state_to_file and state_override is None:
            _save_json(state_path, state)
        return

    # 5) 当日幂等保护：如果今天已经发送过，则直接跳过
    single_push_per_day_raw = state_cfg.get("single_push_per_day")
    single_push_per_day = (
        True if single_push_per_day_raw is None else bool(single_push_per_day_raw)
    )
    if single_push_per_day and scheduled_dispatch and not dry_run and not no_email:
        last_email_date = str(state.get("last_scheduled_email_date") or "").strip()
        if last_email_date == run_date.isoformat():
            _log(
                f"[INFO] Daily send guard: email already sent on {last_email_date}; skip sending again today."
            )
            _report_progress("skip", "今日已发送过定时邮件，跳过执行")
            return
    crossref_cfg = sources_cfg.get("crossref") or {}
    arxiv_cfg = sources_cfg.get("arxiv") or {}
    pubmed_cfg = sources_cfg.get("pubmed") or {}
    ss_cfg = sources_cfg.get("semantic_scholar") or {}

    all_papers: list[Paper] = []

    _log(
        f"[INFO] Run date: {run_date.isoformat()} | Window: {since.isoformat()} ~ {until.isoformat()} | Keywords list: {keywords_list}"
    )
    _report_progress(
        "search_window",
        f"开始检索近 {days_back} 天论文（关键词组 {len(keywords_list or [])}）",
    )

    if bool(arxiv_cfg.get("enabled", True)):
        _report_progress("search_arxiv", "arXiv 搜索中")
        _log("[INFO] Source enabled: arXiv")
        try:
            results = search_arxiv(
                keywords_list=keywords_list,
                since=since,
            )
            _log(f"[INFO] arXiv '{keywords_list}' -> {len(results)}")
            all_papers.extend(results)
            _report_progress("search_arxiv", f"arXiv 完成，命中 {len(results)} 篇")
        except Exception as e:
            _log(f"[WARN] arXiv搜索失败：{keywords_list} -> {e}")
            _report_progress("search_arxiv", "arXiv 搜索失败，继续后续数据源")

    if bool(crossref_cfg.get("enabled", True)):
        _report_progress("search_crossref", "Crossref 搜索中")
        _log("[INFO] Source enabled: Crossref")
        try:
            results = search_crossref(
                keywords_list=keywords_list,
                rows=20,
                since=since,
                mailto="",
                publisher_substrings=[],
                types=[],
                timeout_s=timeout_s,
            )
            _log(f"[INFO] Crossref '{keywords_list}' -> {len(results)}")
            all_papers.extend(results)
            _report_progress("search_crossref", f"Crossref 完成，命中 {len(results)} 篇")
        except Exception as e:
            _log(f"[WARN] Crossref搜索失败：{keywords_list} -> {e}")
            _report_progress("search_crossref", "Crossref 搜索失败，继续后续数据源")

    if bool(pubmed_cfg.get("enabled", True)):
        _report_progress("search_pubmed", "PubMed 搜索中")
        _log("[INFO] Source enabled: PubMed")
        rows = int(pubmed_cfg.get("rows") or max_per_keyword)
        pm_email = (pubmed_cfg.get("email") or "").strip()
        pm_api_key = (pubmed_cfg.get("api_key") or "").strip()
        if not pm_api_key:
            pm_key_env = (pubmed_cfg.get("api_key_env") or "").strip()
            if pm_key_env:
                pm_api_key = _env_get(pm_key_env)
        try:
            results = search_pubmed(
                keywords_list=keywords_list,
                rows=20,
                since=since,
                timeout_s=timeout_s,
                api_key=pm_api_key,
                email=pm_email,
            )
            _log(f"[INFO] PubMed '{keywords_list}' -> {len(results)}")
            all_papers.extend(results)
            _report_progress("search_pubmed", f"PubMed 完成，命中 {len(results)} 篇")
        except Exception as e:
            _log(f"[WARN] PubMed搜索失败：{keywords_list} -> {e}")
            _report_progress("search_pubmed", "PubMed 搜索失败，继续后续流程")

    # if bool(ieee_cfg.get("enabled", True)):
    #     ieee_api_key = (ieee_cfg.get("api_key") or "").strip()
    #     if not ieee_api_key:
    #         ieee_key_env = (ieee_cfg.get("api_key_env") or "").strip()
    #         if ieee_key_env:
    #             ieee_api_key = _env_get(ieee_key_env)
    #     if not ieee_api_key:
    #         _log(
    #             "[WARN] IEEE Xplore enabled but no API key found; skipping IEEE source."
    #         )
    #     else:
    #         _log("[INFO] Source enabled: IEEE Xplore")
    #         rows = int(ieee_cfg.get("rows") or max_per_keyword)
    #         for kw in keywords:
    #             try:
    #                 results = search_ieee_xplore(
    #                     keyword=kw,
    #                     rows=rows,
    #                     since=since,
    #                     until=until,
    #                     timeout_s=timeout_s,
    #                     api_key=ieee_api_key,
    #                 )
    #                 _log(f"[INFO] IEEE '{kw}' -> {len(results)}")
    #                 all_papers.extend(results)
    #             except Exception as e:
    #                 print(f"[WARN] IEEE搜索失败：{kw} -> {e}")
    #                 continue
    #             time.sleep(0.34)

    # 6) 全源聚合去重：同一论文按 UID 合并，并汇总关键词
    _report_progress("merge", "聚合去重中")
    merged: dict[str, Paper] = {}
    for p in all_papers:
        uid = _paper_uid(p)
        if uid in merged:
            existing = merged[uid]
            merged[uid] = dataclasses.replace(
                existing, keywords=sorted(set(existing.keywords) | set(p.keywords))
            )
        else:
            merged[uid] = p
    papers = list(merged.values())
    _log(
        f"[INFO] Unique by source (after dedupe): {_source_breakdown(papers)} len={len(papers)}"
    )
    # 7) 基于历史状态去重：仅“定时调度”参与去重，手动执行不计入去重历史
    dedupe_enabled = scheduled_dispatch
    seen: dict[str, str] = {}
    if dedupe_enabled:
        scheduled_seen_raw = state.get("seen_scheduled")
        if not isinstance(scheduled_seen_raw, dict):
            scheduled_seen_raw = {}

        if not scheduled_seen_raw:
            history_rows = state.get("push_history") or []
            if isinstance(history_rows, list):
                for row in history_rows:
                    if not isinstance(row, dict):
                        continue
                    row_run_type = str(row.get("run_type") or "").strip().lower()
                    if row_run_type != "scheduled":
                        continue
                    uid = str(row.get("uid") or "").strip()
                    pushed_on = str(row.get("push_date") or "").strip()
                    if not uid or not pushed_on:
                        continue
                    scheduled_seen_raw[uid] = pushed_on

        for uid_raw, date_raw in scheduled_seen_raw.items():
            uid = str(uid_raw or "").strip()
            pushed_on = str(date_raw or "").strip()
            if not uid or not pushed_on:
                continue
            seen[uid] = pushed_on

        _log(
            f"[INFO] Dedupe enabled (run_type={normalized_run_type}), seen_scheduled={len(seen)}"
        )
    else:
        _log(
            f"[INFO] Dedupe disabled for run_type={normalized_run_type}; manual run keeps full history search."
        )
    available_papers: list[Paper] = []
    for p in papers:
        uid = _paper_uid(p)
        if dedupe_enabled and uid in seen:
            continue
        available_papers.append(p)
    logger.info(f"llm筛选前论文数量={len(available_papers)}")
    _report_progress("llm_rerank", "大模型偏好筛选中")
    try:
        available_papers, _ = llm_preference_rerank(available_papers, profile)
    except Exception as e:
        _log(f"[WARN] LLM偏好筛选失败 -> {e}")

    if max_total > 0 and len(available_papers) > max_total:
        available_papers = available_papers[:max_total]

    new_papers = available_papers

    if dedupe_enabled:
        _log(
            f"[INFO] New papers llm筛选出来: {len(new_papers)} (max_total={max_total})"
        )
    else:
        _log(
            f"[INFO] Dedupe disabled; selected {len(new_papers)} papers (max_total={max_total})."
        )
    _log(f"[INFO] Selected by source: {_source_breakdown(new_papers)}")

    api_key = ""
    ss_enabled = bool(ss_cfg.get("enabled", True)) and not skip_semantic_scholar
    if ss_enabled:
        api_key = (ss_cfg.get("api_key") or "").strip()
    enriched: list[Paper] = []
    if ss_enabled:
        _report_progress("semantic_enrich", "论文信息补全中（Semantic Scholar）")
    else:
        _report_progress("semantic_enrich", "跳过 Semantic Scholar 补全")
    for p in available_papers:
        if ss_enabled:
            try:
                _log(f"[INFO] Enriching (Semantic Scholar): {p.title[:80]}")
                enriched.append(
                    semantic_scholar_enrich(p, api_key=api_key, timeout_s=timeout_s)
                )
            except Exception as e:
                _log(f"[WARN] Semantic Scholar补全失败：{p.title[:60]} -> {e}")
                enriched.append(p)
        else:
            enriched.append(p)
        time.sleep(0.5)

    # 8) 可选摘要：仅对本次入选论文生成中文总结
    summaries: dict[str, dict[str, str]] = {}
    if skip_llm:
        summarize_limit = 0
    else:
        summarize_limit = int(llm_cfg.get("max_summaries") or len(enriched))
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
                    summaries[uid] = llm_summarize_zh(
                        p, llm_cfg, user_search_intent=profile
                    )
                except Exception as e:
                    _log(f"[WARN] LLM总结失败：{p.title[:60]} -> {e}")
                time.sleep(0.5)
    else:
        _report_progress("llm_summary", "跳过大模型总结")

    _report_progress("render_email", "整理邮件内容中")
    subject, text_body, html_body = build_email(run_date, enriched, summaries)

    if dry_run:
        print(subject)
        print(text_body)
        return

    email_sent = False
    if no_email:
        print("[INFO] no_email=True, content generated but email not sent.")
        _report_progress("skip_email", "仅生成内容，未发送邮件")
    else:
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
        if not isinstance(history, list):
            history = []
        for p in enriched:
            history.append(
                _paper_history_record(p, run_date, run_type=normalized_run_type)
            )

        if not dedupe_enabled:
            _log(
                "[INFO] Skip scheduled dedupe state update for manual dispatch."
            )
        else:
            for p in enriched:
                uid = _paper_uid(p)
                # Keep state TTL based on push date, not publication date.
                # Otherwise old papers are pruned immediately and can reappear daily.
                d = run_date.isoformat()
                seen[uid] = d
            state["seen_scheduled"] = seen
            state["seen"] = seen

        now_ts = dt.datetime.now().isoformat(timespec="seconds")
        state["push_history"] = _prune_push_history(
            history, history_keep_days, today=run_date
        )
        state["last_run"] = now_ts
        state["last_email_at"] = now_ts
        state["last_email_date"] = run_date.isoformat()
        if scheduled_dispatch:
            state["last_scheduled_email_date"] = run_date.isoformat()
        # 仅文件模式写回 JSON；数据库模式由外层服务持久化 state_override。
        if persist_state_to_file and state_override is None:
            _save_json(state_path, state)

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
        dry_run=args.dry_run,
        no_email=args.no_email,
        skip_llm=args.skip_llm,
        skip_semantic_scholar=args.skip_semantic_scholar,
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
