from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_dispatch_service
from app.api.router import api_router
from app.services.auth_service import UserIdentity
from fastapi import FastAPI


def _diagnostics() -> dict:
    return {
        "run_id": "run-task",
        "run_type": "manual_digest",
        "window_start": "2026-05-01",
        "window_end": "2026-05-28",
        "recovery_reason": "manual_extended",
        "counts": {
            "raw_fetched": 2,
            "after_keyword_filter": 2,
            "after_run_dedup": 1,
            "after_history_dedup": 1,
            "after_relevance_filter": 0,
            "delivered": 0,
        },
        "source_results": [
            {
                "source": "pubmed",
                "status": "success",
                "query_count": 1,
                "raw_count": 2,
                "candidate_count": 2,
                "error_message": "",
                "elapsed_ms": 12,
            }
        ],
        "zero_result_explanation": {
            "reason": "no_relevant_after_ranking",
            "message": "候选论文存在，但相关性筛选后没有保留项。",
            "filter_summary": "raw=2, run_dedup=1",
        },
    }


class _Dispatch:
    def get_manual_digest_task(self, *, user_id: int, task_id: str) -> dict | None:
        assert user_id == 7
        assert task_id == "task-1"
        return {
            "task_id": "task-1",
            "run_type": "manual_digest",
            "status": "success",
            "progress_stage": "completed",
            "progress_message": "执行完成",
            "result_message": "推送成功",
            "error_message": "",
            "created_at": "2026-05-28T00:00:00Z",
            "updated_at": "2026-05-28T00:00:10Z",
            "started_at": "2026-05-28T00:00:01Z",
            "finished_at": "2026-05-28T00:00:10Z",
            "diagnostics": _diagnostics(),
        }


def test_get_manual_task_status_returns_diagnostics() -> None:
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: UserIdentity(
        id=7,
        username="tester",
        email="tester@example.test",
    )
    app.dependency_overrides[get_dispatch_service] = lambda: _Dispatch()

    response = TestClient(app).get(
        "/api/v1/push/tasks/task-1",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["diagnostics"]["counts"]["delivered"] == 0
    assert payload["diagnostics"]["source_results"][0]["source"] == "pubmed"
    assert (
        payload["diagnostics"]["zero_result_explanation"]["reason"]
        == "no_relevant_after_ranking"
    )
