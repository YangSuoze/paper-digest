from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.paper_digest.core_utils import Paper
from app.paper_digest.diagnostics import (
    SearchRunDiagnostics,
    SourceResult,
    new_diagnostics,
)
from app.paper_digest.fingerprints import paper_fingerprint


SourceCallable = Callable[[], list[Paper]]


@dataclass
class RetrievalResult:
    papers: list[Paper]
    diagnostics: SearchRunDiagnostics


def _merge_keywords(left: list[str], right: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in [*left, *right]:
        clean = str(item or "").strip()
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            out.append(clean)
    return out


def _merge_sources(left: Paper, right: Paper) -> list[str]:
    sources = [
        *(left.source_provenance or []),
        left.source,
        *(right.source_provenance or []),
        right.source,
    ]
    seen: set[str] = set()
    out: list[str] = []
    for source in sources:
        clean = str(source or "").strip()
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            out.append(clean)
    return out


def _paper_with_source(paper: Paper, source: str) -> Paper:
    provenance = paper.source_provenance or [paper.source or source]
    if source and source not in provenance:
        provenance = [*provenance, source]
    return dataclasses.replace(
        paper,
        source=paper.source or source,
        source_provenance=provenance,
    )


def merge_paper_pair(primary: Paper, secondary: Paper) -> Paper:
    provenance = _merge_sources(primary, secondary)
    return dataclasses.replace(
        primary,
        title=primary.title or secondary.title,
        url=primary.url or secondary.url,
        venue=primary.venue or secondary.venue,
        published_date=primary.published_date or secondary.published_date,
        authors=primary.authors or secondary.authors,
        abstract=primary.abstract or secondary.abstract,
        publisher=primary.publisher or secondary.publisher,
        doi=primary.doi or secondary.doi,
        arxiv_id=primary.arxiv_id or secondary.arxiv_id,
        pdf_url=primary.pdf_url or secondary.pdf_url,
        keywords=_merge_keywords(primary.keywords, secondary.keywords),
        pmid=primary.pmid or secondary.pmid,
        source_provenance=provenance,
        relevance_score=max(primary.relevance_score, secondary.relevance_score),
        trust_signal=primary.trust_signal or secondary.trust_signal,
    )


def merge_duplicate_papers(papers: list[Paper]) -> list[Paper]:
    merged: dict[str, Paper] = {}
    passthrough: list[Paper] = []
    for paper in papers:
        fp = paper_fingerprint(paper)
        if not fp:
            passthrough.append(paper)
            continue
        if fp in merged:
            merged[fp] = merge_paper_pair(merged[fp], paper)
        else:
            merged[fp] = paper
    return [*merged.values(), *passthrough]


def run_source_searches(
    *,
    source_calls: Mapping[str, SourceCallable],
    run_type: str,
    since: Any,
    until: Any,
    recovery_reason: str,
    query_count: int = 0,
) -> RetrievalResult:
    diagnostics = new_diagnostics(
        run_type=run_type,
        window_start=since,
        window_end=until,
        recovery_reason=recovery_reason,
    )
    all_papers: list[Paper] = []

    for source, fn in source_calls.items():
        started = time.monotonic()
        try:
            papers = [_paper_with_source(p, source) for p in (fn() or [])]
        except TimeoutError as exc:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            diagnostics.source_results.append(
                SourceResult(
                    source=source,
                    status="timeout",
                    query_count=query_count,
                    error_message=str(exc),
                    elapsed_ms=elapsed_ms,
                )
            )
            continue
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            diagnostics.source_results.append(
                SourceResult(
                    source=source,
                    status="failed",
                    query_count=query_count,
                    error_message=str(exc),
                    elapsed_ms=elapsed_ms,
                )
            )
            continue

        elapsed_ms = int((time.monotonic() - started) * 1000)
        all_papers.extend(papers)
        diagnostics.source_results.append(
            SourceResult(
                source=source,
                status="success" if papers else "empty",
                query_count=query_count,
                raw_count=len(papers),
                candidate_count=len(papers),
                elapsed_ms=elapsed_ms,
            )
        )

    diagnostics.counts.raw_fetched = len(all_papers)
    diagnostics.counts.after_keyword_filter = len(all_papers)
    merged = merge_duplicate_papers(all_papers)
    diagnostics.counts.after_run_dedup = len(merged)
    return RetrievalResult(papers=merged, diagnostics=diagnostics)


def build_default_source_calls(
    *,
    keywords_list: list[list[str]],
    since: Any,
    until: Any,
    timeout_s: int = 30,
    pubmed_api_key: str = "",
    pubmed_email: str = "",
    semantic_scholar_api_key: str = "",
    openalex_mailto: str = "",
) -> dict[str, SourceCallable]:
    from app.paper_digest.sources_and_llm import (
        search_arxiv,
        search_crossref,
        search_openalex,
        search_pubmed,
        search_semantic_scholar,
    )

    return {
        "arxiv": lambda: search_arxiv(
            keywords_list=keywords_list,
            since=since,
            timeout_s=timeout_s,
        ),
        "crossref": lambda: search_crossref(
            keywords_list=keywords_list,
            rows=20,
            since=since,
            mailto="",
            publisher_substrings=[],
            types=[],
            timeout_s=timeout_s,
        ),
        "pubmed": lambda: search_pubmed(
            keywords_list=keywords_list,
            rows=20,
            since=since,
            until=until,
            timeout_s=timeout_s,
            api_key=pubmed_api_key,
            email=pubmed_email,
        ),
        "openalex": lambda: search_openalex(
            keywords_list=keywords_list,
            rows=50,
            since=since,
            until=until,
            timeout_s=timeout_s,
            mailto=openalex_mailto,
        ),
        "semantic_scholar": lambda: search_semantic_scholar(
            keywords_list=keywords_list,
            rows=50,
            since=since,
            until=until,
            timeout_s=timeout_s,
            api_key=semantic_scholar_api_key,
        ),
    }
