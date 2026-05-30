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
    assert body["slots"]["date"] == "2026-05-30"
    assert body["slots"]["time"] == "08:00"

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


def test_text_command_parses_tomorrow_evening_reminder(client: TestClient) -> None:
    response = client.post(
        "/api/text/commands",
        json={
            "text": "明晚十点提醒我吃饭",
            "timezone": "Asia/Shanghai",
            "now": "2026-05-29T10:00:00+08:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "create_reminder"
    assert body["state"] == "completed"
    assert body["event"]["title"] == "吃饭"
    assert body["event"]["start_at"] == "2026-05-30T22:00:00+08:00"


def test_text_command_creates_event_with_time_range_and_reminder(client: TestClient) -> None:
    response = client.post(
        "/api/text/commands",
        json={
            "text": "下周三下午两点到三点和李雷开项目评审会，提前十分钟提醒我",
            "timezone": "Asia/Shanghai",
            "now": "2026-05-29T10:00:00+08:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "create_event"
    assert body["state"] == "completed"
    assert body["event"]["title"] == "项目评审会"
    assert body["event"]["start_at"] == "2026-06-03T14:00:00+08:00"
    assert body["event"]["end_at"] == "2026-06-03T15:00:00+08:00"
    assert body["slots"]["reminder_offset_minutes"] == -10


def test_text_command_creates_meeting_event_from_natural_phrase(client: TestClient) -> None:
    response = client.post(
        "/api/text/commands",
        json={
            "text": "今晚八点有个会议",
            "timezone": "Asia/Shanghai",
            "now": "2026-05-29T10:00:00+08:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "create_event"
    assert body["state"] == "completed"
    assert body["event"]["title"] == "会议"
    assert body["event"]["start_at"] == "2026-05-29T20:00:00+08:00"


def test_text_command_supports_abstract_list_query(client: TestClient) -> None:
    client.post(
        "/api/events",
        json={
            "title": "项目会议",
            "start_at": "2026-05-30T20:00:00+08:00",
            "end_at": "2026-05-30T21:00:00+08:00",
        },
    )

    response = client.post(
        "/api/text/commands",
        json={
            "text": "明天有什么事",
            "timezone": "Asia/Shanghai",
            "now": "2026-05-29T10:00:00+08:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "list_events"
    assert "项目会议" in body["reply_text"]


def test_text_command_completes_pending_event_after_follow_up_time(client: TestClient) -> None:
    first = client.post(
        "/api/text/commands",
        json={
            "text": "有会议",
            "timezone": "Asia/Shanghai",
            "now": "2026-05-29T10:00:00+08:00",
        },
    )

    assert first.status_code == 200
    first_body = first.json()
    assert first_body["state"] == "collecting_slots"
    assert first_body["intent"] == "create_event"
    assert first_body["missing_fields"] == ["start_time"]

    second = client.post(
        "/api/text/commands",
        json={
            "text": "明天晚上八点",
            "timezone": "Asia/Shanghai",
            "session_id": first_body["session_id"],
            "now": "2026-05-29T10:00:00+08:00",
        },
    )

    assert second.status_code == 200
    body = second.json()
    assert body["state"] == "completed"
    assert body["intent"] == "create_event"
    assert body["event"]["title"] == "会议"
    assert body["event"]["start_at"] == "2026-05-30T20:00:00+08:00"


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


def test_text_command_updates_existing_event(client: TestClient) -> None:
    create = client.post(
        "/api/events",
        json={
            "title": "面试",
            "start_at": "2026-05-30T10:00:00+08:00",
            "end_at": "2026-05-30T11:00:00+08:00",
        },
    )
    assert create.status_code == 201

    update = client.post(
        "/api/text/commands",
        json={
            "text": "把明天的面试改到下午三点",
            "timezone": "Asia/Shanghai",
            "now": "2026-05-29T10:00:00+08:00",
        },
    )

    assert update.status_code == 200
    body = update.json()
    assert body["intent"] == "update_event"
    assert body["state"] == "completed"
    assert body["event"]["start_at"] == "2026-05-30T15:00:00+08:00"


def test_text_command_collects_missing_time(client: TestClient) -> None:
    response = client.post(
        "/api/text/commands",
        json={
            "text": "提醒我带身份证",
            "timezone": "Asia/Shanghai",
            "now": "2026-05-29T10:00:00+08:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "collecting_slots"
    assert body["missing_fields"] == ["time"]
    assert body["requires_user_input"] is True


def test_pending_text_command_survives_new_request_connection(client: TestClient) -> None:
    first = client.post(
        "/api/text/commands",
        json={
            "text": "提醒我带身份证",
            "timezone": "Asia/Shanghai",
            "now": "2026-05-29T10:00:00+08:00",
        },
    )
    assert first.status_code == 200
    session_id = first.json()["session_id"]

    second = client.post(
        "/api/text/commands",
        json={
            "text": "明早八点",
            "timezone": "Asia/Shanghai",
            "session_id": session_id,
            "now": "2026-05-29T10:00:00+08:00",
        },
    )

    assert second.status_code == 200
    body = second.json()
    assert body["state"] == "completed"
    assert body["event"]["title"] == "带身份证"
    assert body["event"]["start_at"] == "2026-05-30T08:00:00+08:00"
