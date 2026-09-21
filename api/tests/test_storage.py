import json
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import sessionmaker

from monitor import monitoring
from monitor.changes import normalise_snapshot
from monitor.main import app
from monitor.monitoring import database_engine
from monitor.settings import settings
from monitor.storage import (
    AuditEntry,
    ChangeEvent,
    FollowUpAction,
    StoredStudy,
    StudySnapshot,
    VerificationDraft,
    VerificationDraftHistory,
    persist_snapshot,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or settings.test_database_url


def db_url() -> URL:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL unset")
    url = make_url(TEST_DATABASE_URL)
    if url.get_backend_name() != "postgresql":
        pytest.fail("TEST_DATABASE_URL must reference PostgreSQL")
    return url.set(drivername="postgresql+psycopg")


@pytest.fixture
def sessions():
    schema = f"test_{uuid.uuid4().hex}"
    engine = create_engine(db_url(), connect_args={"connect_timeout": 5})
    preparer = engine.dialect.identifier_preparer
    quoted = preparer.quote_schema(schema)
    conn = None
    created = False
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
            admin.execute(text(f"create schema {quoted}"))
            created = True
        conn = engine.connect()
        conn.execute(text(f"set search_path to {quoted}"))
        cfg = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        cfg.attributes["connection"] = conn
        cfg.attributes["schema"] = schema
        command.upgrade(cfg, "head")
        conn.commit()
        yield sessionmaker(bind=conn, expire_on_commit=False)
    finally:
        if conn is not None:
            conn.close()
        if created:
            with engine.connect().execution_options(
                isolation_level="AUTOCOMMIT"
            ) as admin:
                admin.execute(text(f"drop schema {quoted} cascade"))
        engine.dispose()


def raw(status: str = "RECRUITING", title: str = "Trial") -> dict:
    return {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT16090001", "briefTitle": title},
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": "AstraZeneca"}},
            "statusModule": {
                "overallStatus": status,
                "lastUpdatePostDateStruct": {"date": "2026-09-01"},
                "primaryCompletionDateStruct": {"date": "2026-10-01"},
                "completionDateStruct": {"date": "2026-12-01"},
            },
            "designModule": {"phases": ["PHASE3"], "enrollmentInfo": {"count": 100}},
            "armsInterventionsModule": {
                "interventions": [{"name": "Drug", "type": "DRUG"}]
            },
            "outcomesModule": {"primaryOutcomes": [{"measure": "Response"}]},
            "eligibilityModule": {"eligibilityCriteria": "Adults"},
            "contactsLocationsModule": {"locations": []},
        }
    }


def terminated() -> dict:
    item = raw("TERMINATED")
    item["protocolSection"]["statusModule"]["whyStopped"] = "Synthetic stop"
    return item


def save(session, item: dict, source="live"):
    return persist_snapshot(session, item, normalise_snapshot(item), source)


def test_migration_offline_sql_contains_tables(capsys):
    cfg = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    command.upgrade(cfg, "head", sql=True)

    output = capsys.readouterr().out
    assert "CREATE TABLE studies" in output
    assert "CREATE TABLE study_snapshots" in output
    assert "CREATE TABLE change_events" in output
    assert "CREATE TABLE follow_up_actions" in output
    assert "CREATE TABLE audit_entries" in output
    assert "CREATE TABLE verification_drafts" in output
    assert "CREATE TABLE verification_draft_history" in output


def test_repeat_sync_updates_metadata_without_duplicate_event(sessions):
    with sessions() as session:
        assert save(session, raw()) is None
        session.commit()
    updated = raw(title="Updated title")
    with sessions() as session:
        assert save(session, updated) is None
        session.commit()
        study = session.scalar(select(StoredStudy))
        assert study.title == "Updated title"
        assert session.scalar(select(func.count()).select_from(StudySnapshot)) == 1
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == 0


def test_restart_session_persists_baseline(sessions):
    with sessions() as session:
        assert save(session, raw()) is None
        session.commit()
    with sessions() as session:
        event = save(session, terminated())
        session.commit()
        assert event is not None
        assert event.severity == "critical"
        assert event.structured_diff[0]["field"] in {"overall_status", "reason_stopped"}


def test_returning_to_old_hash_still_creates_events(sessions):
    a = raw()
    b = terminated()
    with sessions() as session:
        assert save(session, a) is None
        assert save(session, b) is not None
        assert save(session, a) is not None
        assert save(session, b) is not None
        session.commit()
        assert session.scalar(select(func.count()).select_from(StudySnapshot)) == 2
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == 3


def test_source_namespace_isolated(sessions):
    with sessions() as session:
        assert save(session, raw(), "live") is None
        assert save(session, raw(), "replay") is None
        event = save(session, terminated(), "replay")
        assert event is not None
        assert save(session, raw(), "live") is None
        session.commit()
        assert session.scalar(select(func.count()).select_from(StoredStudy)) == 2
        source = session.scalar(
            select(StoredStudy.source).join(
                ChangeEvent, ChangeEvent.study_id == StoredStudy.id
            )
        )
        assert source == "replay"


def test_repeated_replay_does_not_rewind_current_snapshot(sessions):
    with sessions() as session:
        assert save(session, raw(), "replay") is None
        assert save(session, terminated(), "replay") is not None
        session.commit()
    with sessions() as session:
        assert (
            persist_snapshot(
                session, raw(), normalise_snapshot(raw()), "replay", baseline_only=True
            )
            is None
        )
        assert save(session, terminated(), "replay") is None
        session.commit()
        assert session.scalar(select(func.count()).select_from(StudySnapshot)) == 2
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == 1
        current = session.scalar(
            select(StoredStudy).where(StoredStudy.source == "replay")
        )
        snapshot = session.get(StudySnapshot, current.current_snapshot_id)
        assert snapshot.normalised_data["overall_status"] == "TERMINATED"


def test_api_replay_flow_uses_database_dependency_override(sessions, monkeypatch):
    def fail_ai(changes):
        raise ValueError("model timeout")

    monkeypatch.setattr("monitor.monitoring._generate_ai_analysis", fail_ai)
    app.dependency_overrides[database_engine] = lambda: sessions.kw["bind"]
    try:
        with TestClient(
            app, headers={"Authorization": "Bearer test-api-token"}
        ) as client:
            first = client.post("/api/sync", params={"mode": "replay"})
            assert first.status_code == 200
            first_payload = first.json()
            assert first_payload["source"] == "replay"
            assert len(first_payload["event_ids"]) == 5

            repeat = client.post("/api/sync", params={"mode": "replay"})
            assert repeat.status_code == 200
            assert repeat.json()["event_ids"] == []

            live = client.get("/api/changes", params={"source": "live"})
            assert live.status_code == 200
            assert live.json() == []

            replay_changes = client.get("/api/changes", params={"source": "replay"})
            assert replay_changes.status_code == 200
            changes = replay_changes.json()
            assert len(changes) == 5
            assert {change["source"] for change in changes} == {"replay"}
            assert {change["severity"] for change in changes} == {
                "critical",
                "high",
                "medium",
            }
            assert changes[0]["severity"] == "critical"

            missing = client.get("/api/changes/999999")
            assert missing.status_code == 404

            detail = client.get(f"/api/changes/{changes[0]['id']}")
            assert detail.status_code == 200
            payload = detail.json()
            assert (
                payload["before"]["normalised_data"]["overall_status"] == "RECRUITING"
            )
            assert payload["after"]["normalised_data"]["overall_status"] == "TERMINATED"
            status_change = next(
                item
                for item in payload["structured_diff"]
                if item["field"] == "overall_status"
            )
            assert status_change == {
                "field": "overall_status",
                "before": "RECRUITING",
                "after": "TERMINATED",
            }
            assert payload["ai_analysis"] is None
            assert payload["draft"] is None
            assert payload["draft_history"] == []
            assert len(payload["actions"]) == 2
            assert {action["status"] for action in payload["actions"]} == {"proposed"}
            assert payload["audit_timeline"] == []

            action = payload["actions"][0]
            decision = client.patch(
                f"/api/actions/{action['id']}", json={"status": "approved"}
            )
            assert decision.status_code == 200
            assert decision.json()["status"] == "approved"

            decided = client.get(f"/api/changes/{changes[0]['id']}").json()
            assert decided["review_status"] == "approved"
            assert decided["audit_timeline"][0] == {
                "id": decided["audit_timeline"][0]["id"],
                "action_id": action["id"],
                "action_title": action["title"],
                "decision": "approved",
                "created_at": decided["audit_timeline"][0]["created_at"],
            }
            assert session_count(sessions, AuditEntry) == 1
            assert session_count(sessions, FollowUpAction) == 10
    finally:
        app.dependency_overrides.pop(database_engine, None)


def test_draft_api_versions_edits_and_decisions(sessions, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(monitoring, "_generate_ai_analysis", lambda changes: None)

    received = {}

    class Completions:
        def parse(self, **kwargs):
            received.update(kwargs)
            draft = monitoring.VerificationDraftBody(
                body="Synthetic replay: ask the study owner to verify the public-record change."
            )
            message = type("Message", (), {"parsed": draft})()
            choice = type("Choice", (), {"message": message})()
            return type("Completion", (), {"choices": [choice]})()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = type("Chat", (), {"completions": Completions()})()

    monkeypatch.setattr(monitoring, "OpenAI", FakeOpenAI)
    app.dependency_overrides[database_engine] = lambda: sessions.kw["bind"]
    try:
        with TestClient(app) as client:
            headers = {"Authorization": "Bearer test-api-token"}
            client.post("/api/sync", params={"mode": "replay"}, headers=headers)
            change_id = client.get(
                "/api/changes", params={"source": "replay"}, headers=headers
            ).json()[0]["id"]

            generated = client.post(f"/api/changes/{change_id}/draft", headers=headers)
            assert generated.status_code == 200
            assert generated.json()["revision"] == 1
            assert generated.json()["origin"] == "ai"
            user_payload = json.loads(received["messages"][1]["content"])
            assert user_payload["evidence"]["study"]["nct_id"] == "NCT90000001"
            assert user_payload["evidence"]["study"]["source"] == "replay"
            assert "Synthetic replay" in user_payload["evidence"]["study"]["label"]
            assert user_payload["evidence"]["changes"][0]["field"]

            duplicate = client.post(f"/api/changes/{change_id}/draft", headers=headers)
            assert duplicate.status_code == 200
            assert duplicate.json() == generated.json()

            stale = client.patch(
                f"/api/changes/{change_id}/draft",
                json={"body": "Manual request.", "revision": 0},
                headers=headers,
            )
            assert stale.status_code == 409

            edited = client.patch(
                f"/api/changes/{change_id}/draft",
                json={"body": "Manual request.", "revision": 1},
                headers=headers,
            )
            assert edited.status_code == 200
            assert edited.json()["revision"] == 2
            assert edited.json()["status"] == "proposed"
            assert edited.json()["origin"] == "manual"

            approved = client.post(
                f"/api/changes/{change_id}/draft/decision",
                json={"status": "approved", "revision": 2},
                headers=headers,
            )
            assert approved.status_code == 200
            assert approved.json()["status"] == "approved"

            no_op_edit = client.patch(
                f"/api/changes/{change_id}/draft",
                json={"body": "Manual request.", "revision": 2},
                headers=headers,
            )
            assert no_op_edit.status_code == 200
            assert no_op_edit.json()["revision"] == 2
            assert no_op_edit.json()["origin"] == "manual"
            assert no_op_edit.json()["status"] == "approved"

            no_op_decision = client.post(
                f"/api/changes/{change_id}/draft/decision",
                json={"status": "approved", "revision": 2},
                headers=headers,
            )
            assert no_op_decision.status_code == 200

            stale_decision = client.post(
                f"/api/changes/{change_id}/draft/decision",
                json={"status": "rejected", "revision": 1},
                headers=headers,
            )
            assert stale_decision.status_code == 409

            action_id = client.get(f"/api/changes/{change_id}", headers=headers).json()[
                "actions"
            ][0]["id"]
            legacy_decision = client.patch(
                f"/api/actions/{action_id}",
                json={"status": "rejected"},
                headers=headers,
            )
            assert legacy_decision.status_code == 200

            detail = client.get(f"/api/changes/{change_id}", headers=headers).json()
            assert detail["review_status"] == "approved"
            assert detail["draft"]["status"] == "approved"
            assert [entry["event"] for entry in detail["draft_history"]] == [
                "generated",
                "edited",
                "approved",
            ]
            assert (
                client.get(
                    "/api/changes", params={"source": "replay"}, headers=headers
                ).json()[0]["review_status"]
                == "approved"
            )
            assert session_count(sessions, VerificationDraft) == 1
            assert session_count(sessions, VerificationDraftHistory) == 3
    finally:
        app.dependency_overrides.pop(database_engine, None)


def test_generate_draft_without_ai_is_clear_503(sessions, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(monitoring, "_generate_ai_analysis", lambda changes: None)
    app.dependency_overrides[database_engine] = lambda: sessions.kw["bind"]
    try:
        with TestClient(app) as client:
            headers = {"Authorization": "Bearer test-api-token"}
            client.post("/api/sync", params={"mode": "replay"}, headers=headers)
            change_id = client.get(
                "/api/changes", params={"source": "replay"}, headers=headers
            ).json()[0]["id"]
            response = client.post(f"/api/changes/{change_id}/draft", headers=headers)
            assert response.status_code == 503
            assert response.json() == {
                "detail": "AI verification draft is unavailable."
            }
    finally:
        app.dependency_overrides.pop(database_engine, None)


def test_transactional_rollback_removes_snapshot_and_event(sessions):
    with sessions() as session:
        assert save(session, raw()) is None
        session.commit()
    with sessions() as session:
        transaction = session.begin()
        assert save(session, terminated()) is not None
        transaction.rollback()
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(StudySnapshot)) == 1
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == 0


def test_migration_created_tables(sessions):
    with sessions() as session:
        tables = session.scalars(
            text("select tablename from pg_tables where schemaname = current_schema()")
        ).all()
        assert {
            "studies",
            "study_snapshots",
            "change_events",
            "follow_up_actions",
            "audit_entries",
            "verification_drafts",
            "verification_draft_history",
            "alembic_version",
        } <= set(tables)


def session_count(sessions, model) -> int:
    with sessions() as session:
        return session.scalar(select(func.count()).select_from(model))
