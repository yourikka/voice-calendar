from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str = "Voice Calendar"
    database_path: Path = Path("backend/data/voice_calendar.db")
    default_timezone: str = "Asia/Shanghai"


def get_settings() -> Settings:
    database_path = Path(os.getenv("VOICE_CALENDAR_DB", "backend/data/voice_calendar.db"))
    return Settings(database_path=database_path)

