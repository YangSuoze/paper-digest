# Quickstart: Improve Paper Search Reliability

## Prerequisites

- Work from repository root: `/Users/yangjie/Documents/python_project/paper-digest`
- Use branch `001-improve-paper-search`
- Backend dependencies installed in `paper_digest_platform/backend`
- Frontend dependencies installed in `paper_digest_platform/frontend`
- SMTP settings configured if running an end-to-end digest email

## Implementation Entry Points

- Retrieval workflow: `paper_digest_platform/backend/app/paper_digest/workflow.py`
- Source retrieval and LLM helpers: `paper_digest_platform/backend/app/paper_digest/sources_and_llm.py`
- Shared paper utilities and state helpers: `paper_digest_platform/backend/app/paper_digest/core_utils.py`
- Dispatch bridge and manual task progress: `paper_digest_platform/backend/app/services/digest_service.py`
- Settings, state, logs, and paper record persistence: `paper_digest_platform/backend/app/services/settings_service.py`
- Push API schemas/routes: `paper_digest_platform/backend/app/schemas/push.py`, `paper_digest_platform/backend/app/api/routes_push.py`
- Frontend task/log/paper display: `paper_digest_platform/frontend/src/App.tsx`, `paper_digest_platform/frontend/src/types.ts`

## Validation Scenarios

1. Source isolation:
   - Stub one source to fail and another source to return candidates.
   - Verify the run completes as success or partial and records both the failure and successful source counts.

2. Zero-result explanation:
   - Stub all sources to return empty results.
   - Verify the run returns or logs a no-new-content explanation with searched window and per-source counts.

3. Bounded catch-up:
   - Seed user digest state with an older failed or missing successful run marker.
   - Verify the next scheduled run searches a bounded recovery window, not an unbounded historical range.

4. Deduplication:
   - Provide the same paper across two sources with the same DOI.
   - Provide another duplicate without identifiers but with a near-identical title.
   - Verify one delivered paper remains and provenance includes all contributing sources.

5. History suppression:
   - Seed `user_digest_state` or prior paper records with an already-delivered fingerprint.
   - Verify scheduled runs suppress the duplicate while still reporting the removal count.

6. Manual parity:
   - Submit `POST /api/v1/push/run-now`.
   - Poll `GET /api/v1/push/tasks/{task_id}`.
   - Verify diagnostics reflect the same pipeline behavior as scheduled runs.

7. API and frontend diagnostics:
   - Call `GET /api/v1/push/logs?limit=20` after a successful, partial, failed, or zero-result digest run.
   - Verify each digest log can include `diagnostics.counts`, `diagnostics.source_results`, and `diagnostics.zero_result_explanation`.
   - Call `GET /api/v1/push/papers?limit=20` after delivered results.
   - Verify paper records include `source_provenance` and the frontend history view renders provenance badges.

8. Existing data compatibility:
   - Use a database containing existing `user_settings`, `paper_records`, and `user_digest_state`.
   - Verify settings load, paper history displays, and digest state can be saved without manual repair.

## Suggested Commands

Backend syntax and tests:

```bash
python -m pytest paper_digest_platform/backend/tests
```

Frontend type/build checks:

```bash
cd paper_digest_platform/frontend
npm run typecheck
npm run build
```

Manual local server:

```bash
cd paper_digest_platform/backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Expected User-Visible Behavior

- Daily digest runs no longer produce unexplained repeated zero-paper days.
- When no papers are delivered, the user can see whether sources were empty, failed, filtered, or duplicate-only.
- Delivered papers show enough provenance to verify where they came from.
- Manual runs and scheduled runs use the same retrieval and diagnostics behavior.

## Data Safety Notes

- SQLite schema additions are additive and backward-compatible.
- Dispatch diagnostics are stored as JSON on new log rows and absent diagnostics are returned as `null`.
- Paper provenance is stored separately from the existing primary `source` field.
- Scheduled recovery windows are bounded so a long outage does not trigger an unbounded historical crawl or resend existing history.
