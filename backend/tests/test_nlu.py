def test_mcp_parse_command_returns_structured_slots(client) -> None:
    response = client.post(
        "/api/mcp/tools/calendar.parse_command",
        json={
            "arguments": {
                "text": "今天科技圈有什么新闻",
                "timezone": "Asia/Shanghai",
                "now": "2026-05-29T10:00:00+08:00",
            }
        },
    )

    assert response.status_code == 200
    body = response.json()["result"]
    assert body["intent"] == "get_today_news"
    assert body["slots"]["news_category"] == "technology"
    assert body["slots"]["date"] == "2026-05-29"
