from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from uuid import uuid4

import sqlite3
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.config import Settings, get_settings
from app.db import get_connection
from app.models import (
    CalendarMetaDayRead,
    CalendarMetaResponse,
    DailyBriefingResponse,
    ConfirmOperationRequest,
    ConfirmOperationResponse,
    EventCreate,
    EventCreateResponse,
    EventListResponse,
    EventRead,
    EventUpdate,
    HotTopicPanelResponse,
    HotTopicRefreshRequest,
    HotTopicRefreshResponse,
    MCPToolRequest,
    MCPToolResponse,
    NewsTodayResponse,
    OperationRead,
    TextCommandRequest,
    TextCommandResponse,
    UndoResponse,
    VoiceCapabilitiesResponse,
    VoiceCommandResponse,
)
from app.services.agent import ThirdPartyAgentParser
from app.services.almanac import AlmanacService
from app.services.asr import ASRRequestError, ASRService, ASRUnavailableError
from app.services.briefing import DailyBriefingService
from app.services.calendar import CalendarService
from app.services.command import TextCommandService
from app.services.mcp import MCPToolService
from app.services.news import NewsService
from app.services.nlu import HybridCommandParser


router = APIRouter(prefix="/api")


def get_calendar_service(
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
) -> CalendarService:
    return CalendarService(conn)


def get_news_service(
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
) -> NewsService:
    return NewsService(conn)


def get_briefing_service(
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
) -> DailyBriefingService:
    return DailyBriefingService(conn)


def get_command_parser(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HybridCommandParser:
    agent_parser = ThirdPartyAgentParser(settings)
    return HybridCommandParser(fallback_parser=agent_parser if agent_parser.is_configured() else None)


def get_text_command_service(
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    parser: HybridCommandParser = Depends(get_command_parser),
) -> TextCommandService:
    return TextCommandService(
        calendar=CalendarService(conn),
        news=NewsService(conn),
        briefing=DailyBriefingService(conn),
        parser=parser,
    )


def get_asr_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ASRService:
    return ASRService(settings)


def get_mcp_tool_service(
    conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    parser: HybridCommandParser = Depends(get_command_parser),
) -> MCPToolService:
    return MCPToolService(conn, parser=parser)


@router.get("/events", response_model=EventListResponse)
def list_events(
    start: Annotated[datetime, Query()],
    end: Annotated[datetime, Query()],
    calendar_id: str = "primary",
    service: CalendarService = Depends(get_calendar_service),
) -> EventListResponse:
    return EventListResponse(items=service.list_events(start, end, calendar_id))


@router.post("/events", response_model=EventCreateResponse, status_code=status.HTTP_201_CREATED)
def create_event(
    payload: EventCreate = Body(embed=False),
    service: CalendarService = Depends(get_calendar_service),
) -> EventCreateResponse:
    return service.create_event(payload)


@router.get("/events/{event_id}", response_model=EventRead)
def get_event(
    event_id: str,
    service: CalendarService = Depends(get_calendar_service),
) -> EventRead:
    try:
        return service.get_event(event_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Event not found") from exc


@router.patch("/events/{event_id}", response_model=EventCreateResponse)
def update_event(
    event_id: str,
    payload: EventUpdate = Body(embed=False),
    service: CalendarService = Depends(get_calendar_service),
) -> EventCreateResponse:
    try:
        return service.update_event(event_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Event not found") from exc


@router.delete("/events/{event_id}", response_model=OperationRead)
def delete_event(
    event_id: str,
    service: CalendarService = Depends(get_calendar_service),
) -> OperationRead:
    try:
        return service.delete_event(event_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Event not found") from exc


@router.post("/operations/undo", response_model=UndoResponse)
def undo_last_operation(
    service: CalendarService = Depends(get_calendar_service),
) -> UndoResponse:
    return service.undo_last_operation()


@router.post("/operations/confirm", response_model=ConfirmOperationResponse)
def confirm_operation(
    payload: ConfirmOperationRequest,
    service: CalendarService = Depends(get_calendar_service),
) -> ConfirmOperationResponse:
    try:
        return service.confirm_operation(payload.operation_id, payload.confirmed)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Operation not found") from exc


@router.post("/text/commands", response_model=TextCommandResponse)
def handle_text_command(
    payload: TextCommandRequest,
    service: TextCommandService = Depends(get_text_command_service),
) -> TextCommandResponse:
    return service.handle(payload)


@router.get("/voice/capabilities", response_model=VoiceCapabilitiesResponse)
def get_voice_capabilities(
    asr: ASRService = Depends(get_asr_service),
) -> VoiceCapabilitiesResponse:
    health = asr.health()
    return VoiceCapabilitiesResponse(
        server_asr_available=health.available,
        provider=health.provider,
        model=health.model,
        ready=health.ready,
        warming=health.warming,
        detail=health.detail,
    )


@router.post("/voice/commands", response_model=VoiceCommandResponse)
async def handle_voice_command(
    audio: UploadFile = File(...),
    timezone: str = Form("Asia/Shanghai"),
    locale: str = Form("zh-CN"),
    session_id: str | None = Form(None),
    now: datetime | None = Form(None),
    asr: ASRService = Depends(get_asr_service),
    service: TextCommandService = Depends(get_text_command_service),
) -> VoiceCommandResponse:
    try:
        transcript = asr.transcribe(
            filename=audio.filename or "voice-input.webm",
            audio=await audio.read(),
            content_type=audio.content_type or "application/octet-stream",
            locale=locale,
        )
    except ASRUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ASRRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    response = service.handle(
        TextCommandRequest(
            text=transcript.text,
            timezone=timezone,
            locale=locale,
            session_id=session_id,
            now=now,
        )
    )
    return VoiceCommandResponse(
        command_id=f"cmd_{uuid4().hex}",
        asr_provider=transcript.provider,
        **response.model_dump(),
    )


@router.get("/news/today", response_model=NewsTodayResponse)
def get_today_news(
    category: str | None = None,
    region: str = "CN",
    limit: int = 5,
    timezone: str = "Asia/Shanghai",
    fresh: bool = False,
    service: NewsService = Depends(get_news_service),
) -> NewsTodayResponse:
    return service.get_today_news(
        timezone_name=timezone,
        category=category,
        region=region,
        limit=limit,
        fresh=fresh,
    )


@router.get("/calendar/hot-topics", response_model=HotTopicPanelResponse)
def get_calendar_hot_topics(
    date: str,
    timezone: str = "Asia/Shanghai",
    limit: int = 5,
    service: NewsService = Depends(get_news_service),
) -> HotTopicPanelResponse:
    return service.get_hot_topic_panel(date=date, timezone_name=timezone, limit=limit)


@router.get("/calendar/meta", response_model=CalendarMetaResponse)
def get_calendar_meta(
    start: Annotated[date, Query()],
    end: Annotated[date, Query()],
) -> CalendarMetaResponse:
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
    return CalendarMetaResponse(start=start, end=end, items=items)


@router.post("/news/hot-topics/refresh", response_model=HotTopicRefreshResponse)
def refresh_hot_topics(
    payload: HotTopicRefreshRequest,
    service: NewsService = Depends(get_news_service),
) -> HotTopicRefreshResponse:
    return service.refresh_hot_topics(payload)


@router.get("/briefings/daily", response_model=DailyBriefingResponse)
def get_daily_briefing(
    date: str,
    timezone: str = "Asia/Shanghai",
    service: DailyBriefingService = Depends(get_briefing_service),
) -> DailyBriefingResponse:
    return service.get_daily_briefing(date=date, timezone_name=timezone)


@router.post("/mcp/tools/{tool_name}", response_model=MCPToolResponse)
def call_mcp_tool(
    tool_name: str,
    payload: MCPToolRequest,
    service: MCPToolService = Depends(get_mcp_tool_service),
) -> MCPToolResponse:
    try:
        return service.call_tool(tool_name, payload.arguments)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="MCP tool not found") from exc
