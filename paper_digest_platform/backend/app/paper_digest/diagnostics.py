from __future__ import annotations

import dataclasses
import datetime as dt
import uuid
from dataclasses import dataclass, field
from typing import Any


def _date_text(value: dt.date | dt.datetime | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return str(value)


@dataclass
class SearchRunCounts:
    raw_fetched: int = 0
    after_keyword_filter: int = 0
    after_run_dedup: int = 0
    after_history_dedup: int = 0
    after_relevance_filter: int = 0
    delivered: int = 0

    def to_dict(self) -> dict[str, int]:
        return dataclasses.asdict(self)


@dataclass
class SourceResult:
    source: str
    status: str
    query_count: int = 0
    raw_count: int = 0
    candidate_count: int = 0
    error_message: str = ""
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class ZeroResultExplanation:
    reason: str
    message: str
    filter_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class SearchRunDiagnostics:
    run_type: str
    window_start: str
    window_end: str
    recovery_reason: str = "normal"
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    counts: SearchRunCounts = field(default_factory=SearchRunCounts)
    source_results: list[SourceResult] = field(default_factory=list)
    zero_result_explanation: ZeroResultExplanation | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_type": self.run_type,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "recovery_reason": self.recovery_reason,
            "counts": self.counts.to_dict(),
            "source_results": [item.to_dict() for item in self.source_results],
            "zero_result_explanation": (
                self.zero_result_explanation.to_dict()
                if self.zero_result_explanation
                else None
            ),
        }


def new_diagnostics(
    *,
    run_type: str,
    window_start: dt.date | dt.datetime | str,
    window_end: dt.date | dt.datetime | str,
    recovery_reason: str = "normal",
) -> SearchRunDiagnostics:
    return SearchRunDiagnostics(
        run_type=str(run_type or "").strip() or "scheduled",
        window_start=_date_text(window_start),
        window_end=_date_text(window_end),
        recovery_reason=str(recovery_reason or "").strip() or "normal",
    )


def explain_zero_result(diagnostics: SearchRunDiagnostics) -> ZeroResultExplanation:
    counts = diagnostics.counts
    failed_sources = [
        s for s in diagnostics.source_results if s.status in {"failed", "timeout"}
    ]
    successful_sources = [
        s for s in diagnostics.source_results if s.status in {"success", "empty"}
    ]
    all_failed = diagnostics.source_results and len(failed_sources) == len(
        diagnostics.source_results
    )

    if all_failed:
        reason = "all_sources_failed"
        message = "所有检索来源本次都失败，未能完成有效论文检索。"
    elif counts.raw_fetched == 0:
        reason = "no_source_hits"
        message = "已完成检索，但所有可用来源在当前时间窗口内都没有返回候选论文。"
    elif counts.after_history_dedup == 0 and counts.after_run_dedup > 0:
        reason = "duplicates_only"
        message = "检索到的候选论文均已在近期推送过，本次没有新增论文。"
    elif counts.after_relevance_filter == 0 and counts.after_history_dedup > 0:
        reason = "no_relevant_after_ranking"
        message = "候选论文存在，但经过用户研究方向相关性筛选后没有保留项。"
    else:
        reason = "filtered_out"
        message = "候选论文经过过滤、去重和排序后没有剩余可推送项。"

    source_bits = [
        f"{item.source}:{item.status}/{item.candidate_count}"
        for item in diagnostics.source_results
    ]
    filter_summary = (
        f"raw={counts.raw_fetched}, run_dedup={counts.after_run_dedup}, "
        f"history={counts.after_history_dedup}, relevant={counts.after_relevance_filter}; "
        f"sources={', '.join(source_bits) if source_bits else 'none'}"
    )
    if failed_sources and successful_sources:
        message += " 部分来源失败，但其他来源已正常完成。"

    return ZeroResultExplanation(
        reason=reason,
        message=message,
        filter_summary=filter_summary,
    )
