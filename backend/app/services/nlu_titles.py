from __future__ import annotations

import re

from app.services.nlu_datetime import (
    CHINESE_TIME_RE,
    COLON_TIME_RE,
    EXPLICIT_DATE_RE,
    RELATIVE_REMINDER_RE,
    SLASH_DATE_RE,
    WEEKDAY_RE,
)


def _remove_time_and_date_tokens(text: str) -> str:
    cleaned = EXPLICIT_DATE_RE.sub("", text)
    cleaned = SLASH_DATE_RE.sub("", cleaned)
    cleaned = WEEKDAY_RE.sub("", cleaned)
    cleaned = re.sub(r"(今天|今日|明天|明日|后天|大后天|今早|明早|明晚|今晚|上午|下午|晚上|中午)", "", cleaned)
    cleaned = RELATIVE_REMINDER_RE.sub("", cleaned)
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
    marker = ""
    for candidate in ("提醒我", "提醒", "记一下", "帮我记下", "帮我记", "记个", "记得"):
        if candidate in text:
            marker = candidate
            break
    if marker:
        _, _, title = text.partition(marker)
    else:
        title = text
    title = _remove_time_and_date_tokens(title)
    title = re.sub(r"^(去|要去|需要去|记得去)", "", title)
    title = re.sub(r"^(一下|一下子)", "", title)
    if re.match(r"^给我[\u4e00-\u9fff]{1,6}", title):
        return title.strip("的了吧呀呢，。,. ")
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
