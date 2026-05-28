from __future__ import annotations

import datetime as dt

from app.paper_digest.retrieval import run_source_searches

from paper_digest.fixtures import make_paper, source_fails, source_returns


def test_run_source_searches_keeps_successful_source_when_another_fails() -> None:
    paper = make_paper(
        title="Recovered Source Paper",
        source="pubmed",
        doi="10.1000/recovered",
    )

    result = run_source_searches(
        source_calls={
            "crossref": source_fails("crossref unavailable"),
            "pubmed": source_returns("pubmed", [paper]),
        },
        run_type="scheduled",
        since=dt.date(2026, 5, 1),
        until=dt.date(2026, 5, 8),
        recovery_reason="normal",
        query_count=1,
    )

    assert [p.title for p in result.papers] == ["Recovered Source Paper"]
    assert result.diagnostics.counts.raw_fetched == 1
    assert result.diagnostics.counts.after_run_dedup == 1

    by_source = {item.source: item for item in result.diagnostics.source_results}
    assert by_source["crossref"].status == "failed"
    assert "crossref unavailable" in by_source["crossref"].error_message
    assert by_source["pubmed"].status == "success"
    assert by_source["pubmed"].candidate_count == 1


def test_run_source_searches_merges_duplicate_provenance() -> None:
    pubmed = make_paper(
        title="Same DOI Paper",
        source="pubmed",
        doi="10.1000/same",
        keywords=["blood pressure"],
    )
    openalex = make_paper(
        title="Same DOI Paper",
        source="openalex",
        doi="https://doi.org/10.1000/same",
        keywords=["wearable sensor"],
    )

    result = run_source_searches(
        source_calls={
            "pubmed": source_returns("pubmed", [pubmed]),
            "openalex": source_returns("openalex", [openalex]),
        },
        run_type="scheduled",
        since=dt.date(2026, 5, 1),
        until=dt.date(2026, 5, 8),
        recovery_reason="normal",
        query_count=2,
    )

    assert len(result.papers) == 1
    merged = result.papers[0]
    assert set(merged.source_provenance) == {"pubmed", "openalex"}
    assert merged.keywords == ["blood pressure", "wearable sensor"]
    assert result.diagnostics.counts.raw_fetched == 2
    assert result.diagnostics.counts.after_run_dedup == 1
