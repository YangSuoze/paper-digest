from __future__ import annotations

import asyncio

from app.services.digest_service import DigestDispatchService


class _Settings:
    def __init__(self) -> None:
        self.saved_state: dict | None = None
        self.logs: list[dict] = []
        self.records: list[dict] = []

    async def get_user_dispatch_profile(self, user_id: int) -> dict:
        return {
            "target_email": "user@example.test",
            "active": 1,
            "keywords_list": [["wearable", "sensor"]],
            "user_search_intent": "wearable sensor",
        }

    async def get_user_digest_state(self, user_id: int) -> dict:
        return {}

    async def save_user_digest_state(self, user_id: int, state: dict) -> None:
        self.saved_state = dict(state)

    async def add_paper_records(
        self,
        user_id: int,
        run_type: str,
        records: list[dict],
    ) -> int:
        self.records.extend(records)
        return len(records)

    async def add_dispatch_log(
        self,
        user_id: int,
        run_type: str,
        status: str,
        message: str,
        diagnostics: dict | None = None,
    ) -> None:
        self.logs.append(
            {
                "user_id": user_id,
                "run_type": run_type,
                "status": status,
                "message": message,
                "diagnostics": diagnostics,
            }
        )


class _Email:
    pass


def _zero_diagnostics() -> dict:
    return {
        "run_id": "zero-run",
        "run_type": "scheduled",
        "window_start": "2026-05-21",
        "window_end": "2026-05-28",
        "recovery_reason": "normal",
        "counts": {
            "raw_fetched": 0,
            "after_keyword_filter": 0,
            "after_run_dedup": 0,
            "after_history_dedup": 0,
            "after_relevance_filter": 0,
            "delivered": 0,
        },
        "source_results": [
            {
                "source": "pubmed",
                "status": "empty",
                "query_count": 1,
                "raw_count": 0,
                "candidate_count": 0,
                "error_message": "",
                "elapsed_ms": 1,
            }
        ],
        "zero_result_explanation": {
            "reason": "no_source_hits",
            "message": "没有命中。",
            "filter_summary": "raw=0",
        },
    }


def test_zero_result_diagnostics_are_persisted(monkeypatch) -> None:
    async def _run() -> None:
        settings = _Settings()
        service = DigestDispatchService(settings_service=settings, email_service=_Email())

        def _run_agent(**kwargs):
            state = kwargs["state_snapshot"]
            state["last_search_diagnostics"] = _zero_diagnostics()
            state["last_search_window"] = {
                "since": "2026-05-21",
                "until": "2026-05-28",
                "recovery_reason": "normal",
            }
            state["push_history"] = []
            state["last_successful_search_date"] = "2026-05-28"
            state["last_successful_scheduled_search_date"] = "2026-05-28"

        monkeypatch.setattr(service, "_run_agent_with_runtime_config", _run_agent)
        monkeypatch.setattr(
            service,
            "_shared_smtp_cfg",
            lambda: {
                "smtp_host": "smtp.example.test",
                "username": "smtp-user",
                "password": "secret",
                "from": "noreply@example.test",
            },
        )

        message = await service.trigger_user_digest(user_id=42, run_type="scheduled")

        assert "delivered=0" in message
        assert settings.saved_state is not None
        assert settings.saved_state["last_search_diagnostics"][
            "zero_result_explanation"
        ]["reason"] == "no_source_hits"
        assert settings.records == []
        assert settings.logs[0]["diagnostics"]["run_id"] == "zero-run"

    asyncio.run(_run())
