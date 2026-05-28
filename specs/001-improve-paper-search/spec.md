# Feature Specification: Improve Paper Search Reliability

**Feature Branch**: `001-improve-paper-search`

**Created**: 2026-05-28

**Status**: Draft

**Input**: User description: "针对当前项目按照如下要求重构：当前项目论文搜索每日失败率高，搜索到的论文数目连续几天都是0，请参考开源项目/Users/yangjie/Documents/python_project/Academic-Radar进行改造，提高论文检索效果"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Daily Search Returns Relevant Papers Reliably (Priority: P1)

As a paper digest user, I want the daily scheduled search to find relevant new papers for my research interests instead of repeatedly returning zero results, so that the digest remains useful as a daily research-monitoring tool.

**Why this priority**: The current business failure is repeated zero-paper daily runs. Fixing reliable discovery is the core value of the refactor.

**Independent Test**: Run the daily search for an active research topic over a recent publication window and verify that the search produces relevant candidate papers or a documented no-new-content outcome with source-level evidence.

**Acceptance Scenarios**:

1. **Given** a user has saved a clear research intent and keyword groups, **When** the daily search runs for a recent active topic, **Then** the user receives a digest containing relevant new papers when credible sources contain matching content.
2. **Given** one source returns no matching papers, **When** other enabled sources contain matching content, **Then** the digest still includes papers found from the available sources.
3. **Given** no credible source contains new matching papers for the search window, **When** the daily search completes, **Then** the user sees a transparent no-new-content result with the searched window and per-source counts instead of an unexplained empty result.

---

### User Story 2 - Search Recovers From Missed Or Failed Runs (Priority: P2)

As a paper digest user, I want the next successful run to cover missed time when previous runs failed or found nothing due to source problems, so that relevant papers are not lost across days.

**Why this priority**: Consecutive zero-result days can come from source failures, too-narrow windows, or missed runs. Recovery protects trust in the daily digest.

**Independent Test**: Simulate a failed or skipped run, then run the digest again and verify that the search covers the appropriate prior period without flooding the user with stale or duplicate papers.

**Acceptance Scenarios**:

1. **Given** the previous scheduled search failed before completing, **When** the next search succeeds, **Then** the covered period includes the missed interval up to a bounded recovery limit.
2. **Given** the system has already sent a paper during a previous recovery or daily run, **When** a later recovery window overlaps that period, **Then** that paper is not sent again.

---

### User Story 3 - Users Can Diagnose Search Quality (Priority: P3)

As a platform operator or advanced user, I want each run to expose enough search-quality information to understand zero-result or low-result days, so that I can adjust research intent, keywords, or source settings with confidence.

**Why this priority**: Search improvements must be observable. Without diagnostics, users cannot distinguish true no-new-paper days from broken retrieval, over-filtering, or source outages.

**Independent Test**: Run a search that returns zero final papers and verify that the run record explains source counts, filtering counts, deduplication counts, and any source errors in user-readable terms.

**Acceptance Scenarios**:

1. **Given** a run returns zero final papers, **When** the user reviews the run history, **Then** the user can see whether zero papers came from no source hits, filtering, duplicate removal, or source failures.
2. **Given** one or more sources fail, **When** the run completes, **Then** the failure is visible in the run record while successful sources still contribute results.

### Edge Cases

- A user provides a very narrow research intent or keyword group that legitimately has no new papers.
- A user provides broad keywords that create too many low-relevance candidates.
- One or more enabled sources are unavailable, rate-limited, slow, or return malformed data.
- Candidate papers appear late in a source after the original publication date.
- The same paper appears in multiple sources or appears once as a preprint and later as a formally published article.
- A search run overlaps with a prior run because of recovery from missed days.
- The digest has no final papers after duplicates and low-relevance items are removed.
- Existing user settings, push history, and paper records already contain data from prior behavior.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST search across multiple credible academic source categories for each enabled daily or manual paper search.
- **FR-002**: The system MUST treat each source independently so that a failure, timeout, or empty response from one source does not prevent results from other sources being considered.
- **FR-003**: The system MUST derive search coverage from the user's saved research intent and keyword groups, including both exact phrase matching and broader related-term matching when appropriate.
- **FR-004**: The system MUST apply a bounded recovery window after failed or missed runs so that recent papers are not skipped permanently.
- **FR-005**: The system MUST avoid unbounded historical searches that could flood the user with stale papers after long downtime.
- **FR-006**: The system MUST keep enough per-run source statistics to distinguish no source results, source failure, filtering, duplicate removal, and final delivery.
- **FR-007**: The system MUST remove duplicate candidate papers within a run using stable paper identifiers when available and normalized title similarity when identifiers are unavailable.
- **FR-008**: The system MUST remove papers that were already sent to the same user within the configured recent-history period.
- **FR-009**: The system MUST preserve the most complete available metadata when the same paper is found from multiple sources.
- **FR-010**: The system MUST rank final papers by relevance to the user's research intent, recency, and publication trust signals.
- **FR-011**: The system MUST retain only papers that pass a minimum relevance threshold for delivery, while recording how many candidates were filtered out.
- **FR-012**: The system MUST send a clear no-new-content digest when no final papers remain after a successful search, including the searched date range and source-level counts.
- **FR-013**: The system MUST record source provenance for every delivered paper, including which source categories contributed to the item.
- **FR-014**: The system MUST support manual search runs using the same retrieval, deduplication, ranking, and diagnostics behavior as scheduled runs.
- **FR-015**: The system MUST preserve existing user settings, historical paper records, and digest state during the refactor.

### Key Entities

- **User Research Profile**: The user's saved research intent, keyword groups, optional exclusions, and delivery preferences that guide retrieval and filtering.
- **Search Run**: A scheduled or manual execution with run type, covered date range, status, source statistics, filtering statistics, errors, and final result count.
- **Source Result**: A source-specific retrieval outcome containing searched count, candidate count, success or failure status, and any user-readable failure reason.
- **Candidate Paper**: A paper discovered before final filtering, with title, authors, abstract or summary, publication date, source provenance, identifiers, and relevance signals.
- **Delivered Paper**: A candidate selected for the user digest after relevance filtering, deduplication, ranking, and history checks.
- **Deduplication Fingerprint**: A stable representation of a paper used to prevent duplicate delivery within and across runs.
- **Zero-Result Explanation**: The user-readable reason a run produced no final papers, based on source hits, filtering, duplicates, and source errors.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For active research topics with known recent publications, at least 90% of daily scheduled runs return one or more relevant papers over a 14-day validation period.
- **SC-002**: Fewer than 5% of successful daily runs produce an unexplained zero-result outcome over a 30-day validation period.
- **SC-003**: When at least one source category fails during a run, the run still completes with results or a clear no-new-content digest in at least 95% of cases.
- **SC-004**: At least 95% of delivered papers include source provenance and enough bibliographic information for the user to verify the paper.
- **SC-005**: Duplicate delivered papers for the same user stay below 2% over a rolling 30-day period.
- **SC-006**: At least 80% of delivered papers are judged relevant or highly relevant by user feedback or review sampling.
- **SC-007**: A manual search run for a user's saved research profile completes with a final digest or clear no-new-content explanation within 5 minutes for normal daily workloads.
- **SC-008**: Existing users can continue using their saved settings and view prior paper records after the refactor without manual data repair.

## Assumptions

- The primary users are researchers or research-monitoring users who expect a low-noise daily paper digest.
- The refactor should improve retrieval and observability without changing the core user workflow of saving settings and receiving scheduled or manual digests.
- Academic-Radar is used as a behavioral reference for product outcomes such as multi-source retrieval, recovery windows, deduplication, provenance, relevance filtering, and diagnostics.
- A true zero-paper day is acceptable when credible sources have no new relevant content, but the outcome must be explainable.
- Existing delivery channels remain in scope only insofar as they must receive the improved digest output.
- Detailed implementation choices will be defined during planning, not in this specification.
