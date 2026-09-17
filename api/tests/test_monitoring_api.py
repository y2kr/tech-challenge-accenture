import json
from importlib.resources import files

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from monitor import monitoring
from monitor.clinicaltrials import STUDIES_URL
from monitor.main import app
from monitor.settings import settings

client = TestClient(app)


def test_monitoring_without_database_is_explicitly_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "")
    for method, path in (
        ("post", "/api/sync"),
        ("post", "/api/sync?mode=replay"),
        ("get", "/api/changes"),
        ("get", "/api/changes/1"),
        ("patch", "/api/actions/1"),
    ):
        response = getattr(client, method)(
            path, **({"json": {"status": "approved"}} if method == "patch" else {})
        )
        assert response.status_code == 503
        assert response.json() == {"detail": "Monitoring database is not configured."}
    assert client.get("/health").status_code == 200


@pytest.fixture
def configured_boundary():
    app.dependency_overrides[monitoring.database_engine] = lambda: object()
    yield
    app.dependency_overrides.pop(monitoring.database_engine, None)


def test_live_sync_validates_skips_and_passes_only_valid_snapshots(
    configured_boundary, monkeypatch, caplog
):
    raw = json.loads(files("monitor").joinpath("fixtures/recruiting.json").read_text())
    received = []

    def save(engine, records, source):
        received.extend(records)
        assert source == "live"
        return [7]

    monkeypatch.setattr(monitoring, "_save", save)
    with respx.mock() as upstream:
        upstream.get(STUDIES_URL).respond(json={"studies": [None, raw, []]})
        response = client.post("/api/sync")
    assert response.status_code == 200
    body = response.json()
    assert body["processed"] == 1
    assert body["skipped"] == 2
    assert body["event_ids"] == [7]
    assert body["source"] == "live"
    assert len(received) == 1
    assert received[0][1].overall_status == "RECRUITING"
    assert "Skipped sync study" in caplog.text


def test_replay_is_labelled_and_never_calls_upstream(configured_boundary, monkeypatch):
    def save(engine, records, source):
        assert source == "replay"
        assert [snapshot.overall_status for _, snapshot in records] == [
            "RECRUITING",
            "TERMINATED",
        ]
        return [9]

    monkeypatch.setattr(monitoring, "_save", save)
    with respx.mock():
        response = client.post("/api/sync?mode=replay")
    assert response.status_code == 200
    assert response.json()["label"] == monitoring.REPLAY_LABEL
    assert response.json()["source"] == "replay"
    assert response.json()["event_ids"] == [9]


def test_database_failure_is_sanitised(configured_boundary, monkeypatch):
    def fail(*args):
        raise OperationalError("secret database URL", {}, Exception("password"))

    monkeypatch.setattr(monitoring, "_save", fail)
    response = client.post("/api/sync?mode=replay")
    assert response.status_code == 503
    assert "password" not in response.text
    assert "secret" not in response.text
    assert "migrations" in response.json()["detail"]


def test_live_sync_preserves_upstream_timeout(configured_boundary):
    with respx.mock() as upstream:
        upstream.get(STUDIES_URL).mock(side_effect=httpx.ReadTimeout("timeout"))
        response = client.post("/api/sync")
    assert response.status_code == 504


def test_monitoring_input_and_post_cors(configured_boundary):
    assert client.post("/api/sync?mode=arbitrary").status_code == 422
    assert client.get("/api/changes?limit=101").status_code == 422
    assert client.get("/api/changes?source=arbitrary").status_code == 422
    assert client.get("/api/changes/0").status_code == 422
    response = client.options(
        "/api/actions/1",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "PATCH",
        },
    )
    assert response.status_code == 200
    assert "PATCH" in response.headers["access-control-allow-methods"]


def test_ai_explanation_is_structured_and_receives_only_evidence(monkeypatch):
    change = monitoring.FieldChange(
        field="overall_status", before="RECRUITING", after="TERMINATED"
    )
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    received = {}

    analysis_result = monitoring.AIAnalysis(
        headline="Study status changed to terminated",
        summary="The status moved from recruiting to terminated.",
        possible_significance=["The change may warrant analyst review."],
        confidence="high",
    )

    class Completions:
        def parse(self, **kwargs):
            received.update(kwargs)
            message = type("Message", (), {"parsed": analysis_result})()
            choice = type("Choice", (), {"message": message})()
            return type("Completion", (), {"choices": [choice]})()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = type("Chat", (), {"completions": Completions()})()

    monkeypatch.setattr(monitoring, "OpenAI", FakeOpenAI)

    analysis = monitoring._generate_ai_analysis([change])

    assert analysis is not None
    assert analysis.confidence == "high"
    user_payload = json.loads(received["messages"][1]["content"])
    assert user_payload == {"evidence": [change.model_dump(mode="json")]}
    assert "severity" not in user_payload
