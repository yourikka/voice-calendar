from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import chinese_calendar as chinese_calendar_lib


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
        return CalendarMetaDay(
            date=day.isoformat(),
            is_holiday=is_holiday,
            is_adjusted_workday=is_adjusted_workday,
            holiday_name=HOLIDAY_NAME_MAP.get(holiday_key, holiday_key),
            solar_term=solar_term,
        )
