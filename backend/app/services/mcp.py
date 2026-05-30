from __future__ import annotations

import base64
import binascii
from dataclasses import asdict
import sqlite3
from datetime import date, datetime, time
from typing import Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.models import (
    CalendarMetaDayRead,
    ConfirmOperationRequest,
    EventCreate,
    EventUpdate,
    HotTopicRefreshRequest,
    MCPToolResponse,
    TextCommandRequest,
)
from app.services.almanac import AlmanacService
from app.services.asr import ASRRequestError, ASRService, ASRTranscript, ASRUnavailableError
from app.services.briefing import DailyBriefingService
from app.services.calendar import CalendarService
from app.services.command import TextCommandService
from app.services.conversation_state import PendingCommandStore
from app.services.news import NewsService
from app.services.nlu import HybridCommandParser


def _parse_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    return datetime.fromisoformat(normalized)


class MCPToolService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        parser: HybridCommandParser | None = None,
        asr: ASRService | None = None,
    ) -> None:
        self.conn = conn
        self.calendar = CalendarService(conn)
        self.news = NewsService(conn)
        self.briefing = DailyBriefingService(conn)
        self.parser = parser or HybridCommandParser()
        self.commands = TextCommandService(
            calendar=self.calendar,
            news=self.news,
            briefing=self.briefing,
            parser=self.parser,
            pending_store=PendingCommandStore(conn),
        )
        self.asr = asr
        self._handlers: dict[str, Callable[[dict], dict]] = {
            "calendar.parse_command": self._parse_command,
            "calendar.handle_command": self._handle_command,
            "voice.handle_command": self._handle_voice_command,
            "calendar.list_events": self._list_events,
            "calendar.get_event": self._get_event,
            "calendar.create_event": self._create_event,
            "calendar.create_event_draft": self._create_event_draft,
            "calendar.update_event": self._update_event,
            "calendar.resolve_candidate": self._resolve_candidate,
            "calendar.update_event_draft": self._update_event_draft,
            "calendar.delete_event": self._delete_event,
            "calendar.delete_event_draft": self._delete_event_draft,
            "calendar.confirm_operation": self._confirm_operation,
            "calendar.check_availability": self._check_availability,
            "calendar.undo_last_operation": self._undo_last_operation,
            "news.get_today_hot_topics": self._get_today_hot_topics,
            "news.refresh_hot_topics": self._refresh_hot_topics,
            "calendar.get_hot_topic_panel": self._get_hot_topic_panel,
            "calendar.get_meta": self._get_meta,
            "briefing.get_daily_briefing": self._get_daily_briefing,
            "voice.get_capabilities": self._get_voice_capabilities,
            "voice.transcribe_audio": self._transcribe_audio_tool,
        }

    def call_tool(self, tool_name: str, arguments: dict) -> MCPToolResponse:
        handler = self._handlers.get(tool_name)
        if handler is None:
            raise KeyError(tool_name)
        return self._response(tool_name, handler(arguments))

    @staticmethod
    def _response(tool_name: str, result: dict) -> MCPToolResponse:
        return MCPToolResponse(tool=tool_name, result=result)

    def _parse_command(self, arguments: dict) -> dict:
        result = self.parser.parse(TextCommandRequest(**arguments))
        return result.model_dump(mode="json")

    def _handle_command(self, arguments: dict) -> dict:
        result = self.commands.handle(TextCommandRequest(**arguments))
        return result.model_dump(mode="json")

    def _handle_voice_command(self, arguments: dict) -> dict:
        transcript = self._transcribe_audio(arguments)
        result = self.commands.handle(
            TextCommandRequest(
                text=transcript.text,
                timezone=arguments.get("timezone", "Asia/Shanghai"),
                locale=arguments.get("locale", "zh-CN"),
                session_id=arguments.get("session_id"),
                now=_parse_datetime(arguments["now"]) if arguments.get("now") else None,
            )
        )
        payload = result.model_dump(mode="json")
        payload["command_id"] = f"cmd_{uuid4().hex}"
        payload["asr_provider"] = transcript.provider
        return payload

    def _list_events(self, arguments: dict) -> dict:
        result = self.calendar.list_events(
            start=_parse_datetime(arguments["start"]),
            end=_parse_datetime(arguments["end"]),
            calendar_id=arguments.get("calendar_id", "primary"),
        )
        return {"items": [item.model_dump(mode="json") for item in result]}

    def _get_event(self, arguments: dict) -> dict:
        return self.calendar.get_event(arguments["event_id"]).model_dump(mode="json")

    def _create_event(self, arguments: dict) -> dict:
        created = self.calendar.create_event(EventCreate(**arguments))
        return {
            "state": "completed",
            "event": created.event.model_dump(mode="json"),
            "conflicts": [item.model_dump(mode="json") for item in created.conflicts],
            "reply_text": f"已创建{created.event.title}。",
        }

    def _create_event_draft(self, arguments: dict) -> dict:
        payload = self._create_event(arguments)
        payload["requires_confirmation"] = False
        return payload

    def _update_event(self, arguments: dict) -> dict:
        event_id = arguments["event_id"]
        payload = {key: value for key, value in arguments.items() if key != "event_id"}
        updated = self.calendar.update_event(event_id, EventUpdate(**payload))
        return {
            "state": "completed",
            "event": updated.event.model_dump(mode="json"),
            "conflicts": [item.model_dump(mode="json") for item in updated.conflicts],
            "reply_text": f"已更新{updated.event.title}。",
        }

    def _update_event_draft(self, arguments: dict) -> dict:
        return self._update_event(arguments)

    def _delete_event(self, arguments: dict) -> dict:
        return self.calendar.delete_event(arguments["event_id"]).model_dump(mode="json")

    def _delete_event_draft(self, arguments: dict) -> dict:
        draft = self.calendar.create_delete_draft(arguments["event_id"])
        return {
            "operation_id": draft.id,
            "state": draft.state,
            "requires_confirmation": True,
            "reply_text": "确认删除该日程吗？",
        }

    def _confirm_operation(self, arguments: dict) -> dict:
        request = ConfirmOperationRequest(**arguments)
        result = self.calendar.confirm_operation(request.operation_id, request.confirmed)
        return result.model_dump(mode="json")

    def _check_availability(self, arguments: dict) -> dict:
        conflicts = self.calendar.check_conflicts(
            start_at=_parse_datetime(arguments["start_at"]),
            end_at=_parse_datetime(arguments.get("end_at")) if arguments.get("end_at") else None,
            calendar_id=arguments.get("calendar_id", "primary"),
        )
        return {
            "available": not conflicts,
            "conflicts": [item.model_dump(mode="json") for item in conflicts],
        }

    def _undo_last_operation(self, _: dict) -> dict:
        return self.calendar.undo_last_operation().model_dump(mode="json")

    def _get_today_hot_topics(self, arguments: dict) -> dict:
        result = self.news.get_today_news(
            timezone_name=arguments.get("timezone", "Asia/Shanghai"),
            category=arguments.get("category"),
            region=arguments.get("region", "CN"),
            limit=arguments.get("limit", 5),
            fresh=arguments.get("fresh", False),
        )
        return result.model_dump(mode="json")

    def _refresh_hot_topics(self, arguments: dict) -> dict:
        return self.news.refresh_hot_topics(HotTopicRefreshRequest(**arguments)).model_dump(mode="json")

    def _get_hot_topic_panel(self, arguments: dict) -> dict:
        result = self.news.get_hot_topic_panel(
            date=arguments["date"],
            timezone_name=arguments.get("timezone", "Asia/Shanghai"),
            limit=arguments.get("limit", 5),
            region=arguments.get("region", "CN"),
        )
        return result.model_dump(mode="json")

    def _get_meta(self, arguments: dict) -> dict:
        start = date.fromisoformat(arguments["start"])
        end = date.fromisoformat(arguments["end"])
        items = [
            CalendarMetaDayRead(
                date=item.date,
                is_holiday=item.is_holiday,
                is_adjusted_workday=item.is_adjusted_workday,
                holiday_name=item.holiday_name,
                solar_term=item.solar_term,
            )
            for item in AlmanacService().list_day_meta(start, end)
        ]
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "items": [item.model_dump(mode="json") for item in items],
        }

    def _get_daily_briefing(self, arguments: dict) -> dict:
        result = self.briefing.get_daily_briefing(
            date=arguments["date"],
            timezone_name=arguments.get("timezone", "Asia/Shanghai"),
        )
        return result.model_dump(mode="json")

    def _get_voice_capabilities(self, _: dict) -> dict:
        return asdict(self._require_asr().health())

    def _transcribe_audio_tool(self, arguments: dict) -> dict:
        transcript = self._transcribe_audio(arguments)
        return {
            "transcript": transcript.text,
            "asr_provider": transcript.provider,
            "locale": arguments.get("locale", "zh-CN"),
        }

    def _require_asr(self) -> ASRService:
        if self.asr is None:
            raise ASRUnavailableError("ASR 服务未注入。")
        return self.asr

    def _transcribe_audio(self, arguments: dict) -> ASRTranscript:
        audio_base64 = arguments.get("audio_base64")
        if not audio_base64:
            raise ASRRequestError("缺少 audio_base64。")
        try:
            audio = base64.b64decode(audio_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ASRRequestError("audio_base64 不是有效的 base64 数据。") from exc

        return self._require_asr().transcribe(
            filename=arguments.get("filename", "voice-input.webm"),
            audio=audio,
            content_type=arguments.get("content_type", "application/octet-stream"),
            locale=arguments.get("locale", "zh-CN"),
        )

    def _resolve_candidate(self, arguments: dict) -> dict:
        intent = arguments["intent"]
        candidate_id = arguments["candidate_id"]
        timezone_name = arguments.get("timezone", "Asia/Shanghai")
        session_id = arguments.get("session_id")
        slots = arguments.get("slots") or {}

        if intent == "delete_event":
            candidate = self.calendar.get_event(candidate_id)
            operation = self.calendar.create_delete_draft(candidate_id)
            return {
                "session_id": session_id,
                "state": "awaiting_confirmation",
                "intent": intent,
                "reply_text": f"找到{candidate.title}，确认取消吗？",
                "requires_user_input": True,
                "operation_id": operation.id,
                "event": None,
                "candidates": [
                    {
                        "id": candidate.id,
                        "title": candidate.title,
                        "start_at": candidate.start_at.isoformat(),
                        "end_at": candidate.end_at.isoformat() if candidate.end_at else None,
                    }
                ],
                "slots": slots,
                "missing_fields": [],
            }

        if intent == "update_event":
            existing = self.calendar.get_event(candidate_id)
            start_at, end_at = self._resolve_candidate_update_time(slots, timezone_name, existing)
            updated = self.calendar.update_event(
                candidate_id,
                EventUpdate(start_at=start_at, end_at=end_at),
            )
            conflict_text = "，但存在时间冲突" if updated.conflicts else ""
            return {
                "session_id": session_id,
                "state": "completed",
                "intent": intent,
                "reply_text": f"已将{updated.event.title}改到{start_at.strftime('%m月%d日%H:%M')}{conflict_text}。",
                "requires_user_input": False,
                "operation_id": None,
                "event": updated.event.model_dump(mode="json"),
                "candidates": [],
                "slots": slots,
                "missing_fields": [],
            }

        raise ValueError(f"Unsupported candidate intent: {intent}")

    @staticmethod
    def _resolve_candidate_update_time(
        slots: dict,
        timezone_name: str,
        existing,
    ) -> tuple[datetime, datetime | None]:
        zone = ZoneInfo(timezone_name)
        new_date = slots.get("new_date")
        new_start_time = slots.get("new_start_time")
        if not new_date or not new_start_time:
            raise ValueError("Missing new_date or new_start_time for update candidate resolution.")

        start_at = datetime.combine(
            date.fromisoformat(new_date),
            time.fromisoformat(new_start_time),
            tzinfo=zone,
        )
        new_end_time = slots.get("new_end_time")
        if new_end_time:
            return start_at, datetime.combine(
                date.fromisoformat(new_date),
                time.fromisoformat(new_end_time),
                tzinfo=zone,
            )
        if existing.end_at:
            return start_at, start_at + (existing.end_at - existing.start_at)
        return start_at, None
