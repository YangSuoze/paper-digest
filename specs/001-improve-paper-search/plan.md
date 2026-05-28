# Implementation Plan: Improve Paper Search Reliability

**Branch**: `001-improve-paper-search` | **Date**: 2026-05-28 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-improve-paper-search/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

Refactor the paper retrieval pipeline so daily and manual digest runs stop failing silently or producing repeated unexplained zero-paper results. The implementation will keep the current FastAPI + SQLite + React platform shape, but replace the brittle source aggregation flow with a source-isolated, stats-producing retrieval pipeline inspired by Academic-Radar: multi-source discovery, bounded catch-up windows, relevance filtering, within-run and cross-run deduplication, provenance preservation, and user-readable zero-result diagnostics.

## Technical Context

**Language/Version**: Python 3.12.12 backend; TypeScript 5.5 frontend

**Primary Dependencies**: FastAPI, aiosqlite, APScheduler, Pydantic settings, requests, OpenAI-compatible LLM client, React 18, Vite

**Storage**: SQLite database at `paper_digest_platform/runtime/paper_digest_platform.db`; existing JSON state in `user_digest_state.state_json`; optional schema additions for run diagnostics

**Testing**: Backend pytest-style tests for retrieval pipeline units and service integration; frontend `npm run typecheck` and `npm run build`

**Target Platform**: Long-running local or server-hosted web service with scheduled background jobs and browser frontend

**Project Type**: Web application with FastAPI backend, React frontend, and background scheduled digest workflow

**Performance Goals**: Manual search returns a final digest or no-new-content explanation within 5 minutes for normal daily workloads; daily scheduled runs complete without blocking other users beyond existing dispatch concurrency controls

**Constraints**: Source failures must be isolated; no unbounded historical retrieval after downtime; existing user settings, paper records, and digest state must remain usable; bibliographic metadata must come from source data rather than LLM generation

**Scale/Scope**: Multi-user digest platform with per-user scheduled/manual runs, current paper sources in `app/paper_digest`, and a focused diagnostics surface in existing push logs/tasks/pages

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The constitution file is still the generated placeholder and defines no concrete enforceable gates. Planning therefore proceeds with the project-local quality expectations implied by the codebase:

- Preserve existing user data and workflows.
- Keep implementation scoped to the paper digest retrieval, state, records, and diagnostics surfaces.
- Add focused tests around retrieval, deduplication, recovery windows, and API response shape.

Initial gate result: PASS. No constitution violations identified.

## Project Structure

### Documentation (this feature)

```text
specs/001-improve-paper-search/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── push-diagnostics.openapi.yaml
└── tasks.md
```

### Source Code (repository root)

```text
paper_digest_platform/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── routes_push.py
│   │   ├── db/
│   │   │   └── database.py
│   │   ├── schemas/
│   │   │   └── push.py
│   │   ├── services/
│   │   │   ├── digest_service.py
│   │   │   └── settings_service.py
│   │   └── paper_digest/
│   │       ├── workflow.py
│   │       ├── sources_and_llm.py
│   │       ├── core_utils.py
│   │       └── rendering.py
│   └── requirements.txt
└── frontend/
    ├── src/
    │   ├── App.tsx
    │   ├── api.ts
    │   └── types.ts
    └── package.json
```

**Structure Decision**: Use the existing web application layout. The backend paper digest workflow remains under `paper_digest_platform/backend/app/paper_digest`, dispatch/state persistence remains under `app/services`, API schemas/routes remain under `app/schemas` and `app/api`, and the frontend only consumes expanded diagnostics fields from the existing push views.

## Complexity Tracking

No constitution violations or additional projects are planned. Complexity stays within the existing backend/frontend boundaries.

## Phase 0: Research

See [research.md](./research.md).

Key resolved decisions:

- Use source adapters with isolated failure handling rather than a single all-or-nothing retrieval path.
- Use a bounded catch-up search window based on last successful run state rather than fixed `days_back` only.
- Use stable paper fingerprints, source provenance, and richer per-run stats before LLM filtering.
- Preserve current SQLite state/records while adding diagnostics in a backward-compatible way.

## Phase 1: Design & Contracts

See [data-model.md](./data-model.md), [quickstart.md](./quickstart.md), and [contracts/push-diagnostics.openapi.yaml](./contracts/push-diagnostics.openapi.yaml).

Planned design outputs:

- Retrieval pipeline entities for search run diagnostics, source results, candidate papers, delivered papers, fingerprints, and zero-result explanations.
- API contract additions for run diagnostics exposed through push logs/tasks without breaking existing fields.
- Verification flow covering unit tests, integration scenarios, and frontend type/build checks.

## Constitution Check Post-Design

Post-design gate result: PASS.

The design keeps the work scoped to existing modules, preserves existing data, adds testable diagnostics and recovery behavior, and avoids new projects or broad architectural churn.
