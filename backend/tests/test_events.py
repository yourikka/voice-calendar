from fastapi.testclient import TestClient


def test_create_and_list_event(client: TestClient) -> None:
    response = client.post(
        "/api/events",
        json={
            "title": "项目评审会",
            "type": "event",
            "start_at": "2026-06-03T14:00:00+08:00",
            "end_at": "2026-06-03T15:00:00+08:00",
            "timezone": "Asia/Shanghai",
            "reminders": [{"method": "notification", "offset_minutes": -10}],
        },
    )

    assert response.status_code == 201
    created = response.json()
    assert created["event"]["title"] == "项目评审会"
    assert created["conflicts"] == []

    list_response = client.get(
        "/api/events",
        params={
            "start": "2026-06-03T00:00:00+08:00",
            "end": "2026-06-04T00:00:00+08:00",
        },
    )

    assert list_response.status_code == 200
    assert [item["title"] for item in list_response.json()["items"]] == ["项目评审会"]


def test_conflict_detection(client: TestClient) -> None:
    first = client.post(
        "/api/events",
        json={
            "title": "产品同步会",
            "start_at": "2026-06-03T14:00:00+08:00",
            "end_at": "2026-06-03T15:00:00+08:00",
        },
    )
    assert first.status_code == 201

    second = client.post(
        "/api/events",
        json={
            "title": "项目复盘会",
            "start_at": "2026-06-03T14:30:00+08:00",
            "end_at": "2026-06-03T15:30:00+08:00",
        },
    )

    assert second.status_code == 201
    conflicts = second.json()["conflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["title"] == "产品同步会"


def test_delete_and_undo(client: TestClient) -> None:
    created = client.post(
        "/api/events",
        json={
            "title": "健身",
            "start_at": "2026-06-03T18:00:00+08:00",
            "end_at": "2026-06-03T19:00:00+08:00",
        },
    ).json()
    event_id = created["event"]["id"]

    delete_response = client.delete(f"/api/events/{event_id}")

    assert delete_response.status_code == 200
    assert delete_response.json()["operation"] == "delete_event"

    empty_list = client.get(
        "/api/events",
        params={
            "start": "2026-06-03T00:00:00+08:00",
            "end": "2026-06-04T00:00:00+08:00",
        },
    ).json()
    assert empty_list["items"] == []

    undo_response = client.post("/api/operations/undo")

    assert undo_response.status_code == 200
    assert undo_response.json()["state"] == "undone"

    restored = client.get(
        "/api/events",
        params={
            "start": "2026-06-03T00:00:00+08:00",
            "end": "2026-06-04T00:00:00+08:00",
        },
    ).json()
    assert [item["title"] for item in restored["items"]] == ["健身"]

