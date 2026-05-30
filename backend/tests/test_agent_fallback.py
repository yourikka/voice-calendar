from app.api import get_command_parser
from app.config import Settings
from app.main import app
from app.models import ParsedCommand, TextCommandRequest
from app.services.agent import ThirdPartyAgentParser
from app.services.nlu import HybridCommandParser


class FakeAgentFallback:
    def parse(self, request: TextCommandRequest) -> ParsedCommand:
        return ParsedCommand(
            transcript=request.text,
            normalized_text=request.text,
            intent="create_reminder",
            slots={
                "title": "给我妈打电话",
                "date": "2026-05-31",
                "time": "20:00",
            },
            parser="agent:fake",
            confidence=0.88,
        )


def test_text_command_uses_agent_fallback_for_unknown_input(client) -> None:
    app.dependency_overrides[get_command_parser] = lambda: HybridCommandParser(fallback_parser=FakeAgentFallback())
    try:
        response = client.post(
            "/api/text/commands",
            json={
                "text": "记一下后天晚上给我妈打电话",
                "timezone": "Asia/Shanghai",
                "now": "2026-05-29T10:00:00+08:00",
            },
        )
    finally:
        app.dependency_overrides.pop(get_command_parser, None)

    assert response.status_code == 200
    body = response.json()
    assert body["parser"] == "agent:fake"
    assert body["intent"] == "create_reminder"
    assert body["event"]["start_at"] == "2026-05-31T20:00:00+08:00"


def test_mcp_parse_command_uses_agent_fallback(client) -> None:
    app.dependency_overrides[get_command_parser] = lambda: HybridCommandParser(fallback_parser=FakeAgentFallback())
    try:
        response = client.post(
            "/api/mcp/tools/calendar.parse_command",
            json={
                "arguments": {
                    "text": "记一下后天晚上给我妈打电话",
                    "timezone": "Asia/Shanghai",
                    "now": "2026-05-29T10:00:00+08:00",
                }
            },
        )
    finally:
        app.dependency_overrides.pop(get_command_parser, None)

    assert response.status_code == 200
    body = response.json()["result"]
    assert body["parser"] == "agent:fake"
    assert body["intent"] == "create_reminder"


def test_third_party_agent_parser_reads_json_payload() -> None:
    parser = ThirdPartyAgentParser(
        Settings(
            agent_api_url="https://example.com/v1/chat/completions",
            agent_model="calendar-agent",
        )
    )
    parser._create_completion = lambda request: {  # type: ignore[method-assign]
        "choices": [
            {
                "message": {
                    "content": """```json
{"intent":"get_today_news","slots":{"date":"2026-05-29","news_category":"technology"},"missing_fields":[],"confidence":0.83}
```"""
                }
            }
        ]
    }

    result = parser.parse(TextCommandRequest(text="今天科技圈有什么新闻"))

    assert result is not None
    assert result.intent == "get_today_news"
    assert result.slots["news_category"] == "technology"
    assert result.parser == "agent:openai-compatible"
