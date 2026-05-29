from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.models import EventCreate, Reminder, TextCommandRequest, TextCommandResponse
from app.services.calendar import CalendarService


WEEKDAY_MAP = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}

NUMBER_MAP = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
    "十三": 13,
    "十四": 14,
    "十五": 15,
    "十六": 16,
    "十七": 17,
    "十八": 18,
    "十九": 19,
    "二十": 20,
}


def _session_id(existing: str | None) -> str:
    return existing or f"ses_{uuid4().hex}"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text.strip())


def _now(request: TextCommandRequest) -> datetime:
    zone = ZoneInfo(request.timezone)
    if request.now:
        return request.now.astimezone(zone)
    return datetime.now(zone)


def _parse_chinese_number(raw: str) -> int:
    if raw.isdigit():
        return int(raw)
    if raw in NUMBER_MAP:
        return NUMBER_MAP[raw]
    if "十" in raw:
        left, _, right = raw.partition("十")
        tens = NUMBER_MAP.get(left, 1) if left else 1
        ones = NUMBER_MAP.get(right, 0) if right else 0
        return tens * 10 + ones
    return NUMBER_MAP.get(raw, 0)


def _date_range(text: str, base: datetime) -> tuple[datetime, datetime]:
    local_date = base.date()
    if "后天" in text:
        local_date += timedelta(days=2)
    elif "明天" in text or "明日" in text or "明早" in text:
        local_date += timedelta(days=1)
    else:
        weekday_match = re.search(r"(下周|下个周|这周|本周)?周([一二三四五六日天])", text)
        if weekday_match:
            target = WEEKDAY_MAP[weekday_match.group(2)]
            delta = target - local_date.weekday()
            if weekday_match.group(1) in {"下周", "下个周"}:
                delta += 7
            elif delta < 0:
                delta += 7
            local_date += timedelta(days=delta)
    start = datetime.combine(local_date, time.min, tzinfo=base.tzinfo)
    return start, start + timedelta(days=1)


def _parse_time(text: str) -> time | None:
    match = re.search(r"([零一二两三四五六七八九十\d]{1,3})点(半|[零一二三四五六七八九十\d]{1,3}分?)?", text)
    if not match:
        if "早上" in text or "明早" in text:
            return time(hour=8)
        if "上午" in text:
            return time(hour=10)
        if "下午" in text:
            return time(hour=15)
        if "晚上" in text:
            return time(hour=20)
        return None

    hour = _parse_chinese_number(match.group(1))
    minute_raw = match.group(2)
    minute = 0
    if minute_raw == "半":
        minute = 30
    elif minute_raw:
        minute = _parse_chinese_number(minute_raw.removesuffix("分"))
    if ("下午" in text or "晚上" in text) and hour < 12:
        hour += 12
    return time(hour=hour, minute=minute)


def _extract_title_after(text: str, marker: str) -> str:
    _, _, title = text.partition(marker)
    return title.strip("，。,. ") or "未命名事项"


class TextCommandService:
    def __init__(self, calendar: CalendarService) -> None:
        self.calendar = calendar

    def handle(self, request: TextCommandRequest) -> TextCommandResponse:
        text = _normalize(request.text)
        base = _now(request)
        session_id = _session_id(request.session_id)

        if "简报" in text:
            return TextCommandResponse(
                session_id=session_id,
                state="completed",
                transcript=request.text,
                intent="get_daily_briefing",
                reply_text="今日简报功能已进入简报服务处理流程。",
            )
        if "热点" in text or "新闻" in text or "资讯" in text:
            return TextCommandResponse(
                session_id=session_id,
                state="completed",
                transcript=request.text,
                intent="get_today_news",
                reply_text="今日热点功能已进入资讯服务处理流程。",
            )
        if text.startswith("撤销") or "撤销刚才" in text:
            result = self.calendar.undo_last_operation()
            return TextCommandResponse(
                session_id=session_id,
                state=result.state,
                transcript=request.text,
                intent="undo_last_operation",
                reply_text=result.reply_text,
                event=result.event,
            )
        if text.startswith("取消") or text.startswith("删除"):
            return self._handle_delete(request, text, base, session_id)
        if "有什么安排" in text or "有哪些安排" in text or "有事吗" in text:
            return self._handle_list(request, text, base, session_id)
        if "提醒我" in text:
            return self._handle_create_reminder(request, text, base, session_id)
        if "开会" in text or "会议" in text or "面试" in text:
            return self._handle_create_event(request, text, base, session_id)

        return TextCommandResponse(
            session_id=session_id,
            state="unsupported",
            transcript=request.text,
            intent="unknown",
            reply_text="暂时无法理解这条指令，请换一种说法。",
            requires_user_input=True,
        )

    def _handle_create_reminder(
        self,
        request: TextCommandRequest,
        text: str,
        base: datetime,
        session_id: str,
    ) -> TextCommandResponse:
        day_start, _ = _date_range(text, base)
        parsed_time = _parse_time(text)
        if parsed_time is None:
            return TextCommandResponse(
                session_id=session_id,
                state="collecting_slots",
                transcript=request.text,
                intent="create_reminder",
                reply_text="什么时候提醒你？",
                requires_user_input=True,
            )
        start_at = datetime.combine(day_start.date(), parsed_time, tzinfo=day_start.tzinfo)
        title = _extract_title_after(text, "提醒我")
        created = self.calendar.create_event(
            EventCreate(
                title=title,
                type="reminder",
                start_at=start_at,
                end_at=None,
                timezone=request.timezone,
                reminders=[Reminder(method="notification", offset_minutes=0)],
                source="text",
            )
        )
        return TextCommandResponse(
            session_id=session_id,
            state="completed",
            transcript=request.text,
            intent="create_reminder",
            reply_text=f"已设置{start_at.strftime('%m月%d日%H:%M')}提醒你{title}。",
            event=created.event,
        )

    def _handle_create_event(
        self,
        request: TextCommandRequest,
        text: str,
        base: datetime,
        session_id: str,
    ) -> TextCommandResponse:
        day_start, _ = _date_range(text, base)
        parsed_time = _parse_time(text)
        if parsed_time is None:
            return TextCommandResponse(
                session_id=session_id,
                state="collecting_slots",
                transcript=request.text,
                intent="create_event",
                reply_text="这个事件几点开始？",
                requires_user_input=True,
            )
        start_at = datetime.combine(day_start.date(), parsed_time, tzinfo=day_start.tzinfo)
        end_at = start_at + timedelta(hours=1)
        title = "会议" if "会议" in text or "开会" in text else "面试"
        created = self.calendar.create_event(
            EventCreate(
                title=title,
                type="event",
                start_at=start_at,
                end_at=end_at,
                timezone=request.timezone,
                source="text",
            )
        )
        conflict_text = "，但存在时间冲突" if created.conflicts else ""
        return TextCommandResponse(
            session_id=session_id,
            state="completed",
            transcript=request.text,
            intent="create_event",
            reply_text=f"已创建{start_at.strftime('%m月%d日%H:%M')}的{title}{conflict_text}。",
            event=created.event,
        )

    def _handle_list(
        self,
        request: TextCommandRequest,
        text: str,
        base: datetime,
        session_id: str,
    ) -> TextCommandResponse:
        start, end = _date_range(text, base)
        events = self.calendar.list_events(start, end)
        if not events:
            reply = "这段时间没有已安排的日程。"
        else:
            pieces = [f"{event.start_at.strftime('%H:%M')} {event.title}" for event in events[:3]]
            reply = f"这段时间有 {len(events)} 个安排：" + "，".join(pieces)
        return TextCommandResponse(
            session_id=session_id,
            state="completed",
            transcript=request.text,
            intent="list_events",
            reply_text=reply,
        )

    def _handle_delete(
        self,
        request: TextCommandRequest,
        text: str,
        base: datetime,
        session_id: str,
    ) -> TextCommandResponse:
        start, end = _date_range(text, base)
        keyword = text.removeprefix("取消").removeprefix("删除")
        for token in ("今天", "明天", "明日", "后天", "上午", "下午", "晚上", "的"):
            keyword = keyword.replace(token, "")
        keyword = keyword or "会议"
        candidates = self.calendar.find_events_by_title(keyword, start, end)
        if not candidates:
            return TextCommandResponse(
                session_id=session_id,
                state="not_found",
                transcript=request.text,
                intent="delete_event",
                reply_text="没有找到匹配的日程。",
            )
        if len(candidates) > 1:
            return TextCommandResponse(
                session_id=session_id,
                state="selecting_candidate",
                transcript=request.text,
                intent="delete_event",
                reply_text=f"找到 {len(candidates)} 个匹配日程，请选择要取消哪一个。",
                requires_user_input=True,
                candidates=candidates,
            )
        operation = self.calendar.create_delete_draft(candidates[0].id)
        return TextCommandResponse(
            session_id=session_id,
            state="awaiting_confirmation",
            transcript=request.text,
            intent="delete_event",
            reply_text=f"找到{candidates[0].title}，确认取消吗？",
            requires_user_input=True,
            operation_id=operation.id,
            candidates=candidates,
        )

