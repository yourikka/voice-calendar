from __future__ import annotations

import base64
import binascii
from dataclasses import asdict
import sqlite3
from datetime import date, datetime, time
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
        )
        self.asr = asr

    def call_tool(self, tool_name: str, arguments: dict) -> MCPToolResponse:
        if tool_name == "calendar.parse_command":
            result = self.parser.parse(TextCommandRequest(**arguments))
            return self._response(tool_name, result.model_dump(mode="json"))

        if tool_name == "calendar.handle_command":
            result = self.commands.handle(TextCommandRequest(**arguments))
            return self._response(tool_name, result.model_dump(mode="json"))

        if tool_name == "voice.handle_command":
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
            return self._response(tool_name, payload)

        if tool_name == "calendar.list_events":
            result = self.calendar.list_events(
                start=_parse_datetime(arguments["start"]),
                end=_parse_datetime(arguments["end"]),
                calendar_id=arguments.get("calendar_id", "primary"),
            )
            return self._response(tool_name, {"items": [item.model_dump(mode="json") for item in result]})

        if tool_name == "calendar.get_event":
            result = self.calendar.get_event(arguments["event_id"])
            return self._response(tool_name, result.model_dump(mode="json"))

        if tool_name == "calendar.create_event":
            created = self.calendar.create_event(EventCreate(**arguments))
            return self._response(
                tool_name,
                {
                    "state": "completed",
                    "event": created.event.model_dump(mode="json"),
                    "conflicts": [item.model_dump(mode="json") for item in created.conflicts],
                    "reply_text": f"已创建{created.event.title}。",
                },
            )

        if tool_name == "calendar.create_event_draft":
            created = self.calendar.create_event(EventCreate(**arguments))
            return self._response(
                tool_name,
                {
                    "state": "completed",
                    "requires_confirmation": False,
                    "event": created.event.model_dump(mode="json"),
                    "conflicts": [item.model_dump(mode="json") for item in created.conflicts],
                    "reply_text": f"已创建{created.event.title}。",
                },
            )

        if tool_name == "calendar.update_event":
            event_id = arguments["event_id"]
            payload = {key: value for key, value in arguments.items() if key != "event_id"}
            updated = self.calendar.update_event(event_id, EventUpdate(**payload))
            return self._response(
                tool_name,
                {
                    "state": "completed",
                    "event": updated.event.model_dump(mode="json"),
                    "conflicts": [item.model_dump(mode="json") for item in updated.conflicts],
                    "reply_text": f"已更新{updated.event.title}。",
                },
            )

        if tool_name == "calendar.resolve_candidate":
            return self._response(tool_name, self._resolve_candidate(arguments))

        if tool_name == "calendar.update_event_draft":
            event_id = arguments["event_id"]
            payload = {key: value for key, value in arguments.items() if key != "event_id"}
            updated = self.calendar.update_event(event_id, EventUpdate(**payload))
            return self._response(
                tool_name,
                {
                    "state": "completed",
                    "event": updated.event.model_dump(mode="json"),
                    "conflicts": [item.model_dump(mode="json") for item in updated.conflicts],
                    "reply_text": f"已更新{updated.event.title}。",
                },
            )

        if tool_name == "calendar.delete_event":
            deleted = self.calendar.delete_event(arguments["event_id"])
            return self._response(tool_name, deleted.model_dump(mode="json"))

        if tool_name == "calendar.delete_event_draft":
            draft = self.calendar.create_delete_draft(arguments["event_id"])
            return self._response(
                tool_name,
                {
                    "operation_id": draft.id,
                    "state": draft.state,
                    "requires_confirmation": True,
                    "reply_text": "确认删除该日程吗？",
                },
            )

        if tool_name == "calendar.confirm_operation":
            request = ConfirmOperationRequest(**arguments)
            result = self.calendar.confirm_operation(request.operation_id, request.confirmed)
            return self._response(tool_name, result.model_dump(mode="json"))

        if tool_name == "calendar.check_availability":
            conflicts = self.calendar.check_conflicts(
                start_at=_parse_datetime(arguments["start_at"]),
                end_at=_parse_datetime(arguments.get("end_at")) if arguments.get("end_at") else None,
                calendar_id=arguments.get("calendar_id", "primary"),
            )
            return self._response(
                tool_name,
                {
                    "available": not conflicts,
                    "conflicts": [item.model_dump(mode="json") for item in conflicts],
                },
            )

        if tool_name == "calendar.undo_last_operation":
            result = self.calendar.undo_last_operation()
            return self._response(tool_name, result.model_dump(mode="json"))

        if tool_name == "news.get_today_hot_topics":
            result = self.news.get_today_news(
                timezone_name=arguments.get("timezone", "Asia/Shanghai"),
                category=arguments.get("category"),
                region=arguments.get("region", "CN"),
                limit=arguments.get("limit", 5),
                fresh=arguments.get("fresh", False),
            )
            return self._response(tool_name, result.model_dump(mode="json"))

        if tool_name == "news.refresh_hot_topics":
            result = self.news.refresh_hot_topics(HotTopicRefreshRequest(**arguments))
            return self._response(tool_name, result.model_dump(mode="json"))

        if tool_name == "calendar.get_hot_topic_panel":
            result = self.news.get_hot_topic_panel(
                date=arguments["date"],
                timezone_name=arguments.get("timezone", "Asia/Shanghai"),
                limit=arguments.get("limit", 5),
                region=arguments.get("region", "CN"),
            )
            return self._response(tool_name, result.model_dump(mode="json"))

        if tool_name == "calendar.get_meta":
            items = [
                CalendarMetaDayRead(
                    date=item.date,
                    is_holiday=item.is_holiday,
                    is_adjusted_workday=item.is_adjusted_workday,
                    holiday_name=item.holiday_name,
                    solar_term=item.solar_term,
                )
                for item in AlmanacService().list_day_meta(
                    date.fromisoformat(arguments["start"]),
                    date.fromisoformat(arguments["end"]),
                )
            ]
            return self._response(
                tool_name,
                {
                    "start": date.fromisoformat(arguments["start"]).isoformat(),
                    "end": date.fromisoformat(arguments["end"]).isoformat(),
                    "items": [item.model_dump(mode="json") for item in items],
                },
            )

        if tool_name == "briefing.get_daily_briefing":
            result = self.briefing.get_daily_briefing(
                date=arguments["date"],
                timezone_name=arguments.get("timezone", "Asia/Shanghai"),
            )
            return self._response(tool_name, result.model_dump(mode="json"))

        if tool_name == "voice.get_capabilities":
            return self._response(tool_name, asdict(self._require_asr().health()))

        if tool_name == "voice.transcribe_audio":
            transcript = self._transcribe_audio(arguments)
            return self._response(
                tool_name,
                {
                    "transcript": transcript.text,
                    "asr_provider": transcript.provider,
                    "locale": arguments.get("locale", "zh-CN"),
                },
            )

        raise KeyError(tool_name)

    @staticmethod
    def _response(tool_name: str, result: dict) -> MCPToolResponse:
        return MCPToolResponse(tool=tool_name, result=result)

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
