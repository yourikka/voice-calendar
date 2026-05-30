from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.models import EventCreate, EventUpdate, ParsedCommand, Reminder, TextCommandRequest, TextCommandResponse
from app.services.briefing import DailyBriefingService
from app.services.calendar import CalendarService
from app.services.news import NewsService
from app.services.nlu import (
    HybridCommandParser,
    _format_time_value,
    _parse_time_range,
    _resolve_date,
    normalize_text,
    request_now,
)


@dataclass
class PendingCommandState:
    parsed: ParsedCommand
    updated_at: datetime


_PENDING_COMMANDS: dict[str, PendingCommandState] = {}
_PENDING_LOCK = threading.Lock()
_PENDING_TTL = timedelta(minutes=30)


def _session_id(existing: str | None) -> str:
    return existing or f"ses_{uuid4().hex}"


def _slot_datetime(date_text: str, time_text: str, timezone_name: str) -> datetime:
    zone = ZoneInfo(timezone_name)
    return datetime.combine(date.fromisoformat(date_text), time.fromisoformat(time_text), tzinfo=zone)


def _build_reminders(offset_minutes: int | None, default_zero: bool = False) -> list[Reminder]:
    if offset_minutes is None and not default_zero:
        return []
    return [Reminder(method="notification", offset_minutes=offset_minutes or 0)]


def _get_pending_command(session_id: str) -> PendingCommandState | None:
    with _PENDING_LOCK:
        pending = _PENDING_COMMANDS.get(session_id)
        if pending is None:
            return None
        if datetime.now(timezone.utc) - pending.updated_at > _PENDING_TTL:
            _PENDING_COMMANDS.pop(session_id, None)
            return None
        return pending


def _save_pending_command(session_id: str, parsed: ParsedCommand) -> None:
    with _PENDING_LOCK:
        _PENDING_COMMANDS[session_id] = PendingCommandState(
            parsed=parsed,
            updated_at=datetime.now(timezone.utc),
        )


def _clear_pending_command(session_id: str) -> None:
    with _PENDING_LOCK:
        _PENDING_COMMANDS.pop(session_id, None)


def _missing_prompt(parsed: ParsedCommand) -> str:
    prompts = {
        ("create_reminder", "time"): "什么时候提醒你？",
        ("create_event", "start_time"): "这个事件几点开始？",
        ("update_event", "new_time"): "你想改到几点？",
        ("update_event", "title"): "你想修改哪个日程？",
    }
    for field in parsed.missing_fields:
        prompt = prompts.get((parsed.intent, field))
        if prompt:
            return prompt
    return "这条指令还缺少关键信息，请补充一下。"


class TextCommandService:
    def __init__(
        self,
        calendar: CalendarService,
        news: NewsService | None = None,
        briefing: DailyBriefingService | None = None,
        parser: HybridCommandParser | None = None,
    ) -> None:
        self.calendar = calendar
        self.news = news
        self.briefing = briefing
        self.parser = parser or HybridCommandParser()

    def parse(self, request: TextCommandRequest) -> ParsedCommand:
        return self.parser.parse(request)

    def handle(self, request: TextCommandRequest) -> TextCommandResponse:
        session_id = _session_id(request.session_id)
        parsed = self.parse(request)
        pending = _get_pending_command(session_id)
        if pending is not None:
            parsed = self._merge_pending_command(request, parsed, pending.parsed)
        return self._execute(request, parsed, session_id)

    def _response(
        self,
        request: TextCommandRequest,
        parsed: ParsedCommand,
        session_id: str,
        *,
        state: str,
        reply_text: str,
        requires_user_input: bool = False,
        operation_id: str | None = None,
        event=None,
        candidates=None,
    ) -> TextCommandResponse:
        return TextCommandResponse(
            session_id=session_id,
            state=state,
            transcript=request.text,
            intent=parsed.intent,
            reply_text=reply_text,
            requires_user_input=requires_user_input,
            operation_id=operation_id,
            event=event,
            candidates=candidates or [],
            parser=parsed.parser,
            confidence=parsed.confidence,
            slots=parsed.slots,
            missing_fields=parsed.missing_fields,
        )

    def _execute(
        self,
        request: TextCommandRequest,
        parsed: ParsedCommand,
        session_id: str,
    ) -> TextCommandResponse:
        if parsed.missing_fields:
            _save_pending_command(session_id, parsed)
            return self._response(
                request,
                parsed,
                session_id,
                state="collecting_slots",
                reply_text=_missing_prompt(parsed),
                requires_user_input=True,
            )

        if parsed.intent == "get_daily_briefing":
            _clear_pending_command(session_id)
            if self.briefing:
                briefing = self.briefing.get_daily_briefing(
                    date=parsed.slots["date"],
                    timezone_name=request.timezone,
                )
                reply_text = briefing.spoken_summary
            else:
                reply_text = "今日简报功能已进入简报服务处理流程。"
            return self._response(request, parsed, session_id, state="completed", reply_text=reply_text)

        if parsed.intent == "get_today_news":
            _clear_pending_command(session_id)
            if self.news:
                news = self.news.get_today_news(
                    timezone_name=request.timezone,
                    category=parsed.slots.get("news_category"),
                    limit=parsed.slots.get("limit", 5),
                    fresh=False,
                )
                reply_text = news.spoken_summary
            else:
                reply_text = "今日热点功能已进入资讯服务处理流程。"
            return self._response(request, parsed, session_id, state="completed", reply_text=reply_text)

        if parsed.intent == "undo_last_operation":
            _clear_pending_command(session_id)
            result = self.calendar.undo_last_operation()
            return self._response(
                request,
                parsed,
                session_id,
                state=result.state,
                reply_text=result.reply_text,
                event=result.event,
            )

        if parsed.intent == "create_reminder":
            _clear_pending_command(session_id)
            start_at = _slot_datetime(parsed.slots["date"], parsed.slots["time"], request.timezone)
            title = parsed.slots["title"]
            created = self.calendar.create_event(
                EventCreate(
                    title=title,
                    type="reminder",
                    start_at=start_at,
                    end_at=None,
                    timezone=request.timezone,
                    reminders=_build_reminders(None, default_zero=True),
                    source="text",
                )
            )
            return self._response(
                request,
                parsed,
                session_id,
                state="completed",
                reply_text=f"已设置{start_at.strftime('%m月%d日%H:%M')}提醒你{title}。",
                event=created.event,
            )

        if parsed.intent == "create_event":
            _clear_pending_command(session_id)
            start_at = _slot_datetime(parsed.slots["date"], parsed.slots["start_time"], request.timezone)
            if parsed.slots.get("end_time"):
                end_at = _slot_datetime(parsed.slots["date"], parsed.slots["end_time"], request.timezone)
            else:
                end_at = start_at + timedelta(hours=1)
            title = parsed.slots["title"]
            created = self.calendar.create_event(
                EventCreate(
                    title=title,
                    type="event",
                    start_at=start_at,
                    end_at=end_at,
                    timezone=request.timezone,
                    participants=parsed.slots.get("participants") or [],
                    reminders=_build_reminders(parsed.slots.get("reminder_offset_minutes")),
                    source="text",
                )
            )
            conflict_text = "，但存在时间冲突" if created.conflicts else ""
            return self._response(
                request,
                parsed,
                session_id,
                state="completed",
                reply_text=f"已创建{start_at.strftime('%m月%d日%H:%M')}的{title}{conflict_text}。",
                event=created.event,
            )

        if parsed.intent == "list_events":
            _clear_pending_command(session_id)
            start = datetime.fromisoformat(parsed.slots["start"])
            end = datetime.fromisoformat(parsed.slots["end"])
            events = self.calendar.list_events(start, end)
            if not events:
                reply = "这段时间没有已安排的日程。"
            else:
                pieces = [f"{event.start_at.strftime('%H:%M')} {event.title}" for event in events[:3]]
                reply = f"这段时间有 {len(events)} 个安排：" + "，".join(pieces)
            return self._response(request, parsed, session_id, state="completed", reply_text=reply)

        if parsed.intent == "delete_event":
            _clear_pending_command(session_id)
            start = datetime.fromisoformat(parsed.slots["start"])
            end = datetime.fromisoformat(parsed.slots["end"])
            keyword = parsed.slots.get("title", "")
            delete_all = bool(parsed.slots.get("delete_all"))
            candidates = self.calendar.find_events_by_title(keyword or "", start, end)
            if not candidates:
                return self._response(
                    request,
                    parsed,
                    session_id,
                    state="not_found",
                    reply_text="没有找到匹配的日程。",
                )
            if delete_all:
                if len(candidates) == 1:
                    operation = self.calendar.create_delete_draft(candidates[0].id)
                    return self._response(
                        request,
                        parsed,
                        session_id,
                        state="awaiting_confirmation",
                        reply_text=f"找到{candidates[0].title}，确认取消吗？",
                        requires_user_input=True,
                        operation_id=operation.id,
                        candidates=candidates,
                    )
                operation = self.calendar.create_delete_many_draft([candidate.id for candidate in candidates])
                return self._response(
                    request,
                    parsed,
                    session_id,
                    state="awaiting_confirmation",
                    reply_text=f"找到 {len(candidates)} 个日程，确认全部取消吗？",
                    requires_user_input=True,
                    operation_id=operation.id,
                    candidates=candidates,
                )
            if len(candidates) > 1:
                return self._response(
                    request,
                    parsed,
                    session_id,
                    state="selecting_candidate",
                    reply_text=f"找到 {len(candidates)} 个匹配日程，请选择要取消哪一个。",
                    requires_user_input=True,
                    candidates=candidates,
                )
            operation = self.calendar.create_delete_draft(candidates[0].id)
            return self._response(
                request,
                parsed,
                session_id,
                state="awaiting_confirmation",
                reply_text=f"找到{candidates[0].title}，确认取消吗？",
                requires_user_input=True,
                operation_id=operation.id,
                candidates=candidates,
            )

        if parsed.intent == "update_event":
            _clear_pending_command(session_id)
            start_at, explicit_end_at = self._resolve_update_times(parsed, request.timezone)
            query_date = parsed.slots.get("target_date") or parsed.slots.get("new_date")
            zone = ZoneInfo(request.timezone)
            query_start = datetime.combine(date.fromisoformat(query_date), time.min, tzinfo=zone)
            query_end = query_start + timedelta(days=1)
            keyword = parsed.slots.get("title", "")
            candidates = self.calendar.find_events_by_title(keyword or "", query_start, query_end)
            if not candidates:
                return self._response(
                    request,
                    parsed,
                    session_id,
                    state="not_found",
                    reply_text="没有找到要修改的日程。",
                )
            if len(candidates) > 1:
                return self._response(
                    request,
                    parsed,
                    session_id,
                    state="selecting_candidate",
                    reply_text=f"找到 {len(candidates)} 个匹配日程，请选择要修改哪一个。",
                    requires_user_input=True,
                    candidates=candidates,
                )
            existing = self.calendar.get_event(candidates[0].id)
            end_at = explicit_end_at
            if end_at is None and existing.end_at:
                end_at = start_at + (existing.end_at - existing.start_at)
            updated = self.calendar.update_event(
                existing.id,
                EventUpdate(start_at=start_at, end_at=end_at),
            )
            conflict_text = "，但存在时间冲突" if updated.conflicts else ""
            return self._response(
                request,
                parsed,
                session_id,
                state="completed",
                reply_text=f"已将{updated.event.title}改到{start_at.strftime('%m月%d日%H:%M')}{conflict_text}。",
                event=updated.event,
            )

        _clear_pending_command(session_id)
        return self._response(
            request,
            parsed,
            session_id,
            state="unsupported",
            reply_text="暂时无法理解这条指令，请换一种说法。",
            requires_user_input=True,
        )

    @staticmethod
    def _resolve_update_times(parsed: ParsedCommand, timezone_name: str) -> tuple[datetime, datetime | None]:
        start_at = _slot_datetime(parsed.slots["new_date"], parsed.slots["new_start_time"], timezone_name)
        end_time = parsed.slots.get("new_end_time")
        if end_time:
            return start_at, _slot_datetime(parsed.slots["new_date"], end_time, timezone_name)
        return start_at, None

    def _merge_pending_command(
        self,
        request: TextCommandRequest,
        parsed: ParsedCommand,
        pending: ParsedCommand,
    ) -> ParsedCommand:
        if parsed.intent not in {"unknown", pending.intent} and not parsed.missing_fields:
            return parsed
        if pending.intent == "create_event":
            return self._merge_pending_create_event(request, parsed, pending)
        if pending.intent == "create_reminder":
            return self._merge_pending_create_reminder(request, parsed, pending)
        if pending.intent == "update_event":
            return self._merge_pending_update_event(request, parsed, pending)
        return parsed

    def _merge_pending_create_event(
        self,
        request: TextCommandRequest,
        parsed: ParsedCommand,
        pending: ParsedCommand,
    ) -> ParsedCommand:
        slots = dict(pending.slots)
        slots.update({key: value for key, value in parsed.slots.items() if value not in (None, "", [], {})})
        day = _resolve_date(request.text, request_now(request))
        start_time, end_time = _parse_time_range(normalize_text(request.text))
        if day is not None:
            slots["date"] = day.isoformat()
        if start_time is not None:
            slots["start_time"] = _format_time_value(start_time)
        if end_time is not None:
            slots["end_time"] = _format_time_value(end_time)
        missing_fields = []
        if not slots.get("start_time"):
            missing_fields.append("start_time")
        return ParsedCommand(
            transcript=request.text,
            normalized_text=normalize_text(request.text),
            intent="create_event",
            slots=slots,
            missing_fields=missing_fields,
            parser="rule+context",
            confidence=0.9 if not missing_fields else 0.6,
        )

    def _merge_pending_create_reminder(
        self,
        request: TextCommandRequest,
        parsed: ParsedCommand,
        pending: ParsedCommand,
    ) -> ParsedCommand:
        slots = dict(pending.slots)
        slots.update({key: value for key, value in parsed.slots.items() if value not in (None, "", [], {})})
        day = _resolve_date(request.text, request_now(request))
        start_time, _ = _parse_time_range(normalize_text(request.text))
        if day is not None:
            slots["date"] = day.isoformat()
        if start_time is not None:
            slots["time"] = _format_time_value(start_time)
        missing_fields = []
        if not slots.get("time"):
            missing_fields.append("time")
        return ParsedCommand(
            transcript=request.text,
            normalized_text=normalize_text(request.text),
            intent="create_reminder",
            slots=slots,
            missing_fields=missing_fields,
            parser="rule+context",
            confidence=0.9 if not missing_fields else 0.6,
        )

    def _merge_pending_update_event(
        self,
        request: TextCommandRequest,
        parsed: ParsedCommand,
        pending: ParsedCommand,
    ) -> ParsedCommand:
        slots = dict(pending.slots)
        slots.update({key: value for key, value in parsed.slots.items() if value not in (None, "", [], {})})
        day = _resolve_date(request.text, request_now(request))
        start_time, end_time = _parse_time_range(normalize_text(request.text))
        if day is not None:
            slots["new_date"] = day.isoformat()
        if start_time is not None:
            slots["new_start_time"] = _format_time_value(start_time)
        if end_time is not None:
            slots["new_end_time"] = _format_time_value(end_time)
        missing_fields = []
        if not slots.get("title"):
            missing_fields.append("title")
        if not slots.get("new_start_time"):
            missing_fields.append("new_time")
        return ParsedCommand(
            transcript=request.text,
            normalized_text=normalize_text(request.text),
            intent="update_event",
            slots=slots,
            missing_fields=missing_fields,
            parser="rule+context",
            confidence=0.88 if not missing_fields else 0.58,
        )
