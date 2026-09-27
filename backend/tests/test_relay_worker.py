"""Hosted worker behavior with in-memory Cognee files and fake CLI output."""
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import uuid

import pytest

from bodybrain.relay_protocol import canonical_bytes, make_result, make_task, result_filename, task_filename

WORKER_PATH = Path(__file__).resolve().parents[2] / "integrations/clawmax/relay/worker.py"
spec = importlib.util.spec_from_file_location("bodybrain_test_relay_worker", WORKER_PATH)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)

CONFIG = {"base_url": "https://cognee.example.test", "inbox_dataset": "bb_tasks", "outbox_dataset": "bb_results",
          "model": "lmstudio/gpt-4.1-mini", "agents": {"ingestion": "bodybrain-ingestion", "evidence": "bodybrain-evidence"}}


class Files:
    def __init__(self):
        self.datasets = {"bb_tasks": "inbox", "bb_results": "outbox"}
        self.items = {"inbox": {}, "outbox": {}}
        self.fail_publish = False
        self.deleted = []

    def dataset(self, name, create=False):
        return self.datasets.get(name)

    def list_files(self, dataset_id):
        return [{"id": name, "name": name[:-4], "extension": "txt"} for name in self.items[dataset_id]]

    def read_file(self, dataset_id, data_id):
        return self.items[dataset_id][data_id]

    def put_file(self, dataset_name, name, raw):
        if self.fail_publish:
            raise RuntimeError("private-provider-message API-key sample medical data")
        self.items[self.datasets[dataset_name]][name] = raw

    def delete_file(self, dataset_id, data_id):
        self.deleted.append((dataset_id, data_id))
        del self.items[dataset_id][data_id]


def task(kind="evidence"):
    return make_task(str(uuid.uuid4()), kind, {"records": [], "question": "Synthetic test"})


def fake_runner(calls):
    def run(value, config, session_id):
        calls.append((value["task_id"], session_id))
        result = {"findings": []} if value["kind"] == "ingestion" else {"answer": "No approved evidence provided.", "citations": []}
        return result, {"agent_id": config["agents"][value["kind"]], "session_id": session_id, "provider": "lmstudio", "model": "gpt-4.1-mini", "input_tokens": 20}
    return run


def seed(files, value):
    files.items["inbox"][task_filename(value)] = canonical_bytes(value)


def test_worker_runs_real_runner_interface_once_then_uses_published_result(tmp_path):
    files, calls, value = Files(), [], task()
    seed(files, value)
    instance = worker.Worker(CONFIG, files, tmp_path, runner=fake_runner(calls))
    assert instance.poll_once() == {"processed": 1, "skipped": 0, "errors": 0}
    result = json.loads(files.items["outbox"][result_filename(value)])
    assert result["status"] == "completed"
    assert result["execution"]["model"] == "gpt-4.1-mini"
    assert result["execution"]["agent_id"] == "bodybrain-evidence"
    assert instance.poll_once() == {"processed": 0, "skipped": 1, "errors": 0}
    assert len(calls) == 1
    instance.ledger.close()


def test_upload_failure_and_worker_restart_republish_without_model_call(tmp_path):
    files, calls, value = Files(), [], task("ingestion")
    seed(files, value)
    files.fail_publish = True
    instance = worker.Worker(CONFIG, files, tmp_path, runner=fake_runner(calls))
    assert instance.poll_once()["errors"] == 1
    assert len(calls) == 1
    instance.ledger.close()
    files.fail_publish = False
    resumed = worker.Worker(CONFIG, files, tmp_path, runner=lambda *_: pytest.fail("Must use durable result"))
    assert resumed.poll_once()["processed"] == 1
    assert json.loads(files.items["outbox"][result_filename(value)])["result"] == {"findings": []}
    resumed.ledger.close()


def test_restart_checks_existing_outbox_before_invoke_even_without_local_ledger(tmp_path):
    files, value = Files(), task()
    seed(files, value)
    files.items["outbox"][result_filename(value)] = canonical_bytes(make_result(value, "completed", result={"answer": "Existing", "citations": []}))
    instance = worker.Worker(CONFIG, files, tmp_path, runner=lambda *_: pytest.fail("Published work must not repeat"))
    assert instance.poll_once()["skipped"] == 1
    instance.ledger.close()


def test_expired_task_publishes_controlled_failure_without_running_agent(tmp_path):
    files, value = Files(), task()
    value["created_at"] = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    value["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    value["digest"] = hashlib.sha256(canonical_bytes({k: v for k, v in value.items() if k != "digest"})).hexdigest()
    seed(files, value)
    instance = worker.Worker(CONFIG, files, tmp_path, runner=lambda *_: pytest.fail("Expired task"))
    assert instance.poll_once()["processed"] == 1
    result = json.loads(files.items["outbox"][result_filename(value)])
    assert result["status"] == "failed" and result["result"] is None
    assert "expired" in result["error"]
    instance.ledger.close()


def test_malformed_or_misnamed_tasks_do_not_invoke_or_disclose_data(tmp_path):
    files, calls, value = Files(), [], task()
    seed(files, value)
    value["payload"]["question"] = "Tampered private data"
    files.items["inbox"][task_filename(value)] = canonical_bytes(value)
    files.items["inbox"]["unrelated.txt"] = b"unrelated record"
    instance = worker.Worker(CONFIG, files, tmp_path, runner=fake_runner(calls))
    assert instance.poll_once() == {"processed": 0, "skipped": 0, "errors": 1}
    assert calls == [] and files.items["outbox"] == {}
    instance.ledger.close()


def test_unexpected_execution_error_is_sanitized(tmp_path):
    files, value = Files(), task()
    seed(files, value)
    def fail(*_):
        raise RuntimeError("secret-key private record text")
    instance = worker.Worker(CONFIG, files, tmp_path, runner=fail)
    assert instance.poll_once()["processed"] == 1
    raw = files.items["outbox"][result_filename(value)]
    assert b"secret-key" not in raw and b"private record" not in raw
    assert json.loads(raw)["status"] == "failed"
    instance.ledger.close()


def test_interrupted_execution_is_at_least_once_with_fresh_session(tmp_path):
    files, calls, value = Files(), [], task()
    seed(files, value)
    instance = worker.Worker(CONFIG, files, tmp_path, runner=fake_runner(calls))
    instance.ledger.start(value, "interrupted-session")
    assert instance.poll_once()["processed"] == 1
    assert len(calls) == 1 and calls[0][1] != "interrupted-session"
    assert instance.ledger.get(value["task_id"])["attempts"] == 2
    instance.ledger.close()


def test_deleted_task_is_not_republished_after_agent_returns(tmp_path):
    files, value = Files(), task()
    seed(files, value)
    def run(*_):
        del files.items["inbox"][task_filename(value)]
        return {"answer": "PRIVATE_RESULT_AFTER_REVOCATION", "citations": []}, {}
    instance = worker.Worker(CONFIG, files, tmp_path, runner=run)
    assert instance.poll_once() == {"processed": 0, "skipped": 1, "errors": 0}
    assert files.items["outbox"] == {}
    row = instance.ledger.get(value["task_id"])
    assert row["state"] == "retired" and row["result"] is None
    instance.ledger.close()


def test_missing_completed_task_scrubs_retry_bytes_but_keeps_tombstone(tmp_path):
    files, value = Files(), task()
    seed(files, value)
    marker = "PRIVATE_RESULT_TO_REMOVE_" * 40
    instance = worker.Worker(CONFIG, files, tmp_path, runner=lambda *_: ({"answer": marker, "citations": []}, {}))
    assert instance.poll_once()["processed"] == 1
    assert marker.encode() in (tmp_path / "ledger.sqlite3").read_bytes()
    files.items["inbox"].clear()
    files.items["outbox"].clear()
    assert instance.poll_once()["processed"] == 0
    assert marker.encode() not in (tmp_path / "ledger.sqlite3").read_bytes()
    row = instance.ledger.get(value["task_id"])
    assert row["state"] == "retired" and row["result"] is None
    seed(files, value)
    instance.runner = lambda *_: pytest.fail("Revoked task must not resume")
    assert instance.poll_once()["skipped"] == 1
    assert files.items["outbox"] == {}
    instance.ledger.close()


@pytest.mark.parametrize("wrapped", [False, True])
def test_parse_actual_cli_payload_shapes_and_allowlisted_metadata(wrapped):
    body = {"payloads": [{"text": '{"answer":"Synthetic","citations":[]}'}],
            "meta": {"durationMs": 21, "agentMeta": {"provider": "lmstudio", "model": "gpt-4.1-mini", "usage": {"input": 3, "output": 4}, "private": "never-export"}}}
    envelope = {"status": "ok", "result": body} if wrapped else body
    result, meta = worker.parse_cli_output(b"startup notice\n" + json.dumps(envelope).encode(), "evidence")
    assert result == {"answer": "Synthetic", "citations": []}
    assert meta == {"provider": "lmstudio", "model": "gpt-4.1-mini", "input_tokens": 3, "output_tokens": 4, "duration_ms": 21}


@pytest.mark.parametrize("raw", [
    b'{"answer":"raw prose is not a CLI result","citations":[]}',
    b'{"payloads":[{"isError":true,"text":"failure"}]}',
    b'{"payloads":[{"text":"{\\"answer\\":\\"ok\\",\\"citations\\":[]}"},{"text":"extra"}]}',
    b'{"status":"error","result":{"payloads":[{"text":"{}"}]}}',
    b'{"payloads":[{"text":"{\\"answer\\":\\"ok\\",\\"citations\\":[],\\"approved\\":true}"}]}',
])
def test_cli_error_ambiguous_and_nonprotocol_results_fail_closed(raw):
    with pytest.raises(worker.WorkerError):
        worker.parse_cli_output(raw, "evidence")


def test_agent_invocation_uses_hosted_cli_and_omits_partner_credentials(monkeypatch):
    value = task()
    monkeypatch.setenv("COGNEE_API_KEY", "do-not-pass")
    monkeypatch.setenv("CLAWMAX_SECRET_BROKER_TOKEN", "do-not-pass")
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-pass")
    captured = {}
    def fake(args, **kwargs):
        captured.update(args=args, **kwargs)
        return b'{"payloads":[{"text":"{\\"answer\\":\\"Synthetic\\",\\"citations\\":[]}"}],"meta":{"agentMeta":{"provider":"lmstudio","model":"gpt-4.1-mini"}}}'
    monkeypatch.setattr(worker, "run_bounded", fake)
    result, execution = worker.invoke_agent(value, CONFIG, "bb-probe")
    assert captured["args"][:3] == ["openclaw", "agent", "--local"]
    assert captured["args"][captured["args"].index("--agent") + 1] == "bodybrain-evidence"
    assert captured["args"][captured["args"].index("--model") + 1] == "lmstudio/gpt-4.1-mini"
    assert not set(captured["env"]) & {"COGNEE_API_KEY", "OPENAI_API_KEY", "CLAWMAX_SECRET_BROKER_TOKEN"}
    assert "Do not call any tools" in captured["args"][captured["args"].index("--message") + 1]
    assert execution["session_id"] == "bb-probe"
    assert result["answer"] == "Synthetic"


def test_large_prompt_uses_private_message_file_then_removes_it(monkeypatch):
    value = task()
    value["payload"]["records"] = ["synthetic" * 10000]
    captured = {}
    def fake(args, **kwargs):
        path = Path(args[args.index("--message-file") + 1])
        captured["path"] = path
        assert path.stat().st_mode & 0o077 == 0
        assert "synthetic" in path.read_text()
        return b'{"payloads":[{"text":"{\\"answer\\":\\"Synthetic\\",\\"citations\\":[]}"}]}'
    monkeypatch.setattr(worker, "run_bounded", fake)
    worker.invoke_agent(value, CONFIG, "bb-probe")
    assert not captured["path"].exists()


def test_process_timeout_and_output_limit_are_bounded():
    started = time.monotonic()
    with pytest.raises(worker.WorkerError, match="timeout"):
        worker.run_bounded([sys.executable, "-c", "import time; time.sleep(20)"], timeout=0.1)
    assert time.monotonic() - started < 4
    with pytest.raises(worker.WorkerError, match="output limit"):
        worker.run_bounded([sys.executable, "-c", "print('x'*100000)"], output_limit=100)


def test_second_worker_cannot_acquire_same_state_lock(tmp_path):
    with worker.worker_lock(tmp_path):
        with pytest.raises(worker.WorkerError, match="already owns"):
            with worker.worker_lock(tmp_path):
                pytest.fail("Second worker acquired lock")


@pytest.mark.parametrize("name", ["worker.lock", "ledger.sqlite3", "ledger.sqlite3-journal", "ledger.sqlite3-wal", "ledger.sqlite3-shm"])
def test_worker_does_not_follow_state_file_symlinks(tmp_path, name):
    target = tmp_path / "unrelated"
    target.write_text("preserve this file")
    (tmp_path / name).symlink_to(target)
    with pytest.raises(worker.WorkerError):
        with worker.worker_lock(tmp_path):
            worker.Worker(CONFIG, Files(), tmp_path)
    assert target.read_text() == "preserve this file"


def test_heartbeat_retention_deletes_only_this_workers_own_files(tmp_path, monkeypatch):
    files = Files()
    instance = worker.Worker(CONFIG, files, tmp_path, runner=lambda *_: pytest.fail("Heartbeat cannot invoke model"))
    epoch = iter(range(1000, 1007))
    monkeypatch.setattr(worker.time, "time_ns", lambda: next(epoch) * 1_000_000)
    files.items["outbox"]["bb_heartbeat_999.txt"] = canonical_bytes({"schema": "bodybrain.clawmax.heartbeat.v1", "worker_id": "someone-else"})
    for _ in range(5):
        instance.heartbeat()
    assert len(instance.ledger.heartbeat_names()) == 3
    assert "bb_heartbeat_999.txt" in files.items["outbox"]
    assert files.deleted == [("outbox", "bb_heartbeat_1000.txt"), ("outbox", "bb_heartbeat_1001.txt")]
    instance.ledger.close()
