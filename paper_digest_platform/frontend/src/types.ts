export interface UserProfile {
  id: number;
  username: string;
  email: string;
}

export interface LoginResponse {
  token: string;
  token_type: string;
  expires_at: string;
  user: UserProfile;
}

export interface MessageResponse {
  message: string;
}

export interface DigestSettingsResponse {
  sender_email: string;
  smtp_ready: boolean;
  target_email: string;
  daily_send_time: string;
  timezone: string;
  keywords_list?: string[][];
  keywords?: string[];
  user_search_intent?: string;
  active: boolean;
  updated_at: string;
}

export interface AutoKeywordsRequest {
  user_query: string;
}

export interface AutoKeywordsResponse {
  keywords_list?: string[][] | null;
}

export interface FeedbackItem {
  id: number;
  user_id: number;
  username: string;
  user_email: string;
  content: string;
  email_sent: boolean;
  email_error: string;
  created_at: string;
}

export interface FeedbackSubmitResponse {
  message: string;
  item: FeedbackItem;
}

export interface SearchRunCounts {
  raw_fetched: number;
  after_keyword_filter: number;
  after_run_dedup: number;
  after_history_dedup: number;
  after_relevance_filter: number;
  delivered: number;
}

export interface SourceResult {
  source: string;
  status: "success" | "empty" | "failed" | "timeout" | "disabled" | string;
  query_count: number;
  raw_count: number;
  candidate_count: number;
  error_message: string;
  elapsed_ms: number;
}

export interface ZeroResultExplanation {
  reason: string;
  message: string;
  filter_summary: string;
}

export interface SearchRunDiagnostics {
  run_id: string;
  run_type: string;
  window_start: string;
  window_end: string;
  recovery_reason: string;
  counts: SearchRunCounts;
  source_results: SourceResult[];
  zero_result_explanation?: ZeroResultExplanation | null;
}

export interface DispatchLogItem {
  id: number;
  run_type: string;
  status: string;
  message: string;
  created_at: string;
  diagnostics?: SearchRunDiagnostics | null;
}

export interface TriggerResponse {
  message: string;
  run_type: string;
}

export interface RunNowTaskStatus {
  task_id: string;
  run_type: string;
  status: "queued" | "running" | "success" | "failed" | "partial" | string;
  progress_stage: string;
  progress_message: string;
  result_message: string;
  error_message: string;
  created_at: string;
  updated_at: string;
  started_at: string;
  finished_at: string;
  diagnostics?: SearchRunDiagnostics | null;
}

export interface RunNowSubmitResponse {
  message: string;
  task: RunNowTaskStatus;
}

export interface PaperRecordItem {
  id: number;
  uid: string;
  push_date: string;
  title: string;
  url: string;
  venue: string;
  publisher: string;
  source: string;
  source_provenance?: string[];
  published_date: string;
  keywords: string[];
  run_type: string;
  created_at: string;
}
