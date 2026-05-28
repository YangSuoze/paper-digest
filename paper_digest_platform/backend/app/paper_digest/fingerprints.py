from __future__ import annotations

import re
from typing import Any


def normalize_doi(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text)
    text = re.sub(r"^doi:\s*", "", text)
    return text.strip()


def normalize_identifier(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_title(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def fingerprint(
    *,
    doi: Any = "",
    pmid: Any = "",
    arxiv_id: Any = "",
    title: Any = "",
) -> str:
    doi_norm = normalize_doi(doi)
    if doi_norm:
        return f"doi:{doi_norm}"
    pmid_norm = str(pmid or "").strip()
    if pmid_norm:
        return f"pmid:{pmid_norm}"
    arxiv_norm = normalize_identifier(arxiv_id)
    if arxiv_norm:
        return f"arxiv:{arxiv_norm}"
    title_norm = normalize_title(title)
    if title_norm:
        return f"title:{title_norm}"
    return ""


def paper_fingerprint(paper: Any) -> str:
    return fingerprint(
        doi=getattr(paper, "doi", ""),
        pmid=getattr(paper, "pmid", ""),
        arxiv_id=getattr(paper, "arxiv_id", ""),
        title=getattr(paper, "title", ""),
    )


def history_row_fingerprint(row: dict[str, Any]) -> str:
    return fingerprint(
        doi=row.get("doi", ""),
        pmid=row.get("pmid", ""),
        arxiv_id=row.get("arxiv_id", ""),
        title=row.get("title", ""),
    )
