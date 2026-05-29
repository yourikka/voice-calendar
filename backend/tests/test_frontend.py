from fastapi.testclient import TestClient


def test_frontend_index_and_static_assets(client: TestClient) -> None:
    index = client.get("/")

    assert index.status_code == 200
    assert "Voice Calendar" in index.text
    assert 'id="calendar"' in index.text
    assert 'id="voice-button"' in index.text
    assert "fullcalendar" in index.text.lower()

    css = client.get("/static/app.css")
    js = client.get("/static/app.js")

    assert css.status_code == 200
    assert "text/css" in css.headers["content-type"]
    assert js.status_code == 200
    assert "text/javascript" in js.headers["content-type"]
