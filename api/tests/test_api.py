import json
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from monitor.main import app

payload = json.loads((Path(__file__).parent / "fixtures" / "studies.json").read_text())
client = TestClient(app)


@pytest.fixture
def upstream():
    with respx.mock(assert_all_called=True) as mock:
        yield mock.get(
            "https://clinicaltrials.gov/api/v2/studies",
            params={
                "query.lead": "AstraZeneca",
                "pageSize": "50",
                "sort": "LastUpdatePostDate:desc",
            },
        )


def test_lists_normalised_lead_sponsor_studies(upstream):
    upstream.respond(json=payload)

    response = client.get("/api/studies")

    assert response.status_code == 200
    body = response.json()
    assert [s["nct_id"] for s in body["studies"]] == ["NCT06137144", "NCT07646600"]
    assert body["skipped"] == 1
    assert body["retrieved_at"]


def test_upstream_timeout_is_gateway_timeout(upstream):
    upstream.side_effect = httpx.ReadTimeout("timed out")

    response = client.get("/api/studies")

    assert response.status_code == 504
    assert response.json() == {
        "detail": "ClinicalTrials.gov did not respond in time.",
        "upstream_status": None,
    }


@pytest.mark.parametrize("status", [400, 500])
def test_upstream_error_status_is_bad_gateway(upstream, status):
    upstream.respond(status, text="Value provided cannot be converted")

    response = client.get("/api/studies")

    assert response.status_code == 502
    assert response.json() == {
        "detail": f"ClinicalTrials.gov returned HTTP {status}.",
        "upstream_status": status,
    }


def test_unreachable_upstream_is_bad_gateway(upstream):
    upstream.side_effect = httpx.ConnectError("connection refused")

    response = client.get("/api/studies")

    assert response.status_code == 502
    assert response.json() == {
        "detail": "ClinicalTrials.gov could not be reached.",
        "upstream_status": None,
    }


@pytest.mark.parametrize("body", ["<html>maintenance</html>", '{"unexpected": []}'])
def test_unreadable_upstream_payload_is_bad_gateway(upstream, body):
    upstream.respond(200, text=body)

    response = client.get("/api/studies")

    assert response.status_code == 502
    assert response.json() == {
        "detail": "ClinicalTrials.gov returned an unreadable response.",
        "upstream_status": 200,
    }
