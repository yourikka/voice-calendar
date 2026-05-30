import base64

from app.api import get_asr_service
from app.main import app
from app.services.asr import ASRHealth, ASRTranscript
from fastapi.testclient import TestClient


class FakeASRService:
    def health(self) -> ASRHealth:
        return ASRHealth(
            available=True,
            provider="fake-asr",
            model="fake-model",
            ready=True,
            warming=False,
            detail="语音模型已就绪。",
        )

    def transcribe(self, **_: object) -> ASRTranscript:
        return ASRTranscript(text="明早八点提醒我带身份证", provider="fake-asr")


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


def test_mcp_exposes_web_calendar_helpers(client: TestClient) -> None:
    event = client.post(
        "/api/events",
        json={
            "title": "项目会议",
            "start_at": "2026-05-30T20:00:00+08:00",
            "end_at": "2026-05-30T21:00:00+08:00",
        },
    ).json()["event"]

    get_event = client.post(
        "/api/mcp/tools/calendar.get_event",
        json={"arguments": {"event_id": event["id"]}},
    )
    assert get_event.status_code == 200
    assert get_event.json()["result"]["title"] == "项目会议"

    meta = client.post(
        "/api/mcp/tools/calendar.get_meta",
        json={"arguments": {"start": "2026-05-01", "end": "2026-05-31"}},
    )
    assert meta.status_code == 200
    assert meta.json()["result"]["start"] == "2026-05-01"
    assert isinstance(meta.json()["result"]["items"], list)

    refresh = client.post(
        "/api/mcp/tools/news.refresh_hot_topics",
        json={"arguments": {"timezone": "Asia/Shanghai", "region": "CN"}},
    )
    assert refresh.status_code == 200
    assert refresh.json()["result"]["status"] == "completed"

    panel = client.post(
        "/api/mcp/tools/calendar.get_hot_topic_panel",
        json={"arguments": {"date": "2026-05-29", "timezone": "Asia/Shanghai", "limit": 3}},
    )
    assert panel.status_code == 200
    assert len(panel.json()["result"]["items"]) == 3


def test_mcp_voice_tools_reuse_asr_and_command_pipeline(client: TestClient) -> None:
    app.dependency_overrides[get_asr_service] = lambda: FakeASRService()
    try:
        audio_base64 = base64.b64encode(b"fake-audio").decode("ascii")

        capabilities = client.post("/api/mcp/tools/voice.get_capabilities", json={"arguments": {}})
        assert capabilities.status_code == 200
        assert capabilities.json()["result"]["available"] is True

        transcript = client.post(
            "/api/mcp/tools/voice.transcribe_audio",
            json={
                "arguments": {
                    "audio_base64": audio_base64,
                    "filename": "voice.webm",
                    "content_type": "audio/webm",
                    "locale": "zh-CN",
                }
            },
        )
        assert transcript.status_code == 200
        assert transcript.json()["result"]["transcript"] == "明早八点提醒我带身份证"

        command = client.post(
            "/api/mcp/tools/voice.handle_command",
            json={
                "arguments": {
                    "audio_base64": audio_base64,
                    "filename": "voice.webm",
                    "content_type": "audio/webm",
                    "timezone": "Asia/Shanghai",
                    "locale": "zh-CN",
                    "now": "2026-05-29T10:00:00+08:00",
                }
            },
        )
        assert command.status_code == 200
        result = command.json()["result"]
        assert result["asr_provider"] == "fake-asr"
        assert result["intent"] == "create_reminder"
        assert result["event"]["title"] == "带身份证"
    finally:
        app.dependency_overrides.pop(get_asr_service, None)


def test_mcp_resolve_candidate_supports_delete_confirmation_flow(client: TestClient) -> None:
    first = client.post(
        "/api/events",
        json={
            "title": "周会A",
            "start_at": "2026-05-30T10:00:00+08:00",
            "end_at": "2026-05-30T11:00:00+08:00",
        },
    ).json()["event"]
    second = client.post(
        "/api/events",
        json={
            "title": "周会B",
            "start_at": "2026-05-30T15:00:00+08:00",
            "end_at": "2026-05-30T16:00:00+08:00",
        },
    ).json()["event"]

    command = client.post(
        "/api/mcp/tools/calendar.handle_command",
        json={
            "arguments": {
                "text": "取消明天的周会",
                "timezone": "Asia/Shanghai",
                "now": "2026-05-29T10:00:00+08:00",
            }
        },
    )
    assert command.status_code == 200
    body = command.json()["result"]
    assert body["state"] == "selecting_candidate"
    assert len(body["candidates"]) == 2

    resolved = client.post(
        "/api/mcp/tools/calendar.resolve_candidate",
        json={
            "arguments": {
                "intent": "delete_event",
                "candidate_id": first["id"],
                "timezone": "Asia/Shanghai",
                "session_id": body["session_id"],
                "slots": body["slots"],
            }
        },
    )
    assert resolved.status_code == 200
    result = resolved.json()["result"]
    assert result["state"] == "awaiting_confirmation"
    assert result["operation_id"]
    assert result["reply_text"].startswith("找到周会A")

    confirm = client.post(
        "/api/mcp/tools/calendar.confirm_operation",
        json={"arguments": {"operation_id": result["operation_id"], "confirmed": True}},
    )
    assert confirm.status_code == 200
    assert confirm.json()["result"]["state"] == "completed"

    remaining = client.get(
        "/api/events",
        params={
            "start": "2026-05-30T00:00:00+08:00",
            "end": "2026-05-31T00:00:00+08:00",
        },
    ).json()["items"]
    assert [item["id"] for item in remaining] == [second["id"]]
