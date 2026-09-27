"""Record versions and deletions against isolated storage and in-process providers."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace

import httpx
import pytest

from bodybrain.config import Settings
from bodybrain.main import create_app


TEXT = "No fracture of the right femur."
CORRECTION = "The left kidney appears normal."
AGENT_HEADERS = {"Authorization": "Bearer lifecycle-worker"}


class Memory:
    def __init__(self, *, configured=True):
        self.configured = configured
        self.target_identity = {"mode": "rest", "dataset": "synthetic-test", "base_url": "https://memory.invalid"}
        self.documents = {}
        self.operations = []
        self.fail_delete = False
        self.fail_index = False
        self.block_index = False
        self.block_recall = False
        self.block_delete = False
        self.index_entered = asyncio.Event()
        self.index_release = asyncio.Event()
        self.recall_entered = asyncio.Event()
        self.recall_release = asyncio.Event()
        self.delete_entered = asyncio.Event()
        self.delete_release = asyncio.Event()

    async def status(self, probe=False):
        return {"configured": self.configured, "status": "ready"}

    async def remember(self, document_id, text, metadata):
        self.index_entered.set()
        if self.block_index:
            await self.index_release.wait()
        self.documents[document_id] = text
        self.operations.append(("remember", document_id))
        if self.fail_index:
            raise RuntimeError("Private provider failure must never appear in responses")
        return {"status": "completed"}

    async def forget(self, document_id):
        self.delete_entered.set()
        if self.block_delete:
            await self.delete_release.wait()
        if self.fail_delete:
            raise RuntimeError("Private provider failure must never appear in responses")
        existed = self.documents.pop(document_id, None) is not None
        self.operations.append(("forget", document_id))
        return {"status": "deleted" if existed else "not_found"}

    async def recall(self, question, limit=8):
        ids = list(self.documents)
        self.recall_entered.set()
        if self.block_recall:
            await self.recall_release.wait()
        return {"document_ids": ids}


class Workflow:
    configured = True

    def __init__(self):
        self.block_trigger = False
        self.block_poll = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.task_id = None

    async def trigger_task(self, task_id):
        self.task_id = task_id
        self.entered.set()
        if self.block_trigger:
            await self.release.wait()
        return {"status": "submitted", "execution_id": "synthetic-execution"}

    async def execution(self, execution_id):
        self.entered.set()
        if self.block_poll:
            await self.release.wait()
        return {"status": "running"}


@pytest.fixture
def settings(tmp_path):
    return replace(Settings(), data_dir=tmp_path, cognee_mode="disabled", cognee_url="", cognee_api_key="", cognee_token="", clawmax_url="", clawmax_token="", api_token="", agent_token="lifecycle-worker")


@asynccontextmanager
async def connected(settings, memory=None, workflow=None):
    app = create_app(settings, memory=memory or Memory(), clawmax_ingest=workflow, clawmax_evidence=workflow)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            yield client, app.state.service


async def add(client, text=TEXT, **fields):
    response = await client.post("/api/records/text", json={"title": "Synthetic source", "text": text, **fields})
    assert response.status_code == 201, response.text
    return response.json()


async def drain(service):
    await asyncio.wait_for(service.queue.join(), 3)


async def approve(client, record):
    response = await client.post(f"/api/records/{record['id']}/approve", json={})
    assert response.status_code == 200, response.text
    return response.json()


async def revision(client, record, text=CORRECTION):
    response = await client.post(f"/api/records/{record['id']}/revisions", json={"title": "Corrected source", "text": text, "record_type": "correction", "event_date": "2026-08-01"})
    assert response.status_code == 201, response.text
    return response.json()


async def test_delete_pending_removes_source_record_runs_tasks_without_memory_call(settings):
    memory = Memory()
    async with connected(settings, memory) as (client, service):
        record = await add(client)
        service.store.save_task({"id": "synthetic-ingestion", "kind": "ingestion", "record_id": record["id"], "status": "pending"})
        response = await client.delete(f"/api/records/{record['id']}")
        assert response.json() == {"status": "deleted", "record_id": record["id"]}
        assert memory.operations == []
        assert not (service.source_dir / record["id"]).exists()
        assert service.store.get(record["id"]) is None
        assert service.store.task("synthetic-ingestion") is None
        assert service.store.runs() == []
        assert (await client.get(f"/api/records/{record['id']}/source")).status_code == 404
        assert (await client.post("/api/agent/tasks/synthetic-ingestion/result", json={"findings": []}, headers=AGENT_HEADERS)).status_code == 404
        assert (await client.delete(f"/api/records/{record['id']}")).status_code == 404
        # Re-importing after deletion creates a genuinely new source identity.
        assert (await add(client))["id"] != record["id"]


async def test_indexed_delete_forgets_exact_source_and_purges_completed_evidence(settings):
    memory, workflow = Memory(), Workflow()
    async with connected(settings, memory, workflow) as (client, service):
        record = await add(client)
        other = await add(client, CORRECTION)
        await approve(client, record)
        await approve(client, other)
        await drain(service)
        chat = (await client.post("/api/chat", json={"question": "femur", "allow_agent": True})).json()
        task_id = chat["agent_task_id"]
        result = await client.post(f"/api/agent/tasks/{task_id}/result", headers=AGENT_HEADERS, json={"answer": "Source excerpt", "citations": [{"record_id": record["id"], "page": 1, "quote": TEXT}]})
        assert result.status_code == 200
        stale_task = service.store.task(task_id)
        stale_run = next(run for run in service.store.runs() if run.get("task_id") == task_id)
        assert (await client.delete(f"/api/records/{record['id']}")).status_code == 200
        assert set(memory.documents) == {other["id"]}
        assert memory.operations.count(("forget", record["id"])) == 1
        assert (await client.get(f"/api/tasks/{task_id}")).status_code == 404
        assert (await client.get(f"/api/agent/tasks/{task_id}", headers=AGENT_HEADERS)).status_code == 404
        assert service.store.save_task(stale_task) is False
        assert service.store.save_run(stale_run) is False
        assert (await client.post("/api/chat", json={"question": "femur"})).json()["citations"] == []
        assert [r["id"] for r in (await client.get("/api/timeline")).json()["events"]] == [other["id"]]


async def test_failed_cleanup_is_durable_hidden_retryable_and_restart_never_uploads(settings):
    memory = Memory()
    async with connected(settings, memory) as (client, service):
        record = await add(client)
        await approve(client, record)
        await drain(service)
        memory.fail_delete = True
        failed = await client.delete(f"/api/records/{record['id']}")
        assert failed.status_code == 503
        assert "Private provider" not in failed.text
        retained = service.store.get(record["id"])
        assert retained["status"] == "deleting" and retained["deletion_error"]
        assert (service.source_dir / record["id"]).exists()
        assert (await client.get("/api/summary")).json()["citations"] == []
        assert (await client.get(f"/api/records/{record['id']}/source")).status_code == 409
    operations = list(memory.operations)
    async with connected(settings, memory) as (client, service):
        await drain(service)
        assert memory.operations == operations
        assert service.store.get(record["id"])["status"] == "deleting"
        memory.fail_delete = False
        assert (await client.delete(f"/api/records/{record['id']}")).status_code == 200
        assert service.store.get(record["id"]) is None


async def test_partial_provider_write_and_target_change_do_not_claim_cleanup(settings):
    memory = Memory()
    memory.fail_index = True
    async with connected(settings, memory) as (client, service):
        record = await add(client)
        await approve(client, record)
        await drain(service)
        assert service.store.get(record["id"])["memory_status"] == "failed"
        original_target = dict(memory.target_identity)
        memory.target_identity = {**original_target, "dataset": "different-dataset"}
        response = await client.delete(f"/api/records/{record['id']}")
        assert response.status_code == 503 and "configuration" in response.text
        assert record["id"] in memory.documents
        assert ("forget", record["id"]) not in memory.operations
        memory.target_identity = original_target
        assert (await client.delete(f"/api/records/{record['id']}")).status_code == 200
        assert record["id"] not in memory.documents


async def test_legacy_indexed_record_uses_current_destination_for_scoped_cleanup(settings):
    memory = Memory()
    async with connected(settings, memory) as (client, service):
        record = await add(client)
        await approve(client, record)
        await drain(service)
        service.store.update(record["id"], memory_target=None, remote_memory_present=None)
        assert (await client.delete(f"/api/records/{record['id']}")).status_code == 200
        assert ("forget", record["id"]) in memory.operations


async def test_revision_has_unique_source_and_promotes_only_after_remote_retirement(settings):
    memory = Memory()
    async with connected(settings, memory) as (client, service):
        original = await add(client)
        await approve(client, original)
        await drain(service)
        before = service.store.get(original["id"])
        draft = await revision(client, original)
        assert draft["id"] != original["id"] and draft["digest"] != original["digest"]
        assert draft["revision_number"] == 2 and draft["revises_record_id"] == original["id"]
        assert draft["source_kind"] == "corrected_transcription"
        assert service.store.get(original["id"]) == before
        assert draft["status"] == "pending_review" and not any(f["approved"] for f in draft["findings"])
        assert (await client.get(f"/api/records/{draft['id']}/source")).text == CORRECTION
        assert (await client.post("/api/chat", json={"question": "kidney"})).json()["citations"] == []
        memory.fail_delete = True
        response = await client.post(f"/api/records/{draft['id']}/approve", json={})
        assert response.status_code == 503
        assert service.store.get(draft["id"])["status"] == "pending_review"
        assert service.store.get(original["id"])["status"] == "approved"
        assert not any(f["approved"] for f in service.store.get(draft["id"])["findings"])
        memory.fail_delete = False
        await approve(client, draft)
        await drain(service)
        old, new = service.store.get(original["id"]), service.store.get(draft["id"])
        assert old["status"] == "superseded" and old["superseded_by"] == draft["id"]
        assert old["text"] == before["text"] and old["findings"] == before["findings"]
        assert new["status"] == "approved"
        assert memory.operations.index(("forget", original["id"])) < memory.operations.index(("remember", draft["id"]))
        assert (await client.get(f"/api/records/{original['id']}/source")).text == TEXT
        assert [r["id"] for r in (await client.get("/api/timeline")).json()["events"]] == [draft["id"]]
        assert (await client.post("/api/chat", json={"question": "femur"})).json()["citations"] == []
        assert any(run["record_id"] == original["id"] for run in service.store.runs())
        assert (await client.post(f"/api/records/{original['id']}/approve", json={})).status_code == 409
        assert (await client.post(f"/api/records/{original['id']}/index")).status_code == 409


async def test_revision_re_review_identical_text_and_single_draft_constraint(settings):
    memory = Memory(configured=False)
    async with connected(settings, memory) as (client, service):
        record = await add(client)
        body = {"title": record["title"], "text": TEXT}
        url = f"/api/records/{record['id']}/revisions"
        assert (await client.post(url, json=body)).status_code == 409
        await approve(client, record)
        responses = await asyncio.gather(client.post(url, json=body), client.post(url, json=body))
        assert sorted(response.status_code for response in responses) == [201, 409]
        draft = next(response.json() for response in responses if response.status_code == 201)
        assert draft["id"] != record["id"]
        await approve(client, draft)
        third = await revision(client, draft, TEXT)
        assert third["revision_number"] == 3
        assert (await client.post(url, json=body)).status_code == 409
        assert len(list(service.source_dir.iterdir())) == 3  # Failed draft leaves no orphan source.
        assert memory.operations == []


async def test_delete_waits_for_index_then_forgets_without_resurrection(settings):
    memory = Memory()
    memory.block_index = True
    async with connected(settings, memory) as (client, service):
        record = await add(client)
        await approve(client, record)
        await asyncio.wait_for(memory.index_entered.wait(), 3)
        deletion = asyncio.create_task(client.delete(f"/api/records/{record['id']}"))
        for _ in range(100):
            if service.store.get(record["id"])["status"] == "deleting":
                break
            await asyncio.sleep(0.001)
        assert service.store.get(record["id"])["status"] == "deleting"
        assert not deletion.done()
        assert (await client.get("/api/summary")).json()["citations"] == []
        memory.index_release.set()
        assert (await asyncio.wait_for(deletion, 3)).status_code == 200
        await drain(service)
        assert memory.operations == [("remember", record["id"]), ("forget", record["id"])]
        assert service.store.runs() == [] and not memory.documents
        # A delayed queue entry cannot recreate runs or terminate the worker.
        await service.queue.put(record["id"])
        await service.queue.put("missing-synthetic-record")
        await drain(service)
        other = await add(client, CORRECTION)
        await approve(client, other)
        await drain(service)
        assert service.store.get(other["id"])["memory_status"] == "indexed"


async def test_chat_awaiting_recall_cannot_return_deleted_quotes(settings):
    memory = Memory()
    async with connected(settings, memory) as (client, service):
        record = await add(client)
        await approve(client, record)
        await drain(service)
        memory.block_recall = True
        question = asyncio.create_task(client.post("/api/chat", json={"question": "femur"}))
        await asyncio.wait_for(memory.recall_entered.wait(), 3)
        assert (await client.delete(f"/api/records/{record['id']}")).status_code == 200
        memory.recall_release.set()
        response = (await asyncio.wait_for(question, 3)).json()
        assert response["citations"] == [] and TEXT not in response["answer"]


async def test_chat_awaiting_workflow_cannot_resurrect_deleted_snapshot(settings):
    memory, workflow = Memory(), Workflow()
    workflow.block_trigger = True
    async with connected(settings, memory, workflow) as (client, service):
        record = await add(client)
        await approve(client, record)
        await drain(service)
        question = asyncio.create_task(client.post("/api/chat", json={"question": "femur", "allow_agent": True}))
        await asyncio.wait_for(workflow.entered.wait(), 3)
        assert service.store.task(workflow.task_id)
        assert (await client.delete(f"/api/records/{record['id']}")).status_code == 200
        workflow.release.set()
        response = (await asyncio.wait_for(question, 3)).json()
        assert response["citations"] == [] and response["agent_task_id"] is None
        assert service.store.task(workflow.task_id) is None and service.store.runs() == []


async def test_poll_awaiting_provider_cannot_resurrect_deleted_snapshot(settings):
    memory, workflow = Memory(), Workflow()
    async with connected(settings, memory, workflow) as (client, service):
        record = await add(client)
        task = (await client.post(f"/api/records/{record['id']}/process")).json()
        workflow.block_poll = True
        workflow.entered.clear()
        polling = asyncio.create_task(client.get(f"/api/tasks/{task['id']}"))
        await asyncio.wait_for(workflow.entered.wait(), 3)
        assert (await client.delete(f"/api/records/{record['id']}")).status_code == 200
        workflow.release.set()
        assert (await asyncio.wait_for(polling, 3)).status_code == 404
        assert service.store.task(task["id"]) is None and service.store.runs() == []


async def test_parent_deletion_requires_resolving_pending_revision(settings):
    async with connected(settings, Memory(configured=False)) as (client, service):
        original = await add(client)
        await approve(client, original)
        draft = await revision(client, original)
        blocked = await client.delete(f"/api/records/{original['id']}")
        assert blocked.status_code == 409 and "pending revision" in blocked.text
        assert service.store.get(original["id"])["status"] == "approved"
        assert (await client.delete(f"/api/records/{draft['id']}")).status_code == 200
        assert (await client.delete(f"/api/records/{original['id']}")).status_code == 200
        assert service.store.records() == []


async def test_source_cleanup_failure_can_retry_after_remote_retirement(settings, monkeypatch):
    from pathlib import Path
    memory = Memory()
    async with connected(settings, memory) as (client, service):
        record = await add(client)
        await approve(client, record)
        await drain(service)
        source = service.source_dir / record["id"]
        original_unlink = Path.unlink
        def failed_unlink(path, *args, **kwargs):
            if path == source:
                raise OSError("Private filesystem information")
            return original_unlink(path, *args, **kwargs)
        monkeypatch.setattr(Path, "unlink", failed_unlink)
        failed = await client.delete(f"/api/records/{record['id']}")
        assert failed.status_code == 503 and "Private filesystem" not in failed.text
        assert service.store.get(record["id"])["status"] == "deleting"
        assert service.store.get(record["id"])["remote_memory_present"] is False
        monkeypatch.setattr(Path, "unlink", original_unlink)
        assert (await client.delete(f"/api/records/{record['id']}")).status_code == 200
        assert memory.operations.count(("forget", record["id"])) == 1


async def test_revision_is_not_visible_until_blocked_retirement_completes(settings):
    memory = Memory()
    async with connected(settings, memory) as (client, service):
        original = await add(client)
        await approve(client, original)
        await drain(service)
        draft = await revision(client, original)
        memory.block_delete = True
        approving = asyncio.create_task(client.post(f"/api/records/{draft['id']}/approve", json={}))
        await asyncio.wait_for(memory.delete_entered.wait(), 3)
        assert service.store.get(original["id"])["status"] == "approved"
        assert service.store.get(draft["id"])["status"] == "pending_review"
        assert [c["record_id"] for c in (await client.get("/api/summary")).json()["citations"]] == [original["id"]]
        assert ("remember", draft["id"]) not in memory.operations
        memory.delete_release.set()
        assert (await asyncio.wait_for(approving, 3)).status_code == 200
        await drain(service)
        assert [c["record_id"] for c in (await client.get("/api/summary")).json()["citations"]] == [draft["id"]]


async def test_legacy_pending_upload_obligation_survives_disabled_restart(settings):
    import json
    memory = Memory()
    async with connected(settings, memory) as (client, service):
        record = await add(client)
        await approve(client, record)
        await drain(service)
        legacy = service.store.get(record["id"])
        legacy.pop("remote_memory_present")
        legacy.pop("memory_target")
        legacy["memory_status"] = "pending"
        with service.store.connect() as db:
            db.execute("UPDATE records SET memory_status='pending',data=? WHERE id=?", (json.dumps(legacy), record["id"]))
    memory.configured = False
    memory.fail_delete = True
    async with connected(settings, memory) as (client, service):
        current = service.store.get(record["id"])
        assert current["memory_status"] == "unconfigured"
        assert current["remote_memory_present"] is True
        assert (await client.delete(f"/api/records/{record['id']}")).status_code == 503
        assert record["id"] in memory.documents
        memory.configured = True
        memory.fail_delete = False
        assert (await client.delete(f"/api/records/{record['id']}")).status_code == 200
        assert record["id"] not in memory.documents


async def test_draft_delete_cannot_interrupt_parent_retirement_and_promotion(settings):
    memory = Memory()
    async with connected(settings, memory) as (client, service):
        original = await add(client)
        await approve(client, original)
        await drain(service)
        draft = await revision(client, original)
        memory.block_delete = True
        approving = asyncio.create_task(client.post(f"/api/records/{draft['id']}/approve", json={}))
        await asyncio.wait_for(memory.delete_entered.wait(), 3)
        deleting = asyncio.create_task(client.delete(f"/api/records/{draft['id']}"))
        await asyncio.sleep(0.01)
        assert service.store.get(draft["id"])["status"] == "pending_review"
        assert not deleting.done()
        memory.delete_release.set()
        approved, deleted = await asyncio.wait_for(asyncio.gather(approving, deleting), 3)
        assert approved.status_code == 200 and deleted.status_code == 200
        await drain(service)
        assert service.store.get(original["id"])["status"] == "superseded"
        assert service.store.get(draft["id"]) is None
        assert memory.documents == {}
