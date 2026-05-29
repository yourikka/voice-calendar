from __future__ import annotations

from datetime import datetime
from typing import Literal

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
    reply_text: str


class Candidate(BaseModel):
    id: str
    title: str
    start_at: datetime
    end_at: datetime | None = None


class TextCommandRequest(BaseModel):
    text: str = Field(min_length=1)
    timezone: str = "Asia/Shanghai"
    session_id: str | None = None
    now: datetime | None = None


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
