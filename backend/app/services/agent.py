from __future__ import annotations

import json
import re

import httpx

from app.config import Settings
from app.models import ParsedCommand, TextCommandRequest
from app.services.nlu import normalize_text, request_now


SYSTEM_PROMPT = """你是中文日历语义解析器。你只做一件事：把用户指令解析成 JSON。

只允许以下 intent：
- create_event
- create_reminder
- update_event
- delete_event
- list_events
- get_today_news
- get_daily_briefing
- undo_last_operation
- unknown

返回格式必须是 JSON 对象，字段如下：
{
  "intent": "create_event",
  "slots": {},
  "missing_fields": [],
  "confidence": 0.0
}

要求：
- date 一律输出 ISO 日期，例如 2026-05-29
- time / start_time / end_time / new_start_time / new_end_time 一律输出 24 小时制 HH:MM
- 如果信息不足，不要猜，写入 missing_fields
- 如果无法判断，intent 必须是 unknown
- 不要输出 markdown，不要输出解释，只输出 JSON
"""


class ThirdPartyAgentParser:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def is_configured(self) -> bool:
        return bool(self.settings.agent_api_url and self.settings.agent_model)

    def parse(self, request: TextCommandRequest) -> ParsedCommand | None:
        if not self.is_configured():
            return None
        try:
            payload = self._create_completion(request)
            content = payload["choices"][0]["message"]["content"]
            parsed = self._parse_content(content)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
            return None

        return ParsedCommand(
            transcript=request.text,
            normalized_text=normalize_text(request.text),
            intent=str(parsed.get("intent") or "unknown"),
            slots=parsed.get("slots") or {},
            missing_fields=list(parsed.get("missing_fields") or []),
            parser=f"agent:{self.settings.agent_provider}",
            confidence=float(parsed.get("confidence") or 0.75),
        )

    def _create_completion(self, request: TextCommandRequest) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.settings.agent_api_key:
            headers["Authorization"] = f"Bearer {self.settings.agent_api_key}"

        now = request_now(request)
        body = {
            "model": self.settings.agent_model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "text": request.text,
                            "timezone": request.timezone,
                            "locale": request.locale,
                            "now": now.isoformat(),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        with httpx.Client(timeout=self.settings.agent_timeout_seconds) as client:
            response = client.post(self.settings.agent_api_url, headers=headers, json=body)
            response.raise_for_status()
        return response.json()

    @staticmethod
    def _parse_content(content: str) -> dict:
        cleaned = content.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.S)
        if fenced:
            cleaned = fenced.group(1)
        if not cleaned.startswith("{"):
            object_match = re.search(r"(\{.*\})", cleaned, re.S)
            if object_match:
                cleaned = object_match.group(1)
        return json.loads(cleaned)
