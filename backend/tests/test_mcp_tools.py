from fastapi.testclient import TestClient


def test_mcp_calendar_tools_reuse_calendar_service(client: TestClient) -> None:
    create = client.post(
        "/api/mcp/tools/calendar.create_event_draft",
        json={
            "arguments": {
                "title": "项目复盘会",
                "start_at": "2026-05-30T15:00:00+08:00",
                "end_at": "2026-05-30T16:00:00+08:00",
                "timezone": "Asia/Shanghai",
            }
        },
    )

    assert create.status_code == 200
    event_id = create.json()["result"]["event"]["id"]

    availability = client.post(
        "/api/mcp/tools/calendar.check_availability",
        json={
            "arguments": {
                "start_at": "2026-05-30T15:30:00+08:00",
                "end_at": "2026-05-30T16:30:00+08:00",
            }
        },
    )
    assert availability.json()["result"]["available"] is False

    delete_draft = client.post(
        "/api/mcp/tools/calendar.delete_event_draft",
        json={"arguments": {"event_id": event_id}},
    )
    operation_id = delete_draft.json()["result"]["operation_id"]
    assert delete_draft.json()["result"]["requires_confirmation"] is True

    confirm = client.post(
        "/api/mcp/tools/calendar.confirm_operation",
        json={"arguments": {"operation_id": operation_id, "confirmed": True}},
    )
    assert confirm.status_code == 200
    assert confirm.json()["result"]["state"] == "completed"


def test_mcp_news_and_briefing_tools(client: TestClient) -> None:
    news = client.post(
        "/api/mcp/tools/news.get_today_hot_topics",
        json={"arguments": {"timezone": "Asia/Shanghai", "limit": 2, "fresh": True}},
    )

    assert news.status_code == 200
    assert len(news.json()["result"]["items"]) == 2

    briefing = client.post(
        "/api/mcp/tools/briefing.get_daily_briefing",
        json={"arguments": {"date": "2026-05-29", "timezone": "Asia/Shanghai"}},
    )

    assert briefing.status_code == 200
    assert "sections" in briefing.json()["result"]


def test_mcp_handle_command_executes_calendar_action(client: TestClient) -> None:
    response = client.post(
        "/api/mcp/tools/calendar.handle_command",
        json={
            "arguments": {
                "text": "明早八点提醒我带身份证",
                "timezone": "Asia/Shanghai",
                "locale": "zh-CN",
                "now": "2026-05-29T10:00:00+08:00",
            }
        },
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["intent"] == "create_reminder"
    assert result["event"]["title"] == "带身份证"
