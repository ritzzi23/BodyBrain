"""Exercise provider orchestration against the real API, SQLite, and lifecycle."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import httpx
import pytest

from bodybrain.clawmax import ClawMaxClient
from bodybrain.config import Settings
from bodybrain.evidence import render_answer
from bodybrain.main import create_app


TEXT = "Report date: 2026-03-15\nLumbar spine MRI. At L5-S1, a right disc protrusion contacts the right S1 nerve root.\nNo fracture of the right femur."
WORKER_HEADERS = {"Authorization": "Bearer worker-test-secret"}
USER_HEADERS = {"Authorization": "Bearer user-test-secret"}


class Memory:
    def __init__(self, *, fail=False, block=False):
        self.fail = fail
        self.block = block
        self.calls = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def status(self, probe=False):
        return {"provider": "cognee", "configured": True, "status": "ready"}

    async def remember(self, document_id, text, metadata):
        self.calls.append({"id": document_id, "text": text, "metadata": metadata})
        self.entered.set()
        if self.block:
            await self.release.wait()
        if self.fail:
            raise RuntimeError("upstream error contains a private token")
        return {"status": "completed"}

    async def recall(self, question, limit=8):
        return {"document_ids": [entry["id"] for entry in self.calls]}


class Workflow:
    configured = True

    def __init__(self, *, submit=True):
        self.task_ids = []
        self.submit = submit
        self.before_return = None
        self.execution_status = "running"
        self.execution_calls = []
        self.before_execution_return = None

    async def health(self):
        return {"provider": "clawmax", "configured": True, "status": "ready"}

    async def trigger_task(self, task_id):
        self.task_ids.append(task_id)
        if self.before_return:
            await self.before_return(task_id)
        return {"provider": "clawmax", "status": "submitted" if self.submit else "error", "execution_id": "test-exec-" + task_id}

    async def execution(self, execution_id):
        self.execution_calls.append(execution_id)
        if self.before_execution_return:
            await self.before_execution_return(execution_id)
        return {"provider": "clawmax", "status": self.execution_status, "execution_id": execution_id}


@pytest.fixture
def settings(tmp_path):
    return replace(
        Settings(), data_dir=tmp_path, cognee_mode="disabled", cognee_url="",
        cognee_api_key="", cognee_token="", clawmax_url="", clawmax_token="",
        api_token="user-test-secret", agent_token="worker-test-secret",
    )


@asynccontextmanager
async def connected(settings, memory=None, ingestion=None, evidence=None):
    app = create_app(
        settings, memory=memory or Memory(),
        clawmax_ingest=ingestion or ClawMaxClient(),
        clawmax_evidence=evidence or ClawMaxClient(),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver", headers=USER_HEADERS) as client:
            yield client, app.state.service


async def add(client, text=TEXT, *, allow_agent=True):
    response = await client.post("/api/records/text", json={"title": "Integration test report", "text": text, "allow_agent": allow_agent})
    assert response.status_code == 201, response.text
    return response.json()


async def drain(service):
    await asyncio.wait_for(service.queue.join(), timeout=3)
    if service.jobs:
        await asyncio.wait_for(asyncio.gather(*tuple(service.jobs)), timeout=3)


async def approve(client, record, ids=None):
    response = await client.post(f"/api/records/{record['id']}/approve", json={} if ids is None else {"finding_ids": ids})
    assert response.status_code == 200, response.text
    return response.json()


async def test_only_approved_findings_reach_cognee_and_index_once(settings):
    memory = Memory()
    async with connected(settings, memory=memory) as (client, service):
        record = await add(client)
        await drain(service)
        assert memory.calls == []
        femur = next(item for item in record["findings"] if "femur" in item["quote"])
        await approve(client, record, [femur["id"]])
        await drain(service)
        assert len(memory.calls) == 1
        indexed = memory.calls[0]
        assert indexed["id"] == record["id"]
        assert "No fracture of the right femur." in indexed["text"]
        assert "disc protrusion" not in indexed["text"]
        assert (await client.get(f"/api/records/{record['id']}")).json()["memory_status"] == "indexed"
        await approve(client, record)
        await drain(service)
        assert len(memory.calls) == 1


async def test_failed_index_preserves_review_and_source_then_retries(settings):
    memory = Memory(fail=True)
    async with connected(settings, memory=memory) as (client, service):
        record = await add(client)
        await approve(client, record)
        await drain(service)
        stored = (await client.get(f"/api/records/{record['id']}")).json()
        assert stored["status"] == "approved" and stored["memory_status"] == "failed"
        assert "private token" not in stored["index_error"]
        assert (await client.get(f"/api/records/{record['id']}/source")).text == TEXT
        assert any(run["kind"] == "memory_index" and run["status"] == "failed" for run in service.store.runs())
        memory.fail = False
        assert (await client.post(f"/api/records/{record['id']}/index")).status_code == 200
        await drain(service)
        assert service.store.get(record["id"])["memory_status"] == "indexed"
        assert len(memory.calls) == 2


async def test_pending_index_resumes_after_process_lifecycle_restart(settings):
    interrupted = Memory(block=True)
    async with connected(settings, memory=interrupted) as (client, service):
        record = await add(client)
        await approve(client, record)
        await asyncio.wait_for(interrupted.entered.wait(), timeout=3)
        assert service.store.get(record["id"])["memory_status"] == "pending"
    resumed = Memory()
    async with connected(settings, memory=resumed) as (client, service):
        await drain(service)
        assert service.store.get(record["id"])["memory_status"] == "indexed"
        assert [call["id"] for call in resumed.calls] == [record["id"]]
        assert (await client.get(f"/api/records/{record['id']}/source")).text == TEXT
        assert any(run["kind"] == "memory_index" and run["status"] == "interrupted" for run in service.store.runs())


async def test_ingestion_callback_requires_worker_auth_and_human_review(settings):
    workflow, memory = Workflow(), Memory()
    async with connected(settings, memory=memory, ingestion=workflow) as (client, service):
        record = await add(client)
        await drain(service)
        task_id = workflow.task_ids[0]
        task_path = f"/api/agent/tasks/{task_id}"
        assert (await client.get(task_path)).status_code == 401  # User and worker tokens are separate.
        task = (await client.get(task_path, headers=WORKER_HEADERS)).json()
        assert task["record"]["id"] == record["id"] and task["status"] == "pending"
        body = {"findings": [{"quote": "No fracture of the right femur.", "page": 1, "anatomy_query": "right femur", "concept_id": None, "laterality": "right"}]}
        response = await client.post(task_path + "/result", json=body, headers=WORKER_HEADERS)
        assert response.status_code == 200, response.text
        assert response.json()["result"]["review_required"]
        stored = service.store.get(record["id"])
        assert stored["status"] == "pending_review"
        assert stored["extraction_mode"] == "clawmax_agent"
        assert not stored["findings"][0]["approved"] and not memory.calls
        assert (await client.post(f"/api/records/{record['id']}/approve", json={}, headers=WORKER_HEADERS)).status_code == 401
        assert (await client.post(task_path + "/result", json=body, headers=WORKER_HEADERS)).status_code == 409
        assert service.store.task(task_id)["status"] == "completed"
        await approve(client, stored)
        await drain(service)
        assert len(memory.calls) == 1


async def test_failed_workflow_submission_is_persisted_as_failed(settings):
    workflow = Workflow(submit=False)
    async with connected(settings, ingestion=workflow) as (client, service):
        record = await add(client)
        await drain(service)
        task = service.store.task(workflow.task_ids[0])
        assert task["status"] == "failed"
        assert service.store.get(record["id"])["status"] == "pending_review"
        assert any(run["kind"] == "clawmax_ingestion" and run["status"] == "failed" for run in service.store.runs())


async def test_repeated_upload_reuses_task_and_empty_findings_preserve_review_draft(settings):
    workflow = Workflow()
    async with connected(settings, ingestion=workflow) as (client, service):
        record = await add(client)
        await drain(service)
        assert (await add(client))["id"] == record["id"]
        await drain(service)
        assert len(workflow.task_ids) == 1
        response = await client.post(
            f"/api/agent/tasks/{workflow.task_ids[0]}/result", headers=WORKER_HEADERS,
            json={"findings": []},
        )
        assert response.status_code == 200, response.text
        assert response.json()["result"]["local_draft_preserved"] is True
        stored = service.store.get(record["id"])
        assert stored["status"] == "pending_review"
        assert stored["findings"] == record["findings"]


async def test_evidence_callback_limits_sources_to_reviewed_task_snapshot(settings):
    workflow = Workflow()
    async with connected(settings, evidence=workflow) as (client, service):
        record = await add(client)
        femur = next(item for item in record["findings"] if "femur" in item["quote"])
        await approve(client, record, [femur["id"]])
        await drain(service)
        answer = (await client.post("/api/chat", json={"question": "What did the femur report say?", "allow_agent": True})).json()
        task_id = answer["agent_task_id"]
        task_path = f"/api/agent/tasks/{task_id}"
        context = (await client.get(task_path, headers=WORKER_HEADERS)).json()
        assert [r["id"] for r in context["records"]] == [record["id"]]
        assert "disc protrusion" not in json.dumps(context["records"])
        later = await add(client, "Report date: 2026-04-01\nThe left humerus appears normal.")
        await approve(client, later)
        await drain(service)
        assert [r["id"] for r in (await client.get(task_path, headers=WORKER_HEADERS)).json()["records"]] == [record["id"]]
        later_citation = {"record_id": later["id"], "page": 1, "quote": "The left humerus appears normal."}
        rejected = await client.post(task_path + "/result", headers=WORKER_HEADERS, json={"answer": "Unsupported task source", "citations": [later_citation]})
        assert rejected.status_code == 422
        rejected_passage = {"record_id": record["id"], "page": 1, "quote": "a right disc protrusion contacts the right S1 nerve root"}
        assert (await client.post(task_path + "/result", headers=WORKER_HEADERS, json={"answer": "Rejected finding", "citations": [rejected_passage]})).status_code == 422
        good = {"record_id": record["id"], "page": 1, "quote": femur["quote"]}
        response = await client.post(task_path + "/result", headers=WORKER_HEADERS, json={"answer": "The fracture is severe (unverified agent prose).", "citations": [good]})
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert result["citations"][0]["quote"] == femur["quote"]
        assert "fracture is severe" not in result["answer"]
        assert service.store.task(task_id)["status"] == "completed"


async def test_empty_evidence_returns_canonical_no_evidence_answer(settings):
    workflow = Workflow()
    async with connected(settings, evidence=workflow) as (client, service):
        record = await add(client)
        await approve(client, record)
        # An agent may decline to select any citations from an otherwise relevant task.
        answer = (await client.post("/api/chat", json={"question": "What did the femur report say?", "allow_agent": True})).json()
        response = await client.post(
            f"/api/agent/tasks/{answer['agent_task_id']}/result", headers=WORKER_HEADERS,
            json={"answer": "Unsupported arbitrary agent claim", "citations": []},
        )
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert result["answer"] == render_answer([])
        assert result["citations"] == []


async def test_callback_completing_before_trigger_response_is_not_overwritten(settings):
    workflow = Workflow()
    async with connected(settings, ingestion=workflow) as (client, service):
        async def immediate_callback(task_id):
            response = await client.post(
                f"/api/agent/tasks/{task_id}/result", headers=WORKER_HEADERS,
                json={"findings": [{"quote": "No fracture of the right femur.", "page": 1, "anatomy_query": "right femur"}]},
            )
            assert response.status_code == 200, response.text

        workflow.before_return = immediate_callback
        await add(client)
        await drain(service)
        task = service.store.task(workflow.task_ids[0])
        assert task["status"] == "completed" and task["result"]["review_required"]
        run = next(run for run in service.store.runs() if run["id"] == task["run_id"])
        assert run["status"] == "completed"
        assert task["execution"]["status"] == "submitted"


@pytest.mark.parametrize("remote_status", ["failed", "completed"])
async def test_terminal_execution_without_callback_marks_task_and_run_failed(settings, remote_status):
    workflow = Workflow()
    workflow.execution_status = remote_status
    async with connected(settings, ingestion=workflow) as (client, service):
        record = await add(client)
        await drain(service)
        task_id = workflow.task_ids[0]
        response = await client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200, response.text
        task = response.json()
        assert task["status"] == "failed"
        assert task["execution_state"]["status"] == remote_status
        assert task["result"] is None
        expected_error = "without a validated" if remote_status == "completed" else "workflow failure"
        assert expected_error in task["error"]
        run = next(run for run in (await client.get("/api/runs")).json()["runs"] if run["id"] == task["run_id"])
        assert run["status"] == "failed"
        assert service.store.get(record["id"])["status"] == "pending_review"
        assert len(workflow.execution_calls) == 1


async def test_task_and_run_polling_share_five_second_throttle(settings):
    workflow = Workflow()
    async with connected(settings, ingestion=workflow) as (client, service):
        await add(client)
        await drain(service)
        task_id = workflow.task_ids[0]
        assert (await client.get(f"/api/tasks/{task_id}")).json()["status"] == "pending"
        await client.get("/api/runs")
        await client.get(f"/api/tasks/{task_id}")
        assert len(workflow.execution_calls) == 1
        task = service.store.task(task_id)
        task["last_checked_at"] = (datetime.now(timezone.utc) - timedelta(seconds=6)).isoformat()
        service.store.save_task(task)
        await client.get("/api/runs")
        assert len(workflow.execution_calls) == 2
        assert service.store.task(task_id)["status"] == "pending"


async def test_callback_while_execution_poll_is_awaiting_preserves_validated_completion(settings):
    workflow = Workflow()
    workflow.execution_status = "failed"
    async with connected(settings, ingestion=workflow) as (client, service):
        await add(client)
        await drain(service)
        task_id = workflow.task_ids[0]

        async def callback_during_poll(_execution_id):
            response = await client.post(
                f"/api/agent/tasks/{task_id}/result", headers=WORKER_HEADERS,
                json={"findings": [{"quote": "No fracture of the right femur.", "page": 1, "anatomy_query": "right femur"}]},
            )
            assert response.status_code == 200, response.text

        workflow.before_execution_return = callback_during_poll
        task = (await client.get(f"/api/tasks/{task_id}")).json()
        assert task["status"] == "completed"
        assert task["result"]["review_required"] is True
        assert "error" not in task
        run = next(run for run in (await client.get("/api/runs")).json()["runs"] if run["id"] == task["run_id"])
        assert run["status"] == "completed"
        assert len(workflow.execution_calls) == 1
