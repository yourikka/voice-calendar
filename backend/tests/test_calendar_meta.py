from fastapi.testclient import TestClient


def test_calendar_meta_returns_holidays_and_solar_terms(client: TestClient) -> None:
    response = client.get(
        "/api/calendar/meta",
        params={
            "start": "2026-05-01",
            "end": "2026-05-12",
        },
    )

    assert response.status_code == 200
    data = response.json()
    items = {item["date"]: item for item in data["items"]}

    assert items["2026-05-01"]["is_holiday"] is True
    assert items["2026-05-01"]["holiday_name"] == "劳动节"
    assert items["2026-05-05"]["solar_term"] == "立夏"
    assert items["2026-05-09"]["is_adjusted_workday"] is True
