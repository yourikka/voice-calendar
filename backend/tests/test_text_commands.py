from fastapi.testclient import TestClient


def test_text_command_creates_reminder_and_lists_events(client: TestClient) -> None:
    create_response = client.post(
        "/api/text/commands",
        json={
            "text": "明早八点提醒我带身份证",
            "timezone": "Asia/Shanghai",
            "now": "2026-05-29T10:00:00+08:00",
        },
    )

    assert create_response.status_code == 200
    body = create_response.json()
    assert body["intent"] == "create_reminder"
    assert body["state"] == "completed"
    assert body["event"]["title"] == "带身份证"
    assert body["event"]["start_at"] == "2026-05-30T08:00:00+08:00"

    list_response = client.post(
        "/api/text/commands",
        json={
            "text": "明天有什么安排",
            "timezone": "Asia/Shanghai",
            "now": "2026-05-29T10:00:00+08:00",
        },
    )

    assert list_response.status_code == 200
    assert "带身份证" in list_response.json()["reply_text"]


def test_text_delete_requires_confirmation(client: TestClient) -> None:
    client.post(
        "/api/events",
        json={
            "title": "健身",
            "start_at": "2026-05-30T18:00:00+08:00",
            "end_at": "2026-05-30T19:00:00+08:00",
        },
    )

    delete_draft = client.post(
        "/api/text/commands",
        json={
            "text": "取消明天的健身",
            "timezone": "Asia/Shanghai",
            "now": "2026-05-29T10:00:00+08:00",
        },
    )

    assert delete_draft.status_code == 200
    body = delete_draft.json()
    assert body["state"] == "awaiting_confirmation"
    assert body["operation_id"]

    confirm = client.post(
        "/api/operations/confirm",
        json={"operation_id": body["operation_id"], "confirmed": True},
    )

    assert confirm.status_code == 200
    assert confirm.json()["state"] == "completed"

    list_response = client.get(
        "/api/events",
        params={
            "start": "2026-05-30T00:00:00+08:00",
            "end": "2026-05-31T00:00:00+08:00",
        },
    )
    assert list_response.json()["items"] == []

