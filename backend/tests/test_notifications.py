from fastapi.testclient import TestClient


def test_due_reminder_can_be_polled_and_acknowledged(client: TestClient) -> None:
    create = client.post(
        "/api/events",
        json={
            "title": "喝水",
            "type": "reminder",
            "start_at": "2026-06-03T14:00:30+08:00",
            "end_at": None,
            "timezone": "Asia/Shanghai",
            "reminders": [{"method": "notification", "offset_minutes": 0}],
        },
    )
    assert create.status_code == 201

    due = client.get(
        "/api/notifications/due",
        params={
            "channel": "desktop-lite",
            "lookback_seconds": 600,
            "limit": 10,
            "now": "2026-06-03T14:00:31+08:00",
        },
    )
    assert due.status_code == 200
    items = due.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "喝水"
    delivery_id = items[0]["delivery_id"]

    duplicate = client.get(
        "/api/notifications/due",
        params={
            "channel": "desktop-lite",
            "lookback_seconds": 600,
            "limit": 10,
            "now": "2026-06-03T14:00:31+08:00",
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["items"] == []

    ack = client.post(
        "/api/notifications/ack",
        json={"delivery_id": delivery_id, "channel": "desktop-lite"},
    )
    assert ack.status_code == 200
    assert ack.json()["status"] == "delivered"
