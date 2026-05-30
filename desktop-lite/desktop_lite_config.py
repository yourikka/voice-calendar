from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OVERLAY_HTML = PROJECT_ROOT / "desktop-overlay" / "src" / "index.html"
STATE_FILE = PROJECT_ROOT / ".desktop-lite-state.json"
NOTIFY_LOG_FILE = PROJECT_ROOT / ".desktop-lite-notify.log"
BACKEND_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_BROWSER_CMD = os.getenv("VOICE_CALENDAR_BROWSER_CMD", "").strip()

COMPACT_SIZE = {"width": 126, "height": 64}
COMPACT_MIN_WIDTH = 108
COMPACT_MIN_HEIGHT = 52
EXPANDED_SIZE = {"width": 456, "height": 468}
EXPANDED_MIN_HEIGHT = 168
SNAP_MARGIN = 16

TOOL_OPTIONS = [
    {
        "value": "voice.handle_command",
        "label": "语音日历",
        "description": "录音后直接识别并执行日历命令，适合多轮语音补全。",
    },
    {
        "value": "calendar.handle_command",
        "label": "文本日历命令",
        "description": "文本和转写结果都直接进入日历命令解析。",
    },
    {
        "value": "news.get_today_hot_topics",
        "label": "今日热点",
        "description": "获取当天热点资讯，语音输入会先转写再触发热点工具。",
    },
]

WSL_EDGE_CANDIDATES = (
    "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe",
)
