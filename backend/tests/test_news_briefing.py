from fastapi.testclient import TestClient


def test_today_news_and_hot_topic_panel(client: TestClient) -> None:
    refresh = client.post(
        "/api/news/hot-topics/refresh",
        json={
            "timezone": "Asia/Shanghai",
            "region": "CN",
            "categories": ["general", "technology", "finance"],
        },
    )

    assert refresh.status_code == 200
    assert refresh.json()["status"] == "completed"

    news = client.get(
        "/api/news/today",
        params={"timezone": "Asia/Shanghai", "region": "CN", "limit": 3},
    )

    assert news.status_code == 200
    news_body = news.json()
    assert len(news_body["items"]) == 3
    assert "热点" in news_body["spoken_summary"]

    panel = client.get(
        "/api/calendar/hot-topics",
        params={"date": "2026-05-29", "timezone": "Asia/Shanghai", "limit": 3},
    )

    assert panel.status_code == 200
    panel_body = panel.json()
    assert panel_body["date"] == "2026-05-29"
    assert len(panel_body["items"]) == 3


def test_daily_briefing_combines_calendar_and_news(client: TestClient) -> None:
    client.post(
        "/api/events",
        json={
            "title": "周会",
            "start_at": "2026-05-29T10:00:00+08:00",
            "end_at": "2026-05-29T11:00:00+08:00",
        },
    )

    briefing = client.get(
        "/api/briefings/daily",
        params={"date": "2026-05-29", "timezone": "Asia/Shanghai"},
    )

    assert briefing.status_code == 200
    body = briefing.json()
    assert [section["type"] for section in body["sections"]] == ["calendar", "news"]
    assert "周会" in body["spoken_summary"]
    assert "热点" in body["spoken_summary"]


def test_text_command_uses_news_service(client: TestClient) -> None:
    response = client.post(
        "/api/text/commands",
        json={
            "text": "今天有什么热点",
            "timezone": "Asia/Shanghai",
            "now": "2026-05-29T10:00:00+08:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "get_today_news"
    assert "热点" in body["reply_text"]

