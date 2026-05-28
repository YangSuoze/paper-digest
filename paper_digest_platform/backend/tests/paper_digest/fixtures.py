from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from app.paper_digest.core_utils import Paper


def make_paper(
    *,
    title: str = "Reliable Paper Search for Medical AI",
    source: str = "pubmed",
    url: str = "https://example.test/paper",
    doi: str = "",
    pmid: str = "",
    arxiv_id: str = "",
    published_date: dt.date | None = None,
    keywords: list[str] | None = None,
    source_provenance: list[str] | None = None,
) -> Paper:
    return Paper(
        source=source,
        title=title,
        url=url,
        venue="Journal of Tests",
        published_date=published_date or dt.date(2026, 5, 20),
        authors=["Ada Test"],
        abstract="A deterministic paper fixture for retrieval tests.",
        publisher="Test Publisher",
        doi=doi,
        arxiv_id=arxiv_id,
        pdf_url="",
        keywords=keywords or ["medical ai"],
        pmid=pmid,
        source_provenance=source_provenance or [source],
    )


def source_returns(
    source: str,
    papers: list[Paper],
) -> Callable[[], list[Paper]]:
    def _runner() -> list[Paper]:
        return [
            paper
            if paper.source == source
            else make_paper(
                title=paper.title,
                source=source,
                url=paper.url,
                doi=paper.doi,
                pmid=paper.pmid,
                arxiv_id=paper.arxiv_id,
                published_date=paper.published_date,
                keywords=paper.keywords,
                source_provenance=[source],
            )
            for paper in papers
        ]

    return _runner


def source_fails(message: str = "source failed") -> Callable[[], list[Paper]]:
    def _runner() -> list[Paper]:
        raise RuntimeError(message)

    return _runner
