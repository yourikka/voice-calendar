from __future__ import annotations

import sqlite3
from datetime import datetime

from app.models import (
    ConfirmOperationRequest,
    EventCreate,
    EventUpdate,
    MCPToolResponse,
    TextCommandRequest,
)
from app.services.briefing import DailyBriefingService
from app.services.calendar import CalendarService
from app.services.command import TextCommandService
from app.services.news import NewsService
from app.services.nlu import HybridCommandParser


class MCPToolService:
    def __init__(self, conn: sqlite3.Connection, parser: HybridCommandParser | None = None) -> None:
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

    def call_tool(self, tool_name: str, arguments: dict) -> MCPToolResponse:
        if tool_name == "calendar.parse_command":
            result = self.parser.parse(TextCommandRequest(**arguments))
            return self._response(tool_name, result.model_dump(mode="json"))

        if tool_name == "calendar.handle_command":
            result = self.commands.handle(TextCommandRequest(**arguments))
            return self._response(tool_name, result.model_dump(mode="json"))

        if tool_name == "calendar.list_events":
            result = self.calendar.list_events(
                start=datetime.fromisoformat(arguments["start"]),
                end=datetime.fromisoformat(arguments["end"]),
                calendar_id=arguments.get("calendar_id", "primary"),
            )
            return self._response(tool_name, {"items": [item.model_dump(mode="json") for item in result]})

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

        if tool_name == "calendar.update_event_draft":
            event_id = arguments.pop("event_id")
            updated = self.calendar.update_event(event_id, EventUpdate(**arguments))
            return self._response(
                tool_name,
                {
                    "state": "completed",
                    "event": updated.event.model_dump(mode="json"),
                    "conflicts": [item.model_dump(mode="json") for item in updated.conflicts],
                    "reply_text": f"已更新{updated.event.title}。",
                },
            )

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
                start_at=datetime.fromisoformat(arguments["start_at"]),
                end_at=datetime.fromisoformat(arguments.get("end_at")) if arguments.get("end_at") else None,
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

        if tool_name == "briefing.get_daily_briefing":
            result = self.briefing.get_daily_briefing(
                date=arguments["date"],
                timezone_name=arguments.get("timezone", "Asia/Shanghai"),
            )
            return self._response(tool_name, result.model_dump(mode="json"))

        raise KeyError(tool_name)

    @staticmethod
    def _response(tool_name: str, result: dict) -> MCPToolResponse:
        return MCPToolResponse(tool=tool_name, result=result)
