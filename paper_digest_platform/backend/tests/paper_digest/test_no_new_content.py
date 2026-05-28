from __future__ import annotations

import datetime as dt

from app.paper_digest.diagnostics import explain_zero_result
from app.paper_digest.retrieval import run_source_searches


def test_zero_result_explains_empty_sources() -> None:
    result = run_source_searches(
        source_calls={
            "arxiv": lambda: [],
            "pubmed": lambda: [],
            "openalex": lambda: [],
        },
        run_type="scheduled",
        since=dt.date(2026, 5, 1),
        until=dt.date(2026, 5, 8),
        recovery_reason="normal",
        query_count=1,
    )

    result.diagnostics.counts.after_history_dedup = 0
    result.diagnostics.counts.after_relevance_filter = 0
    result.diagnostics.counts.delivered = 0
    explanation = explain_zero_result(result.diagnostics)

    assert explanation.reason == "no_source_hits"
    assert "当前时间窗口" in explanation.message
    assert "arxiv:empty/0" in explanation.filter_summary


def test_zero_result_explains_duplicates_only() -> None:
    result = run_source_searches(
        source_calls={
            "pubmed": lambda: [],
        },
        run_type="scheduled",
        since=dt.date(2026, 5, 1),
        until=dt.date(2026, 5, 8),
        recovery_reason="normal",
        query_count=1,
    )
    result.diagnostics.counts.raw_fetched = 3
    result.diagnostics.counts.after_run_dedup = 2
    result.diagnostics.counts.after_history_dedup = 0
    result.diagnostics.counts.after_relevance_filter = 0
    result.diagnostics.counts.delivered = 0

    explanation = explain_zero_result(result.diagnostics)

    assert explanation.reason == "duplicates_only"
    assert "已在近期推送过" in explanation.message
