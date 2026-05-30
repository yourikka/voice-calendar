from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


EventType = Literal["event", "reminder"]
EventStatus = Literal["confirmed", "cancelled"]


class Reminder(BaseModel):
    method: str = "notification"
    offset_minutes: int = 0


class EventBase(BaseModel):
    title: str = Field(min_length=1)
    type: EventType = "event"
    description: str = ""
    start_at: datetime
    end_at: datetime | None = None
    timezone: str = "Asia/Shanghai"
    location: str | None = None
    participants: list[str] = Field(default_factory=list)
    reminders: list[Reminder] = Field(default_factory=list)
    recurrence_rule: dict | None = None
    calendar_id: str = "primary"


class EventCreate(EventBase):
    source: str = "web"


class EventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    timezone: str | None = None
    location: str | None = None
    participants: list[str] | None = None
    reminders: list[Reminder] | None = None
    recurrence_rule: dict | None = None


class EventRead(EventBase):
    id: str
    source: str
    status: EventStatus
    created_at: datetime
    updated_at: datetime


class EventListResponse(BaseModel):
    items: list[EventRead]


class Conflict(BaseModel):
    id: str
    title: str
    start_at: datetime
    end_at: datetime | None = None


class EventCreateResponse(BaseModel):
    event: EventRead
    conflicts: list[Conflict]


class OperationRead(BaseModel):
    id: str
    operation: str
    target_event_id: str | None = None
    state: str
    created_at: datetime
    undo_expires_at: datetime | None = None


class UndoResponse(BaseModel):
    state: str
    event: EventRead | None = None
    reply_text: str


class ConfirmOperationRequest(BaseModel):
    operation_id: str
    confirmed: bool = True


class ConfirmOperationResponse(BaseModel):
    state: str
    event: EventRead | None = None
    deleted_count: int | None = None
    reply_text: str


class Candidate(BaseModel):
    id: str
    title: str
    start_at: datetime
    end_at: datetime | None = None


class TextCommandRequest(BaseModel):
    text: str = Field(min_length=1)
    timezone: str = "Asia/Shanghai"
    locale: str = "zh-CN"
    session_id: str | None = None
    now: datetime | None = None


class ParsedCommand(BaseModel):
    transcript: str
    normalized_text: str
    intent: str
    slots: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    parser: str = "rule"
    confidence: float = 0.0


class TextCommandResponse(BaseModel):
    session_id: str
    state: str
    transcript: str
    intent: str
    reply_text: str
    requires_user_input: bool = False
    operation_id: str | None = None
    event: EventRead | None = None
    candidates: list[Candidate] = Field(default_factory=list)
    parser: str | None = None
    confidence: float | None = None
    slots: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)


class VoiceCommandResponse(TextCommandResponse):
    command_id: str
    asr_provider: str
    reply_audio_url: str | None = None


class VoiceTranscriptResponse(BaseModel):
    transcript: str
    asr_provider: str
    locale: str = "zh-CN"


class VoiceCapabilitiesResponse(BaseModel):
    server_asr_available: bool
    browser_fallback_recommended: bool = True
    provider: str | None = None
    model: str | None = None
    ready: bool = False
    warming: bool = False
    detail: str | None = None


class NewsItemRead(BaseModel):
    id: str
    title: str
    summary: str
    category: str
    region: str
    source_name: str
    source_url: str
    published_at: datetime
    fetched_at: datetime
    language: str = "zh-CN"
    hot_score: float


class NewsTodayResponse(BaseModel):
    date: str
    timezone: str
    fresh: bool
    fetched_at: datetime
    items: list[NewsItemRead]
    spoken_summary: str


class HotTopicPanelResponse(BaseModel):
    date: str
    timezone: str
    refreshed_at: datetime
    cache_expires_at: datetime
    stale: bool
    items: list[NewsItemRead]


class HotTopicRefreshRequest(BaseModel):
    date: str | None = None
    timezone: str = "Asia/Shanghai"
    region: str = "CN"
    categories: list[str] = Field(default_factory=lambda: ["general", "technology", "finance"])


class HotTopicRefreshResponse(BaseModel):
    status: str
    refreshed_at: datetime
    item_count: int


class BriefingSection(BaseModel):
    type: str
    spoken_summary: str


class DailyBriefingResponse(BaseModel):
    date: str
    timezone: str
    sections: list[BriefingSection]
    spoken_summary: str


class CalendarMetaDayRead(BaseModel):
    date: date
    is_holiday: bool
    is_adjusted_workday: bool
    holiday_name: str | None = None
    solar_term: str | None = None


class CalendarMetaResponse(BaseModel):
    start: date
    end: date
    items: list[CalendarMetaDayRead]


class MCPToolRequest(BaseModel):
    arguments: dict = Field(default_factory=dict)


class MCPToolResponse(BaseModel):
    tool: str
    result: dict
