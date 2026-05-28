from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_dispatch_service
from app.api.router import api_router
from app.services.auth_service import UserIdentity


class _Dispatch:
    async def list_user_logs(self, user_id: int, limit: int = 20) -> list[dict]:
        assert user_id == 7
        return [
            {
                "id": 1,
                "run_type": "scheduled",
                "status": "success",
                "message": "推送成功",
                "created_at": "2026-05-28T00:00:00Z",
                "diagnostics": {
                    "run_id": "run-log",
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
                            "source": "openalex",
                            "status": "empty",
                            "query_count": 1,
                            "raw_count": 0,
                            "candidate_count": 0,
                            "error_message": "",
                            "elapsed_ms": 5,
                        }
                    ],
                    "zero_result_explanation": {
                        "reason": "no_source_hits",
                        "message": "没有返回候选论文。",
                        "filter_summary": "raw=0",
                    },
                },
            }
        ]


def test_dispatch_logs_return_diagnostics() -> None:
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: UserIdentity(
        id=7,
        username="tester",
        email="tester@example.test",
    )
    app.dependency_overrides[get_dispatch_service] = lambda: _Dispatch()

    response = TestClient(app).get(
        "/api/v1/push/logs",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["diagnostics"]["zero_result_explanation"]["reason"] == "no_source_hits"
    assert payload[0]["diagnostics"]["source_results"][0]["status"] == "empty"
