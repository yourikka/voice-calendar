from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from mcp.server.fastmcp import Context, FastMCP

from app.api import get_command_parser
from app.config import get_settings
from app.db import get_connection_context, initialize_database
from app.services.mcp import MCPToolService


MCP_INSTRUCTIONS = (
    "Voice Calendar MCP server. "
    "Use calendar tools for event CRUD, conflict checks, command parsing, hot topics, and daily briefings. "
    "Prefer parse_command when a user request is ambiguous before mutating calendar data."
)


def build_mcp_server() -> FastMCP:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_: FastMCP) -> AsyncIterator[dict[str, Any]]:
        initialize_database(settings)
        with get_connection_context(settings) as conn:
            parser = get_command_parser(settings)
            yield {"tool_service": MCPToolService(conn, parser=parser)}

    server = FastMCP(
        name="voice-calendar",
        instructions=MCP_INSTRUCTIONS,
        host=settings.mcp_host,
        port=settings.mcp_port,
        streamable_http_path="/mcp",
        sse_path="/sse",
        message_path="/messages/",
        debug=False,
        log_level="INFO",
        lifespan=lifespan,
    )

    @server.tool(
        name="calendar.parse_command",
        description="Parse a natural-language calendar command into intent, slots, missing fields, and confidence.",
    )
    def parse_calendar_command(
        text: str,
        timezone: str = "Asia/Shanghai",
        locale: str = "zh-CN",
        session_id: str | None = None,
        now: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        arguments = {
            "text": text,
            "timezone": timezone,
            "locale": locale,
            "session_id": session_id,
            "now": now,
        }
        return _call(ctx, "calendar.parse_command", _drop_none(arguments))

    @server.tool(
        name="calendar.list_events",
        description="List calendar events between start and end timestamps.",
    )
    def list_calendar_events(
        start: str,
        end: str,
        calendar_id: str = "primary",
        ctx: Context = None,
    ) -> dict[str, Any]:
        return _call(
            ctx,
            "calendar.list_events",
            {"start": start, "end": end, "calendar_id": calendar_id},
        )

    @server.tool(
        name="calendar.create_event_draft",
        description="Create an event or reminder in the primary calendar.",
    )
    def create_calendar_event(
        title: str,
        start_at: str,
        end_at: str | None = None,
        timezone: str = "Asia/Shanghai",
        type: str = "event",
        description: str = "",
        location: str | None = None,
        participants: list[str] | None = None,
        reminders: list[dict[str, Any]] | None = None,
        recurrence_rule: dict[str, Any] | None = None,
        calendar_id: str = "primary",
        source: str = "mcp",
        ctx: Context = None,
    ) -> dict[str, Any]:
        return _call(
            ctx,
            "calendar.create_event_draft",
            _drop_none(
                {
                    "title": title,
                    "start_at": start_at,
                    "end_at": end_at,
                    "timezone": timezone,
                    "type": type,
                    "description": description,
                    "location": location,
                    "participants": participants or [],
                    "reminders": reminders or [],
                    "recurrence_rule": recurrence_rule,
                    "calendar_id": calendar_id,
                    "source": source,
                }
            ),
        )

    @server.tool(
        name="calendar.update_event_draft",
        description="Update an existing calendar event by event_id.",
    )
    def update_calendar_event(
        event_id: str,
        title: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        timezone: str | None = None,
        description: str | None = None,
        location: str | None = None,
        participants: list[str] | None = None,
        reminders: list[dict[str, Any]] | None = None,
        recurrence_rule: dict[str, Any] | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        return _call(
            ctx,
            "calendar.update_event_draft",
            _drop_none(
                {
                    "event_id": event_id,
                    "title": title,
                    "start_at": start_at,
                    "end_at": end_at,
                    "timezone": timezone,
                    "description": description,
                    "location": location,
                    "participants": participants,
                    "reminders": reminders,
                    "recurrence_rule": recurrence_rule,
                }
            ),
        )

    @server.tool(
        name="calendar.delete_event_draft",
        description="Create a deletion draft for a calendar event. Requires confirmation.",
    )
    def delete_calendar_event(event_id: str, ctx: Context = None) -> dict[str, Any]:
        return _call(ctx, "calendar.delete_event_draft", {"event_id": event_id})

    @server.tool(
        name="calendar.confirm_operation",
        description="Confirm or reject a previously created operation draft.",
    )
    def confirm_calendar_operation(
        operation_id: str,
        confirmed: bool = True,
        ctx: Context = None,
    ) -> dict[str, Any]:
        return _call(
            ctx,
            "calendar.confirm_operation",
            {"operation_id": operation_id, "confirmed": confirmed},
        )

    @server.tool(
        name="calendar.check_availability",
        description="Check whether a time range has conflicts.",
    )
    def check_calendar_availability(
        start_at: str,
        end_at: str | None = None,
        calendar_id: str = "primary",
        ctx: Context = None,
    ) -> dict[str, Any]:
        return _call(
            ctx,
            "calendar.check_availability",
            _drop_none({"start_at": start_at, "end_at": end_at, "calendar_id": calendar_id}),
        )

    @server.tool(
        name="calendar.undo_last_operation",
        description="Undo the most recent confirmed calendar mutation if still allowed.",
    )
    def undo_last_calendar_operation(ctx: Context = None) -> dict[str, Any]:
        return _call(ctx, "calendar.undo_last_operation", {})

    @server.tool(
        name="news.get_today_hot_topics",
        description="Fetch today's hot topics for a timezone and region.",
    )
    def get_today_hot_topics(
        timezone: str = "Asia/Shanghai",
        category: str | None = None,
        region: str = "CN",
        limit: int = 5,
        fresh: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        return _call(
            ctx,
            "news.get_today_hot_topics",
            _drop_none(
                {
                    "timezone": timezone,
                    "category": category,
                    "region": region,
                    "limit": limit,
                    "fresh": fresh,
                }
            ),
        )

    @server.tool(
        name="briefing.get_daily_briefing",
        description="Get a daily briefing combining schedule context and hot topics.",
    )
    def get_daily_briefing(
        date: str,
        timezone: str = "Asia/Shanghai",
        ctx: Context = None,
    ) -> dict[str, Any]:
        return _call(ctx, "briefing.get_daily_briefing", {"date": date, "timezone": timezone})

    return server


def _call(ctx: Context, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    tool_service: MCPToolService = ctx.request_context.lifespan_context["tool_service"]
    return tool_service.call_tool(tool_name, arguments).result


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}
