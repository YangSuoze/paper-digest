from __future__ import annotations

import datetime as dt

from app.paper_digest import workflow

from paper_digest.fixtures import make_paper


def test_scheduled_run_uses_recovery_window_and_suppresses_history(monkeypatch) -> None:
    state: dict = {
        "last_successful_scheduled_search_date": "2026-04-01",
        "push_history": [
            {
                "uid": "doi:10.1000/old",
                "doi": "10.1000/old",
                "push_date": "2026-04-01",
                "run_type": "scheduled",
                "title": "Already Delivered",
            }
        ],
    }
    captured: dict = {}
    sent: list[tuple[str, str, str]] = []

    monkeypatch.setattr(workflow, "_today_local", lambda: dt.date(2026, 5, 28))
    monkeypatch.setattr(workflow, "send_email", lambda cfg, subject, text, html: sent.append((subject, text, html)))
    monkeypatch.setattr(workflow, "llm_preference_rerank", lambda papers, profile: (papers, {"applied": False}))
    monkeypatch.setattr(workflow, "LLMClient", None)

    def _source_calls(**kwargs):
        captured.update(kwargs)
        return {
            "pubmed": lambda: [
                make_paper(title="Already Delivered", doi="10.1000/old"),
                make_paper(title="Fresh Recovery Paper", doi="10.1000/fresh"),
            ]
        }

    monkeypatch.setattr(workflow, "build_default_source_calls", _source_calls)

    workflow.run_once(
        skip_llm=True,
        shared={"to": ["user@example.test"]},
        keywords_list=[["wearable", "sensor"]],
        state_override=state,
        dispatch_run_type="scheduled",
    )

    assert captured["since"] == dt.date(2026, 5, 7)
    assert captured["until"] == dt.date(2026, 5, 28)
    assert sent
    diagnostics = state["last_search_diagnostics"]
    assert diagnostics["recovery_reason"] == "missed_run"
    assert diagnostics["counts"]["after_run_dedup"] == 2
    assert diagnostics["counts"]["after_history_dedup"] == 1
    assert diagnostics["counts"]["delivered"] == 1
    assert "doi:10.1000/fresh" in state["seen_scheduled"]
