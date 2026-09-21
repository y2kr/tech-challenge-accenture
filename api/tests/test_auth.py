from fastapi.testclient import TestClient

from monitor.auth import api_request_authorized
from monitor.main import app
from monitor.settings import Settings, settings


def test_server_proxy_deployment_does_not_require_cors(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert Settings(_env_file=None).cors_origins == ""


def test_health_does_not_require_api_token():
    response = TestClient(app).get("/health")

    assert response.status_code == 200


def test_api_fails_closed_when_token_unset(monkeypatch):
    monkeypatch.setattr(settings, "api_access_token", "")

    response = TestClient(app).get("/api/changes")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_api_rejects_missing_or_wrong_token():
    client = TestClient(app)

    assert client.get("/api/changes").status_code == 401
    assert (
        client.get(
            "/api/changes", headers={"Authorization": "Bearer wrong-token"}
        ).status_code
        == 401
    )


def test_api_rejects_non_ascii_token_without_error():
    request = type("Request", (), {"headers": {"authorization": "Bearer café"}})()

    assert api_request_authorized(request) is False


def test_api_accepts_configured_bearer_token(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "")

    response = TestClient(app, headers={"Authorization": "Bearer test-api-token"}).get(
        "/api/changes"
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Monitoring database is not configured."}
