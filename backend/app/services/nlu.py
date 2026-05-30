from __future__ import annotations

import re
from datetime import datetime

from app.models import ParsedCommand, TextCommandRequest
from app.services.nlu_datetime import (
    UPDATE_ACTION_RE,
    _format_time_value,
    _parse_reminder_offset,
    _parse_time_range,
    _resolve_date,
    _resolve_relative_reminder_datetime,
    _resolve_window,
    normalize_text,
    request_now,
)
from app.services.nlu_titles import (
    _extract_delete_title,
    _extract_event_title,
    _extract_participants,
    _extract_reminder_title,
    _extract_update_title,
)


LIST_QUERY_PATTERNS = (
    "有什么安排",
    "有哪些安排",
    "有事吗",
    "有什么事",
    "有啥事",
    "都有什么事",
    "都有哪些安排",
    "什么安排",
    "啥安排",
    "有什么日程",
    "有哪些日程",
)


def _news_category(text: str) -> str | None:
    if "科技" in text:
        return "technology"
    if "财经" in text or "金融" in text:
        return "finance"
    return None


def _looks_like_list_query(text: str) -> bool:
    if any(pattern in text for pattern in LIST_QUERY_PATTERNS):
        return True
    return bool(re.search(r"(今天|明天|后天|明晚|今晚|本周|这周|下周).*(忙不忙|空不空)", text))


def _looks_like_reminder(text: str) -> bool:
    return any(token in text for token in ("提醒我", "提醒", "记一下", "记得", "帮我记", "帮我记下", "记个"))


class RuleBasedCommandParser:
    def parse(self, request: TextCommandRequest) -> ParsedCommand:
        text = normalize_text(request.text)
        base = request_now(request)

        if "简报" in text:
            return ParsedCommand(
                transcript=request.text,
                normalized_text=text,
                intent="get_daily_briefing",
                slots={
                    "date": base.date().isoformat(),
                    "briefing_sections": ["calendar", "reminders", "news"],
                },
                confidence=0.98,
            )

        if "热点" in text or "新闻" in text or "资讯" in text:
            return ParsedCommand(
                transcript=request.text,
                normalized_text=text,
                intent="get_today_news",
                slots={
                    "date": (_resolve_date(text, base) or base.date()).isoformat(),
                    "limit": 5,
                    "news_category": _news_category(text),
                },
                confidence=0.96,
            )

        if text.startswith("撤销") or "撤销刚才" in text:
            return ParsedCommand(
                transcript=request.text,
                normalized_text=text,
                intent="undo_last_operation",
                confidence=0.99,
            )

        if UPDATE_ACTION_RE.search(text):
            return self._parse_update(request, text, base)

        if text.startswith("取消") or text.startswith("删除") or text.startswith("去掉"):
            return self._parse_delete(request, text, base)

        if _looks_like_list_query(text) or "日程" in text:
            return self._parse_list(request, text, base)

        if self._looks_like_event(text):
            return self._parse_event(request, text, base)

        if _looks_like_reminder(text):
            return self._parse_reminder(request, text, base)

        return ParsedCommand(
            transcript=request.text,
            normalized_text=text,
            intent="unknown",
            confidence=0.0,
        )

    @staticmethod
    def _looks_like_event(text: str) -> bool:
        if any(keyword in text for keyword in ("开会", "会议", "面试", "评审会", "复盘会")):
            return True
        start_time, end_time = _parse_time_range(text)
        return start_time is not None and end_time is not None

    def _parse_reminder(self, request: TextCommandRequest, text: str, base: datetime) -> ParsedCommand:
        relative_at = _resolve_relative_reminder_datetime(text, base)
        if relative_at is not None:
            return ParsedCommand(
                transcript=request.text,
                normalized_text=text,
                intent="create_reminder",
                slots={
                    "title": _extract_reminder_title(text),
                    "date": relative_at.date().isoformat(),
                    "time": _format_time_value(relative_at.timetz().replace(tzinfo=None)),
                },
                confidence=0.95,
            )

        day = _resolve_date(text, base) or base.date()
        start_time, _ = _parse_time_range(text)
        missing_fields: list[str] = []
        if start_time is None:
            missing_fields.append("time")
        confidence = 0.92 if not missing_fields else 0.55
        if "提醒" not in text:
            confidence = min(confidence, 0.65)
        return ParsedCommand(
            transcript=request.text,
            normalized_text=text,
            intent="create_reminder",
            slots={
                "title": _extract_reminder_title(text),
                "date": day.isoformat(),
                "time": _format_time_value(start_time),
            },
            missing_fields=missing_fields,
            confidence=confidence,
        )

    def _parse_event(self, request: TextCommandRequest, text: str, base: datetime) -> ParsedCommand:
        day = _resolve_date(text, base) or base.date()
        start_time, end_time = _parse_time_range(text)
        missing_fields: list[str] = []
        if start_time is None:
            missing_fields.append("start_time")
        return ParsedCommand(
            transcript=request.text,
            normalized_text=text,
            intent="create_event",
            slots={
                "title": _extract_event_title(text),
                "date": day.isoformat(),
                "start_time": _format_time_value(start_time),
                "end_time": _format_time_value(end_time),
                "participants": _extract_participants(text),
                "reminder_offset_minutes": _parse_reminder_offset(text),
            },
            missing_fields=missing_fields,
            confidence=0.93 if not missing_fields else 0.56,
        )

    def _parse_list(self, request: TextCommandRequest, text: str, base: datetime) -> ParsedCommand:
        start, end = _resolve_window(text, base)
        return ParsedCommand(
            transcript=request.text,
            normalized_text=text,
            intent="list_events",
            slots={"start": start.isoformat(), "end": end.isoformat()},
            confidence=0.94,
        )

    def _parse_delete(self, request: TextCommandRequest, text: str, base: datetime) -> ParsedCommand:
        start, end = _resolve_window(text, base)
        delete_all = bool(re.search(r"(所有|全部)", text))
        return ParsedCommand(
            transcript=request.text,
            normalized_text=text,
            intent="delete_event",
            slots={
                "title": _extract_delete_title(text),
                "start": start.isoformat(),
                "end": end.isoformat(),
                "delete_all": delete_all,
            },
            confidence=0.91,
        )

    def _parse_update(self, request: TextCommandRequest, text: str, base: datetime) -> ParsedCommand:
        match = UPDATE_ACTION_RE.search(text)
        before_text = text[: match.start()] if match else text
        after_text = text[match.end() :] if match else ""
        target_date = _resolve_date(before_text, base)
        new_date = _resolve_date(after_text, base) or target_date or base.date()
        new_start_time, new_end_time = _parse_time_range(after_text)
        title = _extract_update_title(before_text)
        missing_fields: list[str] = []
        if not title:
            missing_fields.append("title")
        if new_start_time is None:
            missing_fields.append("new_time")
        return ParsedCommand(
            transcript=request.text,
            normalized_text=text,
            intent="update_event",
            slots={
                "title": title,
                "target_date": target_date.isoformat() if target_date else None,
                "new_date": new_date.isoformat(),
                "new_start_time": _format_time_value(new_start_time),
                "new_end_time": _format_time_value(new_end_time),
            },
            missing_fields=missing_fields,
            confidence=0.9 if not missing_fields else 0.5,
        )


class HybridCommandParser:
    def __init__(self, fallback_parser: object | None = None) -> None:
        self.rule_parser = RuleBasedCommandParser()
        self.fallback_parser = fallback_parser

    def parse_rule_only(self, request: TextCommandRequest) -> ParsedCommand:
        return self.rule_parser.parse(request)

    def parse(self, request: TextCommandRequest) -> ParsedCommand:
        parsed = self.rule_parser.parse(request)
        should_fallback = (
            self.fallback_parser is not None
            and (
                parsed.intent == "unknown"
                or (not parsed.missing_fields and parsed.confidence < 0.7)
            )
        )
        if not should_fallback:
            return parsed
        fallback = self.fallback_parser.parse(request)
        if fallback and fallback.intent != "unknown":
            return fallback
        return parsed
