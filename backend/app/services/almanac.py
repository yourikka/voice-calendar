from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import chinese_calendar as chinese_calendar_lib
from lunardate import LunarDate


HOLIDAY_NAME_MAP = {
    "New Year's Day": "元旦",
    "Spring Festival": "春节",
    "Tomb-sweeping Day": "清明节",
    "Labour Day": "劳动节",
    "Dragon Boat Festival": "端午节",
    "National Day": "国庆节",
    "Mid-autumn Festival": "中秋节",
}


@dataclass
class CalendarMetaDay:
    date: str
    is_holiday: bool
    is_adjusted_workday: bool
    holiday_name: str | None
    solar_term: str | None


class AlmanacService:
    def list_day_meta(self, start: date, end: date) -> list[CalendarMetaDay]:
        items: list[CalendarMetaDay] = []
        cursor = start
        while cursor < end:
            items.append(self._build_day(cursor))
            cursor += timedelta(days=1)
        return items

    def _build_day(self, day: date) -> CalendarMetaDay:
        is_holiday, holiday_key = chinese_calendar_lib.get_holiday_detail(day)
        solar_terms = chinese_calendar_lib.get_solar_terms(day, day)
        solar_term = solar_terms[0][1] if solar_terms else None
        is_adjusted_workday = chinese_calendar_lib.is_workday(day) and day.weekday() >= 5
        is_statutory_holiday = is_holiday and holiday_key is not None
        return CalendarMetaDay(
            date=day.isoformat(),
            is_holiday=is_statutory_holiday,
            is_adjusted_workday=is_adjusted_workday,
            holiday_name=self._holiday_name_for_day(day, holiday_key, solar_term),
            solar_term=solar_term,
        )

    def _holiday_name_for_day(self, day: date, holiday_key: str | None, solar_term: str | None) -> str | None:
        if holiday_key is None or not self._is_primary_holiday_day(day, holiday_key, solar_term):
            return None
        return HOLIDAY_NAME_MAP.get(holiday_key, holiday_key)

    def _is_primary_holiday_day(self, day: date, holiday_key: str, solar_term: str | None) -> bool:
        if holiday_key == "New Year's Day":
            return day.month == 1 and day.day == 1
        if holiday_key == "Labour Day":
            return day.month == 5 and day.day == 1
        if holiday_key == "National Day":
            return day.month == 10 and day.day == 1
        if holiday_key == "Tomb-sweeping Day":
            return solar_term == "清明"

        lunar_day = LunarDate.fromSolarDate(day.year, day.month, day.day)
        if holiday_key == "Spring Festival":
            return lunar_day.month == 1 and lunar_day.day == 1
        if holiday_key == "Dragon Boat Festival":
            return lunar_day.month == 5 and lunar_day.day == 5
        if holiday_key == "Mid-autumn Festival":
            return lunar_day.month == 8 and lunar_day.day == 15
        return False
