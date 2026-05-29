from __future__ import annotations

import sqlite3
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models import BriefingSection, DailyBriefingResponse
from app.services.calendar import CalendarService
from app.services.news import NewsService


class DailyBriefingService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_daily_briefing(self, date: str, timezone_name: str) -> DailyBriefingResponse:
        zone = ZoneInfo(timezone_name)
        day = datetime.fromisoformat(date).date()
        start = datetime.combine(day, time.min, tzinfo=zone)
        end = start + timedelta(days=1)
        events = CalendarService(self.conn).list_events(start, end)
        news = NewsService(self.conn).get_today_news(timezone_name=timezone_name, limit=5)

        calendar_summary = (
            "今天没有已安排的日程。"
            if not events
            else f"今天你有 {len(events)} 个日程，最早是 {events[0].start_at.strftime('%H:%M')} 的{events[0].title}。"
        )
        news_summary = news.spoken_summary
        sections = [
            BriefingSection(type="calendar", spoken_summary=calendar_summary),
            BriefingSection(type="news", spoken_summary=news_summary),
        ]
        return DailyBriefingResponse(
            date=date,
            timezone=timezone_name,
            sections=sections,
            spoken_summary=f"{calendar_summary}{news_summary}",
        )

