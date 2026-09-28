"""Synthetic automatic relay lifecycle, source verification and wire contracts."""

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from unittest.mock import Mock, patch
from uuid import uuid4

import httpx
import pytest

from bodybrain.cognee_memory import CogneeMemory
from bodybrain.cognee_relay import CogneeRelay, matching_file
from bodybrain.config import Settings
from bodybrain.main import create_app
from bodybrain.relay_protocol import (
    MAX_BYTES, canonical_bytes, is_expired, make_result, make_task,
    parse_result, parse_task, result_filename, task_filename,
)
from bodybrain.service import CleanupFailure


TEXT = "No fracture of the right femur.\nLeft knee pain persists."
QUOTE = "No fracture of the right femur."


class FakeRelay:
    configured = True
    target_identity = {"base_url": "https://example.test", "inbox": "test_jobs", "outbox": "test_results"}

    def __init__(self):
        self.published = {}
        self.responses = {}
        self.cleanup_calls = []
        self.cleanup_error = False
        self.publish_error = False

    async def publish(self, task):
        self.published[task["task_id"]] = deepcopy(task)
        if self.publish_error:
            raise RuntimeError("private synthetic provider detail")
        return {"dataset_id": str(uuid4()), "data_id": str(uuid4()), "name": task_filename(task)}

    async def result(self, task):
        value = self.responses.get(task["task_id"])
        return parse_result(value, task) if value is not None else None

    async def cleanup(self, task):
        self.cleanup_calls.append(task["task_id"])
        if self.cleanup_error:
            raise RuntimeError("private synthetic provider detail")
        self.published.pop(task["task_id"], None)
        self.responses.pop(task["task_id"], None)

    async def health(self, workflow_id=""):
        return {"configured": True, "transport": "cognee_relay", "status": "waiting", "worker_online": False}

    def complete(self, task_id, result, **fields):
        self.responses[task_id] = canonical_bytes(make_result(self.published[task_id], "completed", result, **fields))


@pytest.fixture
async def relay_env(tmp_path):
    settings = replace(Settings(), data_dir=tmp_path, clawmax_transport="cognee_relay", cognee_mode="rest",
                       cognee_url="https://example.test", cognee_api_key="synthetic-key", cognee_token="",
                       cognee_dataset="test_reviewed", clawmax_relay_inbox="test_jobs", clawmax_relay_outbox="test_results",
                       clawmax_url="", clawmax_token="", agent_token="", api_token="", allowed_hosts=("testserver",))
    app = create_app(settings, memory=CogneeMemory("disabled"))
    service = app.state.service
    relay = FakeRelay()
    service.relay = relay
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        yield settings, app, service, relay, client
    await asyncio.gather(*list(service.jobs), return_exceptions=True)


async def add(env, text=TEXT, *, allow_agent=False):
    _, _, service, _, client = env
    response = await client.post("/api/records/text", json={"title": "Synthetic report", "text": text, "allow_agent": allow_agent})
    assert response.status_code == 201
    await asyncio.gather(*list(service.jobs))
    return response.json()


def valid_findings(quote=QUOTE):
    return {"findings": [{"page": 1, "quote": quote, "anatomy_query": "right femur", "concept_id": None}]}


async def test_automatic_dispatch_requires_opt_in_without_dashboard_or_callback_secret(relay_env):
    settings, _, service, relay, _ = relay_env
    first = await add(relay_env)
    assert relay.published == {}
    assert service.store.ingestion_task(first["id"]) is None
    second = await add(relay_env, TEXT + "\nDistinct second source.", allow_agent=True)
    task = service.store.ingestion_task(second["id"])
    assert not settings.clawmax_token and not settings.agent_token
    assert task["status"] == "pending"
    assert task["execution"]["transport"] == "cognee_relay"
    assert task["id"] in relay.published
    assert len(service.store.relay_jobs()) == 1


async def test_automatic_tick_validates_quotes_and_keeps_human_review(relay_env):
    _, _, service, relay, _ = relay_env
    record = await add(relay_env, allow_agent=True)
    task = service.store.ingestion_task(record["id"])
    relay.complete(task["id"], valid_findings(), execution={"agent_id": "bodybrain-ingestion", "provider": "openai-compatible"})
    await service.relay_tick()
    updated = service.store.get(record["id"])
    completed = service.store.task(task["id"])
    assert completed["status"] == "completed"
    assert completed["worker_execution"]["agent_id"] == "bodybrain-ingestion"
    assert updated["status"] == "pending_review" and updated["memory_status"] == "not_indexed"
    assert updated["extraction_mode"] == "clawmax_agent"
    assert all(not finding["approved"] for finding in updated["findings"])
    assert any(finding["quote"] == QUOTE for finding in updated["findings"])
    assert task["id"] in relay.cleanup_calls
    tombstone = service.store.relay_jobs()[0]["task"]
    assert set(tombstone) == {"task_id", "digest", "expires_at"}
    assert TEXT not in json.dumps(tombstone)


@pytest.mark.parametrize("quote", ["A fracture of the right femur.", "fracture of the right femur."])
async def test_invented_or_negation_stripped_quote_rejected(relay_env, quote):
    _, _, service, relay, _ = relay_env
    record = await add(relay_env, allow_agent=True)
    before = deepcopy(service.store.get(record["id"])["findings"])
    task = service.store.ingestion_task(record["id"])
    relay.complete(task["id"], valid_findings(quote))
    await service.relay_tick()
    assert service.store.task(task["id"])["status"] == "failed"
    assert service.store.get(record["id"])["findings"] == before
    assert service.store.get(record["id"])["status"] == "pending_review"


async def test_expired_task_cannot_apply_even_valid_result(relay_env):
    _, _, service, relay, _ = relay_env
    record = await add(relay_env, allow_agent=True)
    task = service.store.ingestion_task(record["id"])
    relay.complete(task["id"], valid_findings())
    with patch("bodybrain.service.is_expired", return_value=True):
        await service.relay_tick()
    assert service.store.task(task["id"])["status"] == "failed"
    assert service.store.get(record["id"])["extraction_mode"] == "anatomical_mentions"


async def test_expiry_while_waiting_for_source_lock_cannot_apply_result(relay_env):
    _, _, service, relay, _ = relay_env
    record = await add(relay_env, allow_agent=True)
    task = service.store.ingestion_task(record["id"])
    relay.complete(task["id"], valid_findings())
    fetched = asyncio.Event()
    original_result = relay.result
    async def gated_result(envelope):
        value = await original_result(envelope)
        fetched.set()
        return value
    relay.result = gated_result
    expired = False
    with patch("bodybrain.main.is_expired", side_effect=lambda envelope: expired):
        async with service.lock_records(record["id"]):
            collection = asyncio.create_task(service.refresh_task(task["id"]))
            await asyncio.wait_for(fetched.wait(), timeout=1)
            await asyncio.sleep(0)
            assert not collection.done()
            expired = True
        await asyncio.wait_for(collection, timeout=1)
    assert service.store.task(task["id"])["status"] == "failed"
    assert service.store.get(record["id"])["extraction_mode"] == "anatomical_mentions"


async def test_approval_freezes_findings_against_pending_agent(relay_env):
    _, _, service, relay, client = relay_env
    record = await add(relay_env, allow_agent=True)
    task = service.store.ingestion_task(record["id"])
    approval = await client.post(f"/api/records/{record['id']}/approve", json={})
    assert approval.status_code == 200
    reviewed = service.store.get(record["id"])
    relay.complete(task["id"], valid_findings())
    await service.relay_tick()
    after = service.store.get(record["id"])
    assert after["status"] == "approved"
    assert after["findings"] == reviewed["findings"]
    assert service.store.task(task["id"])["status"] == "failed"


async def test_deleted_record_and_late_result_cannot_be_restored(relay_env):
    _, _, service, relay, _ = relay_env
    record = await add(relay_env, allow_agent=True)
    task = service.store.ingestion_task(record["id"])
    envelope = deepcopy(relay.published[task["id"]])
    await service.delete_record(record["id"])
    assert service.store.get(record["id"]) is None
    assert service.store.task(task["id"]) is None
    assert not (service.source_dir / record["id"]).exists()
    relay.responses[task["id"]] = canonical_bytes(make_result(envelope, "completed", valid_findings()))
    await service.relay_tick()
    assert service.store.get(record["id"]) is None and service.store.task(task["id"]) is None
    assert task["id"] not in relay.responses


async def test_deletion_during_result_download_revokes_cached_response(relay_env):
    _, _, service, relay, _ = relay_env
    record = await add(relay_env, allow_agent=True)
    task = service.store.ingestion_task(record["id"])
    relay.complete(task["id"], valid_findings())
    fetched, release = asyncio.Event(), asyncio.Event()
    original_result = relay.result
    async def delayed_result(envelope):
        value = await original_result(envelope)
        fetched.set()
        await release.wait()
        return value
    relay.result = delayed_result
    collection = asyncio.create_task(service.refresh_task(task["id"]))
    await asyncio.wait_for(fetched.wait(), timeout=1)
    await service.delete_record(record["id"])
    release.set()
    assert await asyncio.wait_for(collection, timeout=1) is None
    assert service.store.task(task["id"]) is None and service.store.get(record["id"]) is None
    assert not (service.source_dir / record["id"]).exists()
    assert "payload" not in service.store.relay_jobs()[0]["task"]


async def test_uncertain_publication_is_durable_for_cleanup_without_false_success(relay_env):
    _, _, service, relay, _ = relay_env
    relay.publish_error = True
    record = await add(relay_env, allow_agent=True)
    job = service.store.relay_jobs()[0]
    task_id = job["task"]["task_id"]
    assert service.store.task(task_id)["status"] == "failed"
    assert task_id in relay.published  # Simulates a committed write whose acknowledgement was lost.
    await service.relay_tick()
    assert task_id not in relay.published
    assert "payload" not in service.store.relay_jobs()[0]["task"]
    assert service.store.get(record["id"])["status"] == "pending_review"


async def test_oversized_envelope_fails_durably_without_blocking_retry(relay_env):
    _, _, service, relay, _ = relay_env
    # Exercise the real encoder/size validation with a small test-only limit.
    with patch("bodybrain.relay_protocol.MAX_BYTES", 128):
        record = await add(relay_env, allow_agent=True)
    run = next(run for run in service.store.runs() if run["kind"] == "clawmax_ingestion")
    failed = service.store.task(run["task_id"])
    assert failed["status"] == "failed" and run["status"] == "failed"
    assert failed["execution"]["status"] == "error"
    assert service.store.ingestion_task(record["id"]) is None
    assert service.store.relay_jobs() == [] and relay.published == {}
    assert service.store.get(record["id"])["status"] == "pending_review"
    assert (service.source_dir / record["id"]).read_bytes() == TEXT.encode()
    retry = await service.dispatch("ingestion", record_id=record["id"])
    assert retry["id"] != failed["id"] and retry["status"] == "pending"


async def test_remote_cleanup_failure_retains_hidden_local_source_until_retry(relay_env):
    _, _, service, relay, _ = relay_env
    record = await add(relay_env, allow_agent=True)
    relay.cleanup_error = True
    with pytest.raises(CleanupFailure) as caught:
        await service.delete_record(record["id"])
    assert "private synthetic" not in str(caught.value)
    assert service.store.get(record["id"])["status"] == "deleting"
    assert (service.source_dir / record["id"]).read_bytes() == TEXT.encode()
    assert "payload" in service.store.relay_jobs()[0]["task"]
    relay.cleanup_error = False
    await service.delete_record(record["id"])
    assert service.store.get(record["id"]) is None
    assert not (service.source_dir / record["id"]).exists()
    assert "payload" not in service.store.relay_jobs()[0]["task"]


async def test_persisted_jobs_collect_after_backend_restart(relay_env):
    settings, _, service, relay, _ = relay_env
    record = await add(relay_env, allow_agent=True)
    task = service.store.ingestion_task(record["id"])
    relay.complete(task["id"], valid_findings())
    restarted_app = create_app(settings, memory=CogneeMemory("disabled"))
    restarted = restarted_app.state.service
    restarted.relay = relay
    assert restarted.store.relay_jobs()[0]["task"]["task_id"] == task["id"]
    await restarted.relay_tick()
    assert restarted.store.task(task["id"])["status"] == "completed"
    assert restarted.store.get(record["id"])["status"] == "pending_review"


async def test_restart_recovers_published_job_without_dispatch_acknowledgement(relay_env):
    settings, _, service, relay, _ = relay_env
    record = await add(relay_env, allow_agent=True)
    task = service.store.ingestion_task(record["id"])
    relay.complete(task["id"], valid_findings())
    # Simulate termination during publish: the durable envelope and remote
    # result survived, but the final execution metadata was never committed.
    task.pop("execution")
    service.store.save_task(task)
    restarted = create_app(settings, memory=CogneeMemory("disabled")).state.service
    restarted.relay = relay
    await restarted.relay_tick()
    recovered = restarted.store.task(task["id"])
    assert recovered["status"] == "completed"
    assert recovered["execution"]["transport"] == "cognee_relay"
    assert recovered["execution"]["execution_id"] == task["id"]
    assert restarted.store.get(record["id"])["status"] == "pending_review"


async def test_restart_unacknowledged_job_expires_and_allows_new_attempt(relay_env):
    settings, _, service, relay, _ = relay_env
    record = await add(relay_env, allow_agent=True)
    task = service.store.ingestion_task(record["id"])
    task.pop("execution")
    service.store.save_task(task)
    restarted = create_app(settings, memory=CogneeMemory("disabled")).state.service
    restarted.relay = relay
    with patch("bodybrain.service.is_expired", return_value=True):
        await restarted.relay_tick()
    assert restarted.store.task(task["id"])["status"] == "failed"
    assert "payload" not in restarted.store.relay_jobs()[0]["task"]
    retry = await restarted.dispatch("ingestion", record_id=record["id"])
    assert retry["id"] != task["id"] and retry["status"] == "pending"


async def test_evidence_result_cannot_expand_frozen_source_scope(relay_env):
    _, _, service, relay, client = relay_env
    first = await add(relay_env)
    second = await add(relay_env, "Left shoulder pain persists.")
    for record in (first, second):
        assert (await client.post(f"/api/records/{record['id']}/approve", json={})).status_code == 200
    task = await service.dispatch("evidence", question="What about my femur?", evidence=[{"record_id": first["id"], "page": 1, "quote": QUOTE}])
    assert task["allowed_record_ids"] == [first["id"]]
    assert second["id"] not in json.dumps(relay.published[task["id"]])
    relay.complete(task["id"], {"answer": "Unscoped answer", "citations": [{"record_id": second["id"], "page": 1, "quote": "Left shoulder pain persists."}]})
    await service.relay_tick()
    assert service.store.task(task["id"])["status"] == "failed"


async def test_public_status_does_not_claim_worker_online_from_configuration(relay_env):
    _, _, _, _, client = relay_env
    health = (await client.get("/api/health")).json()["integrations"]["clawmax"]
    assert health["configured"] and health["transport"] == "cognee_relay"
    status = (await client.get("/api/integrations")).json()["clawmax"]["ingestion"]
    assert status["configured"] and status["status"] == "waiting" and not status["worker_online"]


async def test_provider_or_malformed_results_remain_pending_without_source_changes(relay_env):
    _, _, service, relay, _ = relay_env
    record = await add(relay_env, allow_agent=True)
    task = service.store.ingestion_task(record["id"])
    relay.responses[task["id"]] = b'{"schema":"wrong"}'
    await service.relay_tick()
    assert service.store.task(task["id"])["status"] == "pending"
    assert service.store.get(record["id"])["extraction_mode"] == "anatomical_mentions"


async def test_changed_relay_destination_never_applies_or_deletes_original_job(relay_env):
    _, _, service, relay, _ = relay_env
    record = await add(relay_env, allow_agent=True)
    task = service.store.ingestion_task(record["id"])
    relay.complete(task["id"], valid_findings())
    relay.target_identity = {**relay.target_identity, "outbox": "another_outbox"}
    await service.relay_tick()
    assert service.store.task(task["id"])["status"] == "pending"
    with pytest.raises(CleanupFailure):
        await service.delete_record(record["id"])
    assert relay.cleanup_calls == []
    assert (service.source_dir / record["id"]).exists()


def test_protocol_roundtrip_hashes_and_task_bound_filenames():
    task = make_task(str(uuid4()), "ingestion", {"record": {"pages": [{"page": 1, "text": TEXT}]}})
    assert parse_task(canonical_bytes(task)) == task
    result = make_result(task, "completed", valid_findings())
    assert parse_result(canonical_bytes(result), task) == result
    assert task["digest"] in task_filename(task) and task["digest"] in result_filename(task)
    assert not is_expired(task)
    altered = deepcopy(task)
    altered["payload"]["record"]["pages"][0]["text"] = "changed"
    with pytest.raises(ValueError, match="integrity"):
        parse_task(canonical_bytes(altered))


@pytest.mark.parametrize("raw", [b"[]", b"{}", b'{"a":1,"a":2}', b'{"x":NaN}', b"\xff", b"[" * 2000 + b"]" * 2000, b"x" * (MAX_BYTES + 1)])
def test_protocol_rejects_malformed_duplicate_nonfinite_and_oversized_envelopes(raw):
    with pytest.raises(ValueError):
        parse_task(raw)


@pytest.mark.parametrize("field,value", [("schema", "other"), ("kind", []), ("created_at", None), ("expires_at", 1), ("task_id", "../"), ("payload", []), ("digest", "a" * 63)])
def test_protocol_rejects_invalid_types_and_schema(field, value):
    task = make_task(str(uuid4()), "ingestion", {})
    task[field] = value
    with pytest.raises(ValueError):
        parse_task(canonical_bytes(task))


def test_protocol_enforces_lifetime_future_timestamp_and_task_result_binding():
    with pytest.raises(ValueError, match="lifetime"):
        make_task(str(uuid4()), "ingestion", {}, ttl_seconds=3601)
    instant = datetime.now(timezone.utc)
    with patch("bodybrain.relay_protocol.utc_now", return_value=instant - timedelta(minutes=2)):
        expired = make_task(str(uuid4()), "ingestion", {}, ttl_seconds=60)
    assert is_expired(expired)
    task = make_task(str(uuid4()), "ingestion", {})
    future = deepcopy(task)
    future["created_at"] = (instant + timedelta(hours=1)).isoformat()
    future["expires_at"] = (instant + timedelta(hours=1, minutes=1)).isoformat()
    future["digest"] = hashlib.sha256(canonical_bytes({k: v for k, v in future.items() if k != "digest"})).hexdigest()
    with pytest.raises(ValueError, match="future"):
        parse_task(canonical_bytes(future))
    result = make_result(task, "completed", {})
    for field, value in [("task_id", str(uuid4())), ("task_digest", "f" * 64), ("status", []), ("completed_at", None), ("execution", {"input_tokens": True})]:
        invalid = {**result, field: value}
        with pytest.raises(ValueError):
            parse_result(canonical_bytes(invalid), task)


async def test_relay_health_handles_absent_stale_and_malformed_heartbeats(relay_env):
    settings, _, _, _, _ = relay_env
    relay = CogneeRelay(settings)
    relay.files = Mock()
    relay.files.dataset.return_value = None
    assert (await relay.health())["status"] == "waiting"
    relay.files.dataset.return_value = str(uuid4())
    relay.files.list_files.return_value = [{"id": str(uuid4()), "name": "bb_heartbeat_123", "extension": "txt"}]
    for beat in [[], {"schema": "bodybrain.clawmax.heartbeat.v1", "timestamp": None}, {"schema": "bodybrain.clawmax.heartbeat.v1", "timestamp": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}]:
        relay.files.read_file.return_value = canonical_bytes(beat)
        assert not (await relay.health()).get("worker_online", False)
    relay.files.read_file.return_value = canonical_bytes({"schema": "bodybrain.clawmax.heartbeat.v1", "timestamp": datetime.now(timezone.utc).isoformat(), "status": "idle"})
    assert (await relay.health())["worker_online"] is True


async def test_relay_health_reports_incomplete_listing_without_claiming_readiness(relay_env):
    from bodybrain.cognee_transport import CogneeTransportError
    settings, _, _, _, _ = relay_env
    relay = CogneeRelay(settings)
    relay.files = Mock()
    relay.files.dataset.return_value = str(uuid4())
    relay.files.list_files.side_effect = CogneeTransportError("private response", code="ambiguous_response")
    result = await relay.health()
    assert result["status"] == "error"
    assert result["error_code"] == "ambiguous_response"
    assert "pagination" in result["message"]
    assert "private response" not in result["message"]
    assert not result.get("worker_online")


def test_matching_file_rejects_two_provider_names_for_same_logical_identity():
    files = [{"id": str(uuid4()), "name": "task", "extension": "txt"}, {"id": str(uuid4()), "name": "task.txt", "extension": "txt"}]
    with pytest.raises(ValueError, match="Ambiguous"):
        matching_file(files, "task.txt")


def test_relay_config_compares_effective_dataset_names_and_rejects_blanks():
    base = dict(clawmax_transport="cognee_relay", cognee_dataset="reviewed", clawmax_relay_inbox="jobs", clawmax_relay_outbox="results")
    for overrides in [{"cognee_dataset": " jobs "}, {"clawmax_relay_outbox": " jobs "}]:
        with pytest.raises(ValueError, match="separate datasets"):
            replace(Settings(), **{**base, **overrides})
    for field in ("cognee_dataset", "clawmax_relay_inbox", "clawmax_relay_outbox"):
        for value in ("", " \t "):
            with pytest.raises(ValueError, match="non-empty dataset names"):
                replace(Settings(), **{**base, field: value})
