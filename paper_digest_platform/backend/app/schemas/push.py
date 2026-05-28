from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class TestEmailRequest(BaseModel):
    to_email: EmailStr | None = None


class TriggerResponse(BaseModel):
    message: str
    run_type: str


class RunNowRequest(BaseModel):
    keywords_list: list[list[str]] | None = Field(default=None)


class SearchRunCounts(BaseModel):
    raw_fetched: int = 0
    after_keyword_filter: int = 0
    after_run_dedup: int = 0
    after_history_dedup: int = 0
    after_relevance_filter: int = 0
    delivered: int = 0


class SourceResult(BaseModel):
    source: str
    status: str
    query_count: int = 0
    raw_count: int = 0
    candidate_count: int = 0
    error_message: str = ""
    elapsed_ms: int = 0


class ZeroResultExplanation(BaseModel):
    reason: str
    message: str
    filter_summary: str = ""


class SearchRunDiagnostics(BaseModel):
    run_id: str = ""
    run_type: str = ""
    window_start: str = ""
    window_end: str = ""
    recovery_reason: str = "normal"
    counts: SearchRunCounts = Field(default_factory=SearchRunCounts)
    source_results: list[SourceResult] = Field(default_factory=list)
    zero_result_explanation: ZeroResultExplanation | None = None


class RunNowTaskStatus(BaseModel):
    task_id: str
    run_type: str
    status: str
    progress_stage: str
    progress_message: str
    result_message: str = ""
    error_message: str = ""
    created_at: str
    updated_at: str
    started_at: str = ""
    finished_at: str = ""
    diagnostics: SearchRunDiagnostics | None = None


class RunNowSubmitResponse(BaseModel):
    message: str
    task: RunNowTaskStatus


class DispatchLogItem(BaseModel):
    id: int
    run_type: str
    status: str
    message: str
    created_at: str
    diagnostics: SearchRunDiagnostics | None = None


class PaperRecordItem(BaseModel):
    id: int
    uid: str
    push_date: str
    title: str
    url: str
    venue: str
    publisher: str
    source: str
    source_provenance: list[str] = Field(default_factory=list)
    published_date: str
    keywords: list[str]
    run_type: str
    created_at: str
