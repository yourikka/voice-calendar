from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = "Voice Calendar"
    database_path: Path = Path("backend/data/voice_calendar.db")
    default_timezone: str = "Asia/Shanghai"
    asr_api_url: str | None = None
    asr_api_key: str | None = None
    asr_model: str | None = "base"
    asr_provider: str = "faster-whisper"
    asr_timeout_seconds: float = 20.0
    asr_device: str = "cpu"
    asr_compute_type: str = "int8"
    asr_preload_on_startup: bool = False
    agent_api_url: str | None = None
    agent_api_key: str | None = None
    agent_model: str | None = None
    agent_provider: str = "openai-compatible"
    agent_timeout_seconds: float = 20.0


def get_settings() -> Settings:
    database_path = Path(os.getenv("VOICE_CALENDAR_DB", "backend/data/voice_calendar.db"))
    return Settings(
        database_path=database_path,
        asr_api_url=os.getenv("VOICE_ASR_API_URL"),
        asr_api_key=os.getenv("VOICE_ASR_API_KEY"),
        asr_model=os.getenv("VOICE_ASR_MODEL", "base"),
        asr_provider=os.getenv("VOICE_ASR_PROVIDER", "faster-whisper"),
        asr_timeout_seconds=float(os.getenv("VOICE_ASR_TIMEOUT_SECONDS", "20")),
        asr_device=os.getenv("VOICE_ASR_DEVICE", "cpu"),
        asr_compute_type=os.getenv("VOICE_ASR_COMPUTE_TYPE", "int8"),
        asr_preload_on_startup=_env_bool("VOICE_ASR_PRELOAD_ON_STARTUP", "false"),
        agent_api_url=os.getenv("VOICE_AGENT_API_URL"),
        agent_api_key=os.getenv("VOICE_AGENT_API_KEY"),
        agent_model=os.getenv("VOICE_AGENT_MODEL"),
        agent_provider=os.getenv("VOICE_AGENT_PROVIDER", "openai-compatible"),
        agent_timeout_seconds=float(os.getenv("VOICE_AGENT_TIMEOUT_SECONDS", "20")),
    )
