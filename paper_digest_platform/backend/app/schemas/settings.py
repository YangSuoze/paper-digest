from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class DigestSettingsUpdateRequest(BaseModel):
    target_email: EmailStr
    daily_send_time: str = Field(default="09:30", min_length=5, max_length=5)
    timezone: str = Field(default="Asia/Shanghai", max_length=64)
    keywords_list: list[list[str]] | None = Field(default=None)
    active: bool = True
    user_search_intent: str | None = Field(default=None, max_length=512)

    @field_validator("daily_send_time")
    @classmethod
    def validate_time(cls, value: str) -> str:
        parts = value.split(":")
        if len(parts) != 2:
            raise ValueError("daily_send_time 必须是 HH:MM")
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except Exception as exc:
            raise ValueError("daily_send_time 必须是 HH:MM") from exc
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError("daily_send_time 超出有效范围")
        return f"{hour:02d}:{minute:02d}"

    @field_validator("keywords_list")
    @classmethod
    def normalize_keywords_list(
        cls, values: list[list[str]] | None
    ) -> list[list[str]] | None:
        if values is None:
            return None

        normalized: list[list[str]] = []
        seen_groups: set[tuple[str, ...]] = set()
        for group in values:
            seen_terms: set[str] = set()
            out_group: list[str] = []
            for term in group or []:
                clean = str(term or "").strip()
                if not clean:
                    continue
                lower = clean.lower()
                if lower in seen_terms:
                    continue
                seen_terms.add(lower)
                out_group.append(clean)
            if not out_group:
                continue
            group_key = tuple(item.lower() for item in out_group)
            if group_key in seen_groups:
                continue
            seen_groups.add(group_key)
            normalized.append(out_group)
        return normalized

    @model_validator(mode="after")
    def validate_keywords_presence(self) -> "DigestSettingsUpdateRequest":
        has_keywords_list = bool(self.keywords_list)
        if not has_keywords_list:
            raise ValueError("keywords_list 不能为空")
        return self


class DigestSettingsResponse(BaseModel):
    sender_email: str
    smtp_ready: bool
    target_email: str
    daily_send_time: str
    timezone: str
    keywords_list: list[list[str]] = Field(default_factory=list)
    active: bool
    updated_at: str
    user_search_intent: str | None = Field(default=None)


class KeywordsListRequest(BaseModel):
    user_query: str


class KeywordsListResponse(BaseModel):
    keywords_list: list[list[str]] | None = Field(default=None)


class FeedbackSubmitRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("反馈内容不能为空")
        if len(cleaned) > 4000:
            raise ValueError("反馈内容不能超过 4000 字")
        return cleaned


class FeedbackItem(BaseModel):
    id: int
    user_id: int
    username: str
    user_email: str
    content: str
    email_sent: bool
    email_error: str
    created_at: str


class FeedbackSubmitResponse(BaseModel):
    message: str
    item: FeedbackItem
