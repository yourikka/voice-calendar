from fastapi.testclient import TestClient


def test_frontend_index_and_static_assets(client: TestClient) -> None:
    index = client.get("/")

    assert index.status_code == 200
    assert "Voice Calendar" in index.text
    assert 'id="calendar"' in index.text
    assert 'id="voice-button"' in index.text
    assert 'id="voice-cancel"' in index.text
    assert 'id="search-button"' in index.text
    assert "fullcalendar" in index.text.lower()
    assert "/static/calendar-utils.js" in index.text
    assert "/static/api.js" in index.text

    css = client.get("/static/app.css")
    js = client.get("/static/app.js")
    api_js = client.get("/static/api.js")
    calendar_utils_js = client.get("/static/calendar-utils.js")

    assert css.status_code == 200
    assert "text/css" in css.headers["content-type"]
    assert js.status_code == 200
    assert "text/javascript" in js.headers["content-type"]
    assert api_js.status_code == 200
    assert "text/javascript" in api_js.headers["content-type"]
    assert calendar_utils_js.status_code == 200
    assert "text/javascript" in calendar_utils_js.headers["content-type"]
