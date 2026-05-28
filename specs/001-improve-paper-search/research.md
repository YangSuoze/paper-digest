# Phase 0 Research: Improve Paper Search Reliability

## Decision: Keep the existing FastAPI/SQLite/React platform shape

**Rationale**: The current project already has a multi-user web platform, scheduled dispatch service, manual run task model, SQLite persistence, and frontend history views. The requested change is a retrieval-quality refactor, not a platform replacement. Keeping the existing shape reduces migration risk and preserves user settings, paper records, and digest state.

**Alternatives considered**:

- Replace the current workflow with the Academic-Radar standalone runner. Rejected because it would bypass the platform's per-user settings, authentication, state storage, logs, and frontend task polling.
- Build a separate retrieval microservice. Rejected because current scale and deployment model do not justify a new service boundary.

## Decision: Introduce source-isolated retrieval outcomes

**Rationale**: The current failure mode is high daily zero-result frequency. Search reliability requires knowing whether a zero result came from no source hits, source outages, query narrowness, filtering, or deduplication. Each source should return a structured outcome with counts and error text, while failures in one source do not block other sources.

**Alternatives considered**:

- Keep source calls inline in `workflow.py`. Rejected because inline calls make diagnostics and per-source failure recovery hard to test.
- Stop the whole run when any primary source fails. Rejected because the specification requires graceful degradation and partial success.

## Decision: Use bounded catch-up windows instead of fixed daily lookback only

**Rationale**: Fixed `days_back` can miss papers after failed or skipped runs, while unbounded recovery can flood users with stale papers. Academic-Radar's product behavior uses last-success tracking with a bounded recovery cap. The platform should store enough state to compute a window from the last successful retrieval for each user and run type.

**Alternatives considered**:

- Always search the last 7 days. Rejected because repeated failures can still miss papers and repeated overlap increases duplicate pressure.
- Search since account creation after failure. Rejected because long downtime would generate stale, noisy results.

## Decision: Fingerprint papers by stable identifiers first, normalized title second

**Rationale**: Papers appear across multiple sources and may later move from preprint to publication. DOI, PMID, and arXiv IDs are better deduplication keys than URL. When identifiers are absent, normalized title similarity is the best fallback already demonstrated in the reference project.

**Alternatives considered**:

- Keep URL-only deduplication. Rejected because the same paper has different URLs across arXiv, PubMed, Crossref, Semantic Scholar, and OpenAlex.
- Deduplicate only after LLM filtering. Rejected because duplicate candidates waste scoring effort and can still produce repeated deliveries.

## Decision: Preserve source provenance on every delivered paper

**Rationale**: Users need to verify bibliographic data and understand why the digest included a paper. Provenance also supports diagnostics and future source tuning. LLM output must not invent title, authors, DOI, venue, or publication date.

**Alternatives considered**:

- Store only a single source label. Rejected because multi-source merge should preserve all contributing sources.
- Let the LLM fill missing bibliographic fields. Rejected because it increases hallucination risk and conflicts with the feature's trust requirement.

## Decision: Add diagnostics to existing push-facing contracts

**Rationale**: Users already inspect manual task status, dispatch logs, and paper records through `/api/v1/push/*`. Extending these responses with optional diagnostics is less disruptive than adding a separate diagnostics page or unrelated API surface.

**Alternatives considered**:

- Keep diagnostics only in backend logs. Rejected because users cannot reliably diagnose zero-result days from server logs.
- Create a separate admin-only diagnostics workflow. Rejected because the feature requirement includes user-facing understanding of zero-result outcomes.

## Decision: Use focused deterministic tests around pipeline decisions

**Rationale**: The most important behavior can be tested without live academic APIs by stubbing source outcomes, candidates, failures, duplicate papers, and prior history. This keeps tests stable while validating the risky business logic.

**Alternatives considered**:

- Validate only by running live source searches. Rejected because live academic APIs are slow, rate-limited, and nondeterministic.
- Test only the final email output. Rejected because it would miss diagnostics, source isolation, recovery-window, and deduplication regressions.
