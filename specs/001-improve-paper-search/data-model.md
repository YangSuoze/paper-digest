# Data Model: Improve Paper Search Reliability

## User Research Profile

Represents the user's saved inputs that guide paper retrieval.

**Fields**:

- `user_id`: Existing platform user identifier.
- `target_email`: Delivery address.
- `timezone`: User timezone for scheduled windows.
- `daily_send_time`: Scheduled daily delivery time.
- `keywords_list`: Keyword groups where each group represents required terms and groups are alternatives.
- `user_search_intent`: Natural language research intent for relevance filtering and ranking.
- `active`: Whether scheduled delivery is enabled.

**Relationships**:

- Owns many `SearchRun` records.
- Produces search queries for many `SourceResult` records.

**Validation Rules**:

- `keywords_list` must contain at least one non-empty group for digest execution.
- `target_email` and SMTP readiness remain required for delivery.
- Existing settings must remain readable after the refactor.

## Search Run

Represents one scheduled or manual digest execution.

**Fields**:

- `run_id`: Stable run identifier.
- `user_id`: Owner.
- `run_type`: `scheduled` or `manual_digest`.
- `status`: `queued`, `running`, `success`, `failed`, or `partial`.
- `window_start`: Inclusive retrieval start date/time.
- `window_end`: Retrieval end date/time.
- `recovery_reason`: Empty, `normal`, `missed_run`, `previous_failure`, or `manual_extended`.
- `source_results`: Collection of `SourceResult`.
- `counts`: Raw fetched count, post-keyword-filter count, post-dedup count, post-relevance count, delivered count.
- `zero_result_explanation`: Optional `ZeroResultExplanation`.
- `created_at`, `started_at`, `finished_at`: Run timestamps.

**Relationships**:

- Belongs to `User Research Profile`.
- Contains many `SourceResult` and `Candidate Paper` records during execution.
- Produces zero or more `Delivered Paper` records.

**State Transitions**:

- `queued` -> `running`
- `running` -> `success`
- `running` -> `partial`
- `running` -> `failed`
- `partial` means at least one source or enrichment step failed, but the run completed with results or a clear no-new-content explanation.

## Source Result

Represents the outcome of querying one source category.

**Fields**:

- `source`: Source category name such as `arxiv`, `pubmed`, `crossref`, `semantic_scholar`, or `openalex`.
- `status`: `success`, `empty`, `failed`, `timeout`, or `disabled`.
- `query_count`: Number of query groups attempted.
- `raw_count`: Number of raw records returned by the source.
- `candidate_count`: Number of candidate papers accepted from the source before global filtering.
- `error_message`: User-readable failure summary when applicable.
- `elapsed_ms`: Optional duration for diagnostics.

**Relationships**:

- Belongs to one `Search Run`.
- Contributes to many `Candidate Paper` records.

**Validation Rules**:

- Failed and timeout outcomes must not prevent other source results from being collected.
- Disabled sources must be distinguishable from failed sources.

## Candidate Paper

Represents a paper found before final delivery selection.

**Fields**:

- `fingerprint`: Deduplication fingerprint.
- `title`: Source-provided title.
- `authors`: Source-provided author list.
- `abstract`: Source-provided abstract or summary.
- `publication_date`: Source-provided publication date.
- `url`: Source-provided landing page.
- `doi`, `pmid`, `arxiv_id`: Optional stable identifiers.
- `venue`: Journal, preprint server, or venue text from the source.
- `publisher`: Source-provided publisher text.
- `source_provenance`: List of sources that found or enriched the paper.
- `keywords`: Matched user keyword groups or terms.
- `relevance_score`: Relevance signal used for ranking.
- `trust_signal`: Publication/preprint/unknown trust signal used for ranking.

**Relationships**:

- Belongs to one `Search Run`.
- Can become one `Delivered Paper`.
- Can merge with other candidates sharing the same fingerprint.

**Validation Rules**:

- Bibliographic fields must come from source data.
- Missing identifiers must fall back to normalized title fingerprinting.
- Merged candidates must preserve all contributing sources.

## Delivered Paper

Represents a paper selected for a user's digest and persisted to history.

**Fields**:

- `uid`: Stable delivery identifier, preferably derived from the fingerprint.
- `push_date`: Delivery date.
- `title`: Delivered title.
- `url`: Delivered URL.
- `venue`: Delivered venue.
- `publisher`: Delivered publisher.
- `source`: Primary display source.
- `source_provenance`: All contributing source categories.
- `published_date`: Publication date.
- `keywords`: Matched keywords.
- `run_type`: Scheduled or manual delivery.
- `created_at`: Persistence timestamp.

**Relationships**:

- Belongs to one `User Research Profile`.
- Produced by one `Search Run`.
- Derived from one merged `Candidate Paper`.

**Validation Rules**:

- The same user should not receive the same fingerprint twice within the recent-history period.
- Existing `paper_records` consumers must continue to work even if provenance is added as an optional field.

## Deduplication Fingerprint

Represents the stable key used to merge and suppress duplicate papers.

**Fields**:

- `kind`: `doi`, `pmid`, `arxiv`, or `title`.
- `value`: Normalized identifier value.
- `source_fields`: Which paper fields contributed to the fingerprint.

**Validation Rules**:

- Prefer DOI over PMID over arXiv ID over normalized title.
- Title fingerprints must strip case and punctuation differences.

## Zero Result Explanation

Represents why a completed run delivered no papers.

**Fields**:

- `reason`: `no_source_hits`, `all_sources_failed`, `filtered_out`, `duplicates_only`, or `no_relevant_after_ranking`.
- `message`: User-readable explanation.
- `window_start`, `window_end`: Date/time range searched.
- `source_summary`: Per-source counts and failures.
- `filter_summary`: Counts removed by keyword filtering, deduplication, history suppression, and relevance filtering.

**Relationships**:

- Belongs to one `Search Run`.

**Validation Rules**:

- Every successful or partial zero-delivery run must have an explanation.
- Explanations must be concise enough to fit existing logs/tasks while still identifying the main cause.
