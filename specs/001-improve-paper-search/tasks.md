# Tasks: Improve Paper Search Reliability

**Input**: Design documents from `specs/001-improve-paper-search/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included because the implementation plan and quickstart require focused deterministic validation for source isolation, recovery windows, deduplication, diagnostics, and API response shape.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it touches different files and has no dependency on incomplete tasks.
- **[Story]**: Maps to the user story being implemented: US1, US2, or US3.
- Every task includes an exact file path.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Prepare deterministic tests and shared fixtures without changing runtime behavior.

- [X] T001 Add pytest as a backend test dependency in `paper_digest_platform/backend/requirements.txt`
- [X] T002 [P] Create pytest path/bootstrap fixtures in `paper_digest_platform/backend/tests/conftest.py`
- [X] T003 [P] Create reusable paper factories and source stubs in `paper_digest_platform/backend/tests/paper_digest/fixtures.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Add shared primitives for diagnostics, fingerprints, recovery windows, and source orchestration before any user story implementation.

**Critical**: No user story work should begin until this phase is complete.

- [X] T004 Create serializable search diagnostics models in `paper_digest_platform/backend/app/paper_digest/diagnostics.py`
- [X] T005 [P] Create DOI/PMID/arXiv/title fingerprint helpers in `paper_digest_platform/backend/app/paper_digest/fingerprints.py`
- [X] T006 [P] Create bounded scheduled/manual search window helpers in `paper_digest_platform/backend/app/paper_digest/windowing.py`
- [X] T007 Extend the Paper dataclass with optional PMID, source provenance, relevance, and trust fields in `paper_digest_platform/backend/app/paper_digest/core_utils.py`
- [X] T008 Add backward-compatible SQLite columns for dispatch diagnostics and paper provenance in `paper_digest_platform/backend/app/db/database.py`
- [X] T009 Add the retrieval pipeline skeleton that accepts source callables and returns papers plus diagnostics in `paper_digest_platform/backend/app/paper_digest/retrieval.py`
- [X] T010 Export the new diagnostics, fingerprint, windowing, and retrieval helpers from `paper_digest_platform/backend/app/paper_digest/__init__.py`

**Checkpoint**: Foundation ready. User story implementation can now begin.

---

## Phase 3: User Story 1 - Daily Search Returns Relevant Papers Reliably (Priority: P1) MVP

**Goal**: Daily and manual digest runs search multiple credible sources, survive single-source failures, return relevant papers when available, and produce a clear no-new-content result when sources are genuinely empty.

**Independent Test**: Stub one source to fail and another source to return relevant candidates, then verify the run completes with delivered papers and source-level diagnostics; stub all sources empty and verify a no-new-content explanation with source counts.

### Tests for User Story 1

- [X] T011 [P] [US1] Add source isolation unit tests in `paper_digest_platform/backend/tests/paper_digest/test_source_isolation.py`
- [X] T012 [P] [US1] Add no-new-content unit tests in `paper_digest_platform/backend/tests/paper_digest/test_no_new_content.py`
- [X] T013 [P] [US1] Add scheduled partial-success integration test in `paper_digest_platform/backend/tests/services/test_digest_source_isolation.py`

### Implementation for User Story 1

- [X] T014 [US1] Add OpenAlex and Semantic Scholar search functions that map source metadata into Paper objects in `paper_digest_platform/backend/app/paper_digest/sources_and_llm.py`
- [X] T015 [US1] Wire arXiv, Crossref, PubMed, OpenAlex, and Semantic Scholar callables into the source-isolated orchestrator in `paper_digest_platform/backend/app/paper_digest/retrieval.py`
- [X] T016 [US1] Replace inline source collection in daily workflow with the retrieval orchestrator in `paper_digest_platform/backend/app/paper_digest/workflow.py`
- [X] T017 [US1] Record raw, filtered, deduplicated, relevance-filtered, and delivered counts during daily selection in `paper_digest_platform/backend/app/paper_digest/workflow.py`
- [X] T018 [US1] Preserve merged source provenance in delivered paper history records in `paper_digest_platform/backend/app/paper_digest/core_utils.py`
- [X] T019 [US1] Render source breakdown and no-new-content search window text in digest emails in `paper_digest_platform/backend/app/paper_digest/rendering.py`
- [X] T020 [US1] Return source provenance in paper record API schemas in `paper_digest_platform/backend/app/schemas/push.py`
- [X] T021 [US1] Persist and read paper source provenance for paper records in `paper_digest_platform/backend/app/services/settings_service.py`
- [X] T022 [US1] Include diagnostics-aware delivered counts in dispatch success messages in `paper_digest_platform/backend/app/services/digest_service.py`

**Checkpoint**: US1 is independently functional. Scheduled and manual runs can retrieve papers from surviving sources or explain an empty result.

---

## Phase 4: User Story 2 - Search Recovers From Missed Or Failed Runs (Priority: P2)

**Goal**: The next successful scheduled run covers a bounded missed interval after failures or skipped runs without flooding the user or resending previously delivered papers.

**Independent Test**: Seed state with a missed or failed prior run, execute a scheduled search, and verify the bounded recovery window is used and already-delivered papers are suppressed.

### Tests for User Story 2

- [X] T023 [P] [US2] Add bounded catch-up window tests in `paper_digest_platform/backend/tests/paper_digest/test_windowing.py`
- [X] T024 [P] [US2] Add fingerprint merge and history suppression tests in `paper_digest_platform/backend/tests/paper_digest/test_fingerprints.py`
- [X] T025 [P] [US2] Add missed-run recovery integration test in `paper_digest_platform/backend/tests/services/test_digest_recovery.py`

### Implementation for User Story 2

- [X] T026 [US2] Store last successful search window and last failure markers in user digest state from `paper_digest_platform/backend/app/paper_digest/workflow.py`
- [X] T027 [US2] Use bounded window computation instead of fixed scheduled `days_back` in `paper_digest_platform/backend/app/paper_digest/workflow.py`
- [X] T028 [US2] Merge within-run duplicates by fingerprint while preserving best metadata and provenance in `paper_digest_platform/backend/app/paper_digest/retrieval.py`
- [X] T029 [US2] Suppress already-delivered scheduled papers by fingerprinted history in `paper_digest_platform/backend/app/paper_digest/workflow.py`
- [X] T030 [US2] Save state for successful zero-result and partial runs without adding empty paper history in `paper_digest_platform/backend/app/services/digest_service.py`
- [X] T031 [US2] Keep manual runs aligned with the same retrieval pipeline while preserving manual history behavior in `paper_digest_platform/backend/app/services/digest_service.py`

**Checkpoint**: US2 is independently functional. Recovery windows are bounded and duplicates are suppressed across overlapping runs.

---

## Phase 5: User Story 3 - Users Can Diagnose Search Quality (Priority: P3)

**Goal**: Users and operators can see why a run returned zero or few papers through task status, dispatch logs, paper records, and the frontend history view.

**Independent Test**: Run a zero-result search and verify API responses and the frontend-visible run history show source counts, filtering counts, duplicate counts, failures, and the zero-result reason.

### Tests for User Story 3

- [X] T032 [P] [US3] Add manual task diagnostics contract test in `paper_digest_platform/backend/tests/api/test_push_task_diagnostics.py`
- [X] T033 [P] [US3] Add dispatch log diagnostics contract test in `paper_digest_platform/backend/tests/api/test_push_log_diagnostics.py`
- [X] T034 [P] [US3] Add zero-result persistence integration test in `paper_digest_platform/backend/tests/services/test_digest_diagnostics.py`

### Implementation for User Story 3

- [X] T035 [US3] Add SearchRunDiagnostics, SourceResult, SearchRunCounts, and ZeroResultExplanation response schemas in `paper_digest_platform/backend/app/schemas/push.py`
- [X] T036 [US3] Write and parse dispatch diagnostics JSON in `paper_digest_platform/backend/app/services/settings_service.py`
- [X] T037 [US3] Attach live diagnostics to manual task status updates in `paper_digest_platform/backend/app/services/digest_service.py`
- [X] T038 [US3] Return diagnostics from push task and log endpoints in `paper_digest_platform/backend/app/api/routes_push.py`
- [X] T039 [US3] Add frontend diagnostics and provenance TypeScript interfaces in `paper_digest_platform/frontend/src/types.ts`
- [X] T040 [US3] Render source counts, filter counts, failure text, and zero-result explanations in `paper_digest_platform/frontend/src/App.tsx`
- [X] T041 [US3] Add responsive styles for diagnostics rows and badges in `paper_digest_platform/frontend/src/styles.css`
- [X] T042 [US3] Align the OpenAPI contract with implemented diagnostics fields in `specs/001-improve-paper-search/contracts/push-diagnostics.openapi.yaml`

**Checkpoint**: US3 is independently functional. Users can diagnose zero-result and low-result runs without reading backend logs.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, validation, and final consistency checks across all implemented stories.

- [X] T043 [P] Document the new retrieval diagnostics and recovery behavior in `paper_digest_platform/backend/README.md`
- [X] T044 [P] Update validation notes and any command changes in `specs/001-improve-paper-search/quickstart.md`
- [X] T045 Run backend pytest and fix failures in `paper_digest_platform/backend/tests/`
- [X] T046 Run frontend typecheck/build and fix failures in `paper_digest_platform/frontend/src/`
- [X] T047 Review final API schema consistency between backend schemas and `specs/001-improve-paper-search/contracts/push-diagnostics.openapi.yaml`
- [X] T048 Verify no implementation changes overwrite existing user settings, paper records, or digest state in `paper_digest_platform/backend/app/services/settings_service.py`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup and blocks all user stories.
- **US1 (Phase 3)**: Depends on Foundational. This is the MVP.
- **US2 (Phase 4)**: Depends on Foundational and can start after US1 retrieval primitives are stable.
- **US3 (Phase 5)**: Depends on Foundational and can start after diagnostics objects exist; frontend rendering benefits from US1/US2 fields.
- **Polish (Phase 6)**: Depends on all selected user stories.

### User Story Dependencies

- **US1**: No dependency on US2 or US3 after Foundational.
- **US2**: Uses the same retrieval and fingerprint primitives; can be developed after or alongside US1 once `retrieval.py` interfaces are stable.
- **US3**: Uses diagnostics emitted by US1/US2; API and frontend work can proceed once diagnostics schema is fixed.

### Within Each User Story

- Write story tests first and confirm they fail against current behavior.
- Implement domain helpers before workflow/service integration.
- Integrate backend behavior before frontend consumption.
- Validate each story at its checkpoint before proceeding.

## Parallel Opportunities

- Setup tasks T002 and T003 can run in parallel.
- Foundational tasks T005 and T006 can run in parallel after T004 is understood.
- US1 tests T011, T012, and T013 can be written in parallel.
- US2 tests T023, T024, and T025 can be written in parallel.
- US3 tests T032, T033, and T034 can be written in parallel.
- US3 frontend tasks T039, T040, and T041 can proceed in parallel with backend API tasks after the schema in T035 is stable.
- Polish documentation tasks T043 and T044 can run in parallel.

## Parallel Example: User Story 1

```text
Task: "T011 Add source isolation unit tests in paper_digest_platform/backend/tests/paper_digest/test_source_isolation.py"
Task: "T012 Add no-new-content unit tests in paper_digest_platform/backend/tests/paper_digest/test_no_new_content.py"
Task: "T013 Add scheduled partial-success integration test in paper_digest_platform/backend/tests/services/test_digest_source_isolation.py"
```

## Parallel Example: User Story 2

```text
Task: "T023 Add bounded catch-up window tests in paper_digest_platform/backend/tests/paper_digest/test_windowing.py"
Task: "T024 Add fingerprint merge and history suppression tests in paper_digest_platform/backend/tests/paper_digest/test_fingerprints.py"
Task: "T025 Add missed-run recovery integration test in paper_digest_platform/backend/tests/services/test_digest_recovery.py"
```

## Parallel Example: User Story 3

```text
Task: "T032 Add manual task diagnostics contract test in paper_digest_platform/backend/tests/api/test_push_task_diagnostics.py"
Task: "T033 Add dispatch log diagnostics contract test in paper_digest_platform/backend/tests/api/test_push_log_diagnostics.py"
Task: "T034 Add zero-result persistence integration test in paper_digest_platform/backend/tests/services/test_digest_diagnostics.py"
```

## Implementation Strategy

### MVP First (US1 Only)

1. Complete Phase 1 setup tasks.
2. Complete Phase 2 foundational primitives.
3. Complete Phase 3 US1 tasks.
4. Stop and validate source isolation, multi-source retrieval, source provenance, and no-new-content digest behavior.

### Incremental Delivery

1. Deliver US1 to address repeated daily zero-result failures.
2. Add US2 to protect missed-run recovery and duplicate suppression.
3. Add US3 to make search quality visible in API responses and the frontend.
4. Finish polish tasks and run backend/frontend validation.

### Parallel Team Strategy

1. One developer owns retrieval primitives in `paper_digest_platform/backend/app/paper_digest/`.
2. One developer owns service/API persistence in `paper_digest_platform/backend/app/services/`, `paper_digest_platform/backend/app/api/`, and `paper_digest_platform/backend/app/schemas/`.
3. One developer owns frontend diagnostics in `paper_digest_platform/frontend/src/`.
4. Tests can be split by story under `paper_digest_platform/backend/tests/`.

## Notes

- Keep existing user settings, paper records, and digest state backward compatible.
- Do not replace the platform with the standalone Academic-Radar runner.
- Preserve bibliographic metadata from source data; do not let LLM output invent title, authors, DOI, venue, or publication date.
- Commit after each completed story or logical group if using the git extension hook.
