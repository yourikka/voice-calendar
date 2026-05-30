from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models import ParsedCommand, TextCommandRequest


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
    "二十一": 21,
    "二十二": 22,
    "二十三": 23,
    "二十四": 24,
    "二十五": 25,
    "二十六": 26,
    "二十七": 27,
    "二十八": 28,
    "二十九": 29,
    "三十": 30,
    "三十一": 31,
}

PERIOD_DEFAULT_HOUR = {
    "明早": 8,
    "明晚": 20,
    "今早": 8,
    "早上": 8,
    "上午": 10,
    "中午": 12,
    "下午": 15,
    "晚上": 20,
    "今晚": 20,
}

TIME_PREFIX_RE = r"(?:凌晨|早上|今早|明早|明晚|上午|中午|下午|晚上|今晚)?"
COLON_TIME_RE = re.compile(rf"({TIME_PREFIX_RE})(\d{{1,2}})[:：](\d{{1,2}})")
CHINESE_TIME_RE = re.compile(
    rf"({TIME_PREFIX_RE})([零一二两三四五六七八九十\d]{{1,3}})点(半|[零一二三四五六七八九十\d]{{1,3}}分?)?"
)
EXPLICIT_DATE_RE = re.compile(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})[日号]?")
CHINESE_EXPLICIT_DATE_RE = re.compile(
    r"(?:(\d{4})年)?([零一二两三四五六七八九十]{1,3})月([零一二两三四五六七八九十]{1,3})[日号]?"
)
SLASH_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})")
WEEKDAY_RE = re.compile(r"(下下周|下周|下个周|这周|本周|周|星期)([一二三四五六日天])")
UPDATE_ACTION_RE = re.compile(r"(改到|改成|改为|挪到|挪成|调整到|推迟到|提前到)")
TIME_CONNECTOR_RE = re.compile(r"(到|至|-|~|—)")
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


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text.strip())


def request_now(request: TextCommandRequest) -> datetime:
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


def _apply_period(hour: int, prefix: str) -> int:
    if prefix in {"下午", "晚上", "今晚", "明晚"} and 0 < hour < 12:
        return hour + 12
    if prefix == "中午" and 0 < hour < 11:
        return hour + 12
    if prefix == "凌晨" and hour == 12:
        return 0
    return hour


def _time_from_match(prefix: str, hour_raw: str, minute_raw: str | None) -> time:
    hour = _parse_chinese_number(hour_raw)
    minute = 0
    if minute_raw == "半":
        minute = 30
    elif minute_raw:
        minute = _parse_chinese_number(minute_raw.removesuffix("分"))
    return time(hour=_apply_period(hour, prefix), minute=minute)


def _extract_time_candidates(text: str) -> list[tuple[int, int, time]]:
    candidates: list[tuple[int, int, time]] = []
    for match in COLON_TIME_RE.finditer(text):
        prefix = match.group(1) or ""
        hour = _apply_period(int(match.group(2)), prefix)
        minute = int(match.group(3))
        candidates.append((match.start(), match.end(), time(hour=hour, minute=minute)))
    for match in CHINESE_TIME_RE.finditer(text):
        candidates.append(
            (
                match.start(),
                match.end(),
                _time_from_match(match.group(1) or "", match.group(2), match.group(3)),
            )
        )
    candidates.sort(key=lambda item: item[0])
    return candidates


def _parse_time_range(text: str) -> tuple[time | None, time | None]:
    candidates = _extract_time_candidates(text)
    if len(candidates) >= 2:
        for index in range(len(candidates) - 1):
            left = candidates[index]
            right = candidates[index + 1]
            if TIME_CONNECTOR_RE.search(text[left[1] : right[0]]):
                right_time = right[2]
                context_text = text[: right[1]]
                if right_time.hour < 12 and left[2].hour >= 12:
                    if any(token in context_text for token in ("下午", "晚上", "今晚", "明晚")):
                        right_time = time(hour=right_time.hour + 12, minute=right_time.minute)
                    elif "中午" in context_text and right_time.hour < 11:
                        right_time = time(hour=right_time.hour + 12, minute=right_time.minute)
                return left[2], right_time
    if candidates:
        return candidates[0][2], None
    for label, hour in PERIOD_DEFAULT_HOUR.items():
        if label in text:
            return time(hour=hour, minute=0), None
    return None, None


def _resolve_date(text: str, base: datetime) -> date | None:
    explicit = EXPLICIT_DATE_RE.search(text)
    if explicit:
        year = int(explicit.group(1)) if explicit.group(1) else base.year
        return date(year, int(explicit.group(2)), int(explicit.group(3)))

    chinese_explicit = CHINESE_EXPLICIT_DATE_RE.search(text)
    if chinese_explicit:
        year = int(chinese_explicit.group(1)) if chinese_explicit.group(1) else base.year
        month = _parse_chinese_number(chinese_explicit.group(2))
        day = _parse_chinese_number(chinese_explicit.group(3))
        return date(year, month, day)

    slash = SLASH_DATE_RE.search(text)
    if slash:
        return date(base.year, int(slash.group(1)), int(slash.group(2)))

    local_date = base.date()
    if "大后天" in text:
        return local_date + timedelta(days=3)
    if "后天" in text:
        return local_date + timedelta(days=2)
    if "明天" in text or "明日" in text or "明早" in text or "明晚" in text:
        return local_date + timedelta(days=1)
    if "今天" in text or "今日" in text or "今早" in text or "今晚" in text:
        return local_date

    weekday_match = WEEKDAY_RE.search(text)
    if weekday_match:
        target = WEEKDAY_MAP[weekday_match.group(2)]
        delta = target - local_date.weekday()
        prefix = weekday_match.group(1)
        if prefix in {"下周", "下个周"}:
            delta += 7
        elif prefix == "下下周":
            delta += 14
        elif prefix in {"周", "星期"}:
            if delta < 0:
                delta += 7
        elif delta < 0:
            delta += 7
        return local_date + timedelta(days=delta)
    return None


def _resolve_window(text: str, base: datetime) -> tuple[datetime, datetime]:
    zone = base.tzinfo
    local_date = base.date()
    if "下周" in text:
        monday = local_date - timedelta(days=local_date.weekday()) + timedelta(days=7)
        return datetime.combine(monday, time.min, tzinfo=zone), datetime.combine(
            monday + timedelta(days=7), time.min, tzinfo=zone
        )
    if "本周" in text or "这周" in text:
        monday = local_date - timedelta(days=local_date.weekday())
        return datetime.combine(monday, time.min, tzinfo=zone), datetime.combine(
            monday + timedelta(days=7), time.min, tzinfo=zone
        )

    day = _resolve_date(text, base) or local_date
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = start + timedelta(days=1)
    if "上午" in text or "今早" in text or "明早" in text or "早上" in text:
        return start.replace(hour=6), start.replace(hour=12)
    if "下午" in text:
        return start.replace(hour=12), start.replace(hour=18)
    if "晚上" in text or "今晚" in text or "明晚" in text:
        return start.replace(hour=18), end
    return start, end


def _format_time_value(value: time | None) -> str | None:
    if value is None:
        return None
    return value.strftime("%H:%M")


def _parse_reminder_offset(text: str) -> int | None:
    minute_match = re.search(r"提前([零一二两三四五六七八九十\d]+)分钟", text)
    if minute_match:
        return -_parse_chinese_number(minute_match.group(1))
    hour_match = re.search(r"提前([零一二两三四五六七八九十\d]+)小时", text)
    if hour_match:
        return -_parse_chinese_number(hour_match.group(1)) * 60
    if "提前半小时" in text:
        return -30
    return None


def _remove_time_and_date_tokens(text: str) -> str:
    cleaned = EXPLICIT_DATE_RE.sub("", text)
    cleaned = SLASH_DATE_RE.sub("", cleaned)
    cleaned = WEEKDAY_RE.sub("", cleaned)
    cleaned = re.sub(r"(今天|今日|明天|明日|后天|大后天|今早|明早|明晚|今晚|上午|下午|晚上|中午)", "", cleaned)
    cleaned = COLON_TIME_RE.sub("", cleaned)
    cleaned = CHINESE_TIME_RE.sub("", cleaned)
    cleaned = re.sub(r"提前[零一二两三四五六七八九十\d]+分钟提醒我", "", cleaned)
    cleaned = re.sub(r"提前[零一二两三四五六七八九十\d]+小时提醒我", "", cleaned)
    cleaned = cleaned.replace("提前半小时提醒我", "")
    cleaned = re.sub(r"[，。,.！!？?]", "", cleaned)
    return cleaned


def _cleanup_title(value: str) -> str:
    cleaned = value
    cleaned = re.sub(r"^(帮我|给我|请|安排|新增|添加|创建|设置|取消|删除|把|将)", "", cleaned)
    cleaned = re.sub(r"(一下|吧)$", "", cleaned)
    return cleaned.strip("的了吧呀呢，。,. ")


def _extract_reminder_title(text: str) -> str:
    marker = "提醒我" if "提醒我" in text else "提醒"
    _, _, title = text.partition(marker)
    title = _remove_time_and_date_tokens(title)
    title = re.sub(r"^(去|要去|需要去|记得去)", "", title)
    title = re.sub(r"^(一下|一下子)", "", title)
    title = _cleanup_title(title)
    return title or "未命名提醒"


def _extract_event_title(text: str) -> str:
    if "会议" in text or "開會" in text or "开会" in text or "有会" in text:
        return "会议"
    meeting_match = re.search(r"开(.+?会)", text)
    if meeting_match:
        title = _cleanup_title(meeting_match.group(1))
        return "会议" if title in {"", "会"} else title
    if "面试" in text:
        return "面试"
    if "健身" in text:
        return "健身"
    cleaned = _remove_time_and_date_tokens(text)
    cleaned = re.sub(r"(提醒我|通知我)", "", cleaned)
    cleaned = re.sub(r"^(有个|有场|有次|有一场|有一个|有|要开个|要开场|要开次)", "", cleaned)
    cleaned = re.sub(r"^(和|跟|与)[^，,。]+?(开|见|聊|讨论|沟通)", "", cleaned)
    cleaned = re.sub(r"^(早上|上午|中午|下午|晚上|今晚|今早|明早|明晚)", "", cleaned)
    cleaned = _cleanup_title(cleaned)
    if cleaned.startswith("开") and len(cleaned) > 1:
        cleaned = cleaned[1:]
    if cleaned in {"有会", "有会议", "有个会", "有个会议", "开会", "会议安排"}:
        return "会议"
    return cleaned or "未命名日程"


def _extract_participants(text: str) -> list[str]:
    match = re.search(r"(?:和|跟|与)([^，,。]+?)(?:开|见|聊|讨论|沟通|面试)", text)
    if not match:
        return []
    name = _cleanup_title(match.group(1))
    return [name] if name else []


def _extract_delete_title(text: str) -> str:
    keyword = re.sub(r"^(取消|删除|去掉)", "", text)
    keyword = _remove_time_and_date_tokens(keyword)
    keyword = re.sub(r"(所有|全部)", "", keyword)
    keyword = re.sub(r"(安排|日程|提醒|事件)", "", keyword)
    return _cleanup_title(keyword)


def _extract_update_title(before_text: str) -> str:
    cleaned = re.sub(r"^(把|将)", "", before_text)
    cleaned = _remove_time_and_date_tokens(cleaned)
    cleaned = re.sub(r"(安排|日程|提醒|事件)", "", cleaned)
    return _cleanup_title(cleaned)


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

        if "提醒我" in text or text.startswith("提醒"):
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
        day = _resolve_date(text, base) or base.date()
        start_time, _ = _parse_time_range(text)
        missing_fields: list[str] = []
        if start_time is None:
            missing_fields.append("time")
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
            confidence=0.92 if not missing_fields else 0.55,
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

    def parse(self, request: TextCommandRequest) -> ParsedCommand:
        parsed = self.rule_parser.parse(request)
        should_fallback = (
            self.fallback_parser is not None
            and (
                parsed.intent == "unknown"
                or parsed.confidence < 0.7
                or (parsed.missing_fields and parsed.intent in {"create_event", "create_reminder", "update_event"})
            )
        )
        if not should_fallback:
            return parsed
        fallback = self.fallback_parser.parse(request)
        if fallback and fallback.intent != "unknown":
            return fallback
        return parsed
