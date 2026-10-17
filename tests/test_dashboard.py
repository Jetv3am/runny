from fastapi.testclient import TestClient

from app.main import app


def test_dashboard_serves_frontend():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "Run with" in response.text
        assert "/static/dashboard.css" in response.text
        assert "/static/dashboard.js" in response.text


def test_dashboard_assets_are_served():
    with TestClient(app) as client:
        css = client.get("/static/dashboard.css")
        js = client.get("/static/dashboard.js")
        assert css.status_code == 200
        assert ".metrics-grid" in css.text
        assert js.status_code == 200
        assert "refreshDashboard" in js.text
