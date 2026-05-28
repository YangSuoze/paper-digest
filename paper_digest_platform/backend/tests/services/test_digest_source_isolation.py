from __future__ import annotations

import datetime as dt

from app.paper_digest import workflow

from paper_digest.fixtures import make_paper


def test_scheduled_run_records_partial_source_diagnostics(monkeypatch) -> None:
    state: dict = {}
    sent: list[tuple[str, str, str]] = []

    monkeypatch.setattr(workflow, "_today_local", lambda: dt.date(2026, 5, 28))
    monkeypatch.setattr(workflow, "send_email", lambda cfg, subject, text, html: sent.append((subject, text, html)))
    monkeypatch.setattr(workflow, "llm_preference_rerank", lambda papers, profile: (papers, {"applied": False}))
    monkeypatch.setattr(workflow, "llm_summarize_zh", lambda paper, user_search_intent="": {})
    monkeypatch.setattr(workflow, "LLMClient", None)
    monkeypatch.setattr(
        workflow,
        "build_default_source_calls",
        lambda **kwargs: {
            "crossref": lambda: (_ for _ in ()).throw(RuntimeError("crossref down")),
            "pubmed": lambda: [
                make_paper(
                    title="Surviving Paper",
                    source="pubmed",
                    doi="10.1000/survive",
                )
            ],
        },
    )

    workflow.run_once(
        skip_llm=True,
        shared={"to": ["user@example.test"]},
        keywords_list=[["wearable", "sensor"]],
        state_override=state,
        dispatch_run_type="scheduled",
    )

    assert sent
    diagnostics = state["last_search_diagnostics"]
    assert diagnostics["counts"]["delivered"] == 1
    assert diagnostics["counts"]["after_history_dedup"] == 1
    by_source = {item["source"]: item for item in diagnostics["source_results"]}
    assert by_source["crossref"]["status"] == "failed"
    assert by_source["pubmed"]["status"] == "success"
    assert state["last_successful_scheduled_search_date"] == "2026-05-28"
    assert "doi:10.1000/survive" in state["seen_scheduled"]
