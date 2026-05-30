from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models import TextCommandRequest


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
RELATIVE_REMINDER_RE = re.compile(
    r"([零一二两三四五六七八九十百\d]+)\s*(秒钟|秒|分钟|分|小时|个小时|钟头|个钟头)\s*(后|之后)"
)
EXPLICIT_DATE_RE = re.compile(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})[日号]?")
CHINESE_EXPLICIT_DATE_RE = re.compile(
    r"(?:(\d{4})年)?([零一二两三四五六七八九十]{1,3})月([零一二两三四五六七八九十]{1,3})[日号]?"
)
SLASH_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})")
WEEKDAY_RE = re.compile(r"(下下周|下周|下个周|这周|本周|周|星期)([一二三四五六日天])")
UPDATE_ACTION_RE = re.compile(r"(改到|改成|改为|挪到|挪成|调整到|推迟到|提前到)")
TIME_CONNECTOR_RE = re.compile(r"(到|至|-|~|—)")


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


def _resolve_relative_reminder_datetime(text: str, base: datetime) -> datetime | None:
    match = RELATIVE_REMINDER_RE.search(text)
    if not match:
        return None
    amount = _parse_chinese_number(match.group(1))
    unit = match.group(2)
    if amount <= 0:
        return None
    if unit in {"秒钟", "秒"}:
        return base + timedelta(seconds=amount)
    if unit in {"分钟", "分"}:
        return base + timedelta(minutes=amount)
    if unit in {"小时", "个小时", "钟头", "个钟头"}:
        return base + timedelta(hours=amount)
    return None


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
    if value.second:
        return value.strftime("%H:%M:%S")
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
