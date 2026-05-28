from __future__ import annotations

from app.paper_digest.fingerprints import (
    fingerprint,
    history_row_fingerprint,
    paper_fingerprint,
)
from app.paper_digest.retrieval import merge_duplicate_papers

from paper_digest.fixtures import make_paper


def test_fingerprint_prefers_stable_identifiers() -> None:
    assert fingerprint(doi="https://doi.org/10.1000/ABC", title="Ignored") == (
        "doi:10.1000/abc"
    )
    assert fingerprint(pmid="12345", arxiv_id="9999.1", title="Ignored") == (
        "pmid:12345"
    )
    assert fingerprint(arxiv_id="2501.00001V2", title="Ignored") == (
        "arxiv:2501.00001v2"
    )
    assert fingerprint(title="Reliable Paper Search!") == "title:reliablepapersearch"


def test_history_row_fingerprint_matches_delivered_paper() -> None:
    paper = make_paper(title="History Match", doi="10.1000/history")
    row = {
        "uid": "doi:10.1000/history",
        "doi": "https://doi.org/10.1000/history",
        "title": "History Match",
    }

    assert paper_fingerprint(paper) == history_row_fingerprint(row)


def test_merge_duplicate_papers_preserves_sources() -> None:
    first = make_paper(source="pubmed", doi="10.1000/merge", keywords=["a"])
    second = make_paper(source="semantic_scholar", doi="10.1000/merge", keywords=["b"])

    merged = merge_duplicate_papers([first, second])

    assert len(merged) == 1
    assert set(merged[0].source_provenance) == {"pubmed", "semantic_scholar"}
    assert merged[0].keywords == ["a", "b"]
