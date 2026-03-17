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

export interface DispatchLogItem {
  id: number;
  run_type: string;
  status: string;
  message: string;
  created_at: string;
}

export interface TriggerResponse {
  message: string;
  run_type: string;
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
  published_date: string;
  keywords: string[];
  run_type: string;
  created_at: string;
}
