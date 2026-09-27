"""Regression coverage for reviewable sources and explicit provider disclosure."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import pytest

from bodybrain.config import Settings
from bodybrain.db import StateConflict
from bodybrain.main import create_app, re_causal


@pytest.fixture
def settings(tmp_path):
    return replace(Settings(), data_dir=tmp_path, cognee_mode="disabled", cognee_url="", cognee_api_key="", cognee_token="", clawmax_url="", clawmax_token="", api_token="", agent_token="test-worker")


@pytest.fixture
def workflow():
    return SimpleNamespace(configured=True, trigger_task=AsyncMock(return_value={"status": "submitted"}), execution=AsyncMock(return_value={"status": "running"}))


@pytest.mark.parametrize("text", ["Brief note.", "OK", "No 2.3 cm lesion in the right kidney.", "No fracture\nof the right femur.", "Observation " * 220])
def test_every_accepted_small_record_has_complete_reviewable_evidence(settings, text):
    with TestClient(create_app(settings)) as client:
        record = client.post("/api/records/text", json={"title": "Context regression", "text": text}).json()
        assert record["findings"]
        assert {finding["quote"] for finding in record["findings"]} == {text.strip()}
        approval = client.post(f"/api/records/{record['id']}/approve", json={})
        assert approval.status_code == 200, approval.text
        answer = client.post("/api/chat", json={"question": "Show my complete history"}).json()
        assert [citation["quote"] for citation in answer["citations"]] == [text.strip()]


def test_unmapped_treatment_passage_is_reviewable_beside_anatomy(settings):
    with TestClient(create_app(settings)) as client:
        record = client.post("/api/records/text", json={"title": "Mixed record", "text": "The right femur appears normal. Follow-up scheduled next month."}).json()
        follow_up = next(f for f in record["findings"] if f["quote"] == "Follow-up scheduled next month.")
        assert follow_up["concept"] is None
        assert client.post(f"/api/records/{record['id']}/approve", json={"finding_ids": [follow_up["id"]]}).status_code == 200
        assert client.post("/api/chat", json={"question": "When is follow-up scheduled?"}).json()["citations"][0]["quote"] == follow_up["quote"]
        assert client.post("/api/chat", json={"question": "femur"}).json()["citations"] == []


def test_imports_and_demo_do_not_dispatch_without_opt_in(settings, workflow):
    with TestClient(create_app(settings, clawmax_ingest=workflow)) as client:
        assert client.post("/api/records/text", json={"title": "Local text", "text": "The right femur appears normal."}).status_code == 201
        assert client.post("/api/records", files={"file": ("local.txt", b"The left kidney appears normal.")}).status_code == 201
        assert client.post("/api/demo").status_code == 201
        workflow.trigger_task.assert_not_awaited()


def test_chat_requires_consent_and_only_discloses_relevant_passages(settings, workflow):
    with TestClient(create_app(settings, clawmax_evidence=workflow)) as client:
        record = client.post("/api/records/text", json={"title": "Mixed record", "text": "The right femur appears normal. The left kidney appears normal."}).json()
        assert client.post(f"/api/records/{record['id']}/approve", json={}).status_code == 200
        local = client.post("/api/chat", json={"question": "femur"}).json()
        assert local["agent_task_id"] is None
        workflow.trigger_task.assert_not_awaited()
        result = client.post("/api/chat", json={"question": "femur", "allow_agent": True}).json()
        assert result["agent_task_id"]
        workflow.trigger_task.assert_awaited_once()
        task = client.get(f"/api/agent/tasks/{result['agent_task_id']}", headers={"Authorization": "Bearer test-worker"}).json()
        assert "kidney" not in str(task["records"])
        assert {f["quote"] for r in task["records"] for f in r["findings"]} == {"The right femur appears normal."}
        unrelated = client.post("/api/chat", json={"question": "medication dosage", "allow_agent": True}).json()
        assert unrelated["agent_task_id"] is None
        assert unrelated["citations"] == []
        assert workflow.trigger_task.await_count == 1


def test_upload_explicit_date_overrides_document_date(settings):
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/records", files={"file": ("dated.txt", b"Report date: 2026-01-01\nThe right femur appears normal.")}, data={"event_date": "2026-02-02"})
        assert response.status_code == 201
        assert response.json()["event_date"] == "2026-02-02"


@pytest.mark.parametrize("source,fragment", [("No 2.3 cm lesion in the right kidney.", "3 cm lesion in the right kidney."), ("No fracture\nof the right femur.", "of the right femur.")])
def test_ingestion_agent_cannot_detach_negation_from_a_source(settings, source, fragment):
    app = create_app(settings)
    with TestClient(app) as client:
        record = client.post("/api/records/text", json={"title": "Negation", "text": source}).json()
        app.state.service.store.save_task({"id": "negation-task", "kind": "ingestion", "status": "pending", "record_id": record["id"]})
        body = {"findings": [{"quote": fragment, "page": 1, "anatomy_query": "anatomy"}]}
        response = client.post("/api/agent/tasks/negation-task/result", json=body, headers={"Authorization": "Bearer test-worker"})
        assert response.status_code == 422
        body["findings"][0]["quote"] = source
        response = client.post("/api/agent/tasks/negation-task/result", json=body, headers={"Authorization": "Bearer test-worker"})
        assert response.status_code == 200, response.text


def test_approval_reconciles_original_activity(settings):
    with TestClient(create_app(settings)) as client:
        record = client.post("/api/records/text", json={"title": "Short", "text": "Brief note."}).json()
        client.post(f"/api/records/{record['id']}/approve", json={})
        runs = client.get("/api/runs").json()["runs"]
        ingestion = next(run for run in runs if run["kind"] == "record_ingestion")
        assert ingestion["status"] != "awaiting_review"
        assert next(step for step in ingestion["steps"] if step["name"] == "Human review")["status"] == "completed"


def test_restart_repairs_empty_pending_drafts_without_rewriting_reviewed_records(settings):
    with TestClient(create_app(settings)) as client:
        pending = client.post("/api/records/text", json={"title": "Legacy draft", "text": "Brief note."}).json()
        approved = client.post("/api/records/text", json={"title": "Reviewed", "text": "The right femur appears normal."}).json()
        client.post(f"/api/records/{approved['id']}/approve", json={})
        store = client.app.state.service.store
        store.update(pending["id"], findings=[])
        reviewed_before_restart = store.get(approved["id"])
    with TestClient(create_app(settings)) as restarted:
        restored = restarted.get(f"/api/records/{pending['id']}").json()
        assert [finding["quote"] for finding in restored["findings"]] == ["Brief note."]
        assert restarted.get(f"/api/records/{approved['id']}").json() == reviewed_before_restart
        assert restarted.post(f"/api/records/{pending['id']}/approve", json={}).status_code == 200


def test_only_state_conflicts_are_reported_as_review_conflicts(settings, monkeypatch):
    app = create_app(settings)
    with TestClient(app, raise_server_exceptions=False) as client:
        record = client.post("/api/records/text", json={"title": "Short", "text": "Brief note."}).json()
        def conflict(*args, **kwargs):
            raise StateConflict("changed")
        monkeypatch.setattr(app.state.service.store, "update", conflict)
        response = client.post(f"/api/records/{record['id']}/approve", json={})
        assert response.status_code == 409
        def unrelated(*args, **kwargs):
            raise ValueError("implementation failure")
        monkeypatch.setattr(app.state.service.store, "update", unrelated)
        response = client.post(f"/api/records/{record['id']}/approve", json={})
        assert response.status_code == 500
        assert "record changed" not in response.text.lower()


@pytest.mark.parametrize("question", ["What is the diagnosis?", "Was this diagnosed?", "Can you diagnose this?", "What caused this?", "What dosage?", "Should I take it?"])
def test_diagnostic_and_causal_questions_are_detected(question):
    assert re_causal(question)


def test_upload_limit_rejects_before_parsing(settings, monkeypatch):
    app = create_app(settings)
    def unexpected_parse(*args, **kwargs):
        pytest.fail("An oversized upload must not reach the parser")
    monkeypatch.setattr(app.state.service, "create_record", unexpected_parse)
    with TestClient(app) as client:
        response = client.post("/api/records", files={"file": ("large.txt", b"x" * (settings.max_upload_bytes + 1))})
        assert response.status_code == 413
