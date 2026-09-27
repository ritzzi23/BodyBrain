"""Storage privacy and durable review-state regressions; synthetic temporary data only."""

import os
from pathlib import Path
import sqlite3
import stat
from types import SimpleNamespace

import pytest

from bodybrain.db import StateConflict, Store, now, write_private_source
from bodybrain.service import Service


def record(record_id="record-one"):
    return {
        "id": record_id, "digest": record_id, "status": "pending_review",
        "memory_status": "not_indexed", "created_at": now(), "findings": [],
    }


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes are not Windows ACLs")
def test_storage_database_is_private_before_sqlite_opens_it(tmp_path, monkeypatch):
    path = tmp_path / "data" / "records.sqlite3"
    actual_connect = sqlite3.connect
    observed = []

    def inspect_connect(database, *args, **kwargs):
        observed.append((mode(Path(database).parent), mode(Path(database))))
        return actual_connect(database, *args, **kwargs)

    monkeypatch.setattr("bodybrain.db.sqlite3.connect", inspect_connect)
    previous = os.umask(0)
    try:
        store = Store(path)
        store.insert(record())
    finally:
        os.umask(previous)
    assert observed and all(item == (0o700, 0o600) for item in observed)
    assert mode(path.parent) == 0o700 and mode(path) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes are not Windows ACLs")
def test_storage_startup_repairs_existing_database_and_live_sidecars(tmp_path):
    path = tmp_path / "records.sqlite3"
    Store(path)
    # Keep a real WAL connection open so the sidecars survive initialization.
    keeper = sqlite3.connect(path)
    try:
        keeper.execute("PRAGMA journal_mode=WAL")
        keeper.execute("CREATE TABLE retained_connection (value TEXT)")
        keeper.commit()
        protected = [path, Path(str(path) + "-wal"), Path(str(path) + "-shm")]
        assert all(item.exists() for item in protected)
        tmp_path.chmod(0o755)
        for item in protected:
            item.chmod(0o644)
        Store(path)
        assert mode(tmp_path) == 0o700
        assert all(mode(item) == 0o600 for item in protected)
    finally:
        keeper.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes are not Windows ACLs")
def test_storage_source_is_private_before_first_write_and_cannot_overwrite(tmp_path, monkeypatch):
    source_path = tmp_path / "source"
    actual_fdopen = os.fdopen
    observed = []

    def inspect_fdopen(descriptor, *args, **kwargs):
        observed.append((stat.S_IMODE(os.fstat(descriptor).st_mode), os.fstat(descriptor).st_size))
        return actual_fdopen(descriptor, *args, **kwargs)

    monkeypatch.setattr("bodybrain.db.os.fdopen", inspect_fdopen)
    previous = os.umask(0)
    try:
        write_private_source(source_path, b"Synthetic source")
    finally:
        os.umask(previous)
    assert observed == [(0o600, 0)]
    with pytest.raises(FileExistsError):
        write_private_source(source_path, b"Replacement")
    assert source_path.read_bytes() == b"Synthetic source"


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes are not Windows ACLs")
def test_storage_service_startup_repairs_existing_source_permissions(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    source_dir = data_dir / "sources"
    source_dir.mkdir(parents=True)
    source = source_dir / "existing-synthetic-source"
    source.write_text("Synthetic report", encoding="utf-8")
    data_dir.chmod(0o755)
    source_dir.chmod(0o755)
    source.chmod(0o644)
    monkeypatch.setattr("bodybrain.service.Anatomy", lambda _path: None)
    settings = SimpleNamespace(data_dir=data_dir, db_path=data_dir / "records.sqlite3", atlas_path=tmp_path / "unused")
    Service(settings, None, None, None)
    assert mode(data_dir) == 0o700 and mode(source_dir) == 0o700
    assert mode(source) == 0o600
    assert source.read_text(encoding="utf-8") == "Synthetic report"


def test_storage_state_conflict_is_distinct_and_preserves_record(tmp_path):
    store = Store(tmp_path / "records.sqlite3")
    item = store.insert(record())
    store.update(item["id"], expected_status="pending_review", status="approved")
    with pytest.raises(StateConflict):
        store.update(item["id"], expected_status="pending_review", status="rejected")
    assert not issubclass(StateConflict, ValueError)
    assert store.get(item["id"])["status"] == "approved"


@pytest.mark.parametrize("memory_status, step_status", [
    ("unconfigured", "unconfigured"), ("pending", "pending"),
    ("indexed", "completed"), ("failed", "failed"),
])
def test_storage_review_reconciles_original_run(tmp_path, memory_status, step_status):
    store = Store(tmp_path / "records.sqlite3")
    item = store.insert(record())
    run = store.new_run("record_ingestion", item["id"])
    run.update(status="awaiting_review", steps=[
        {"name": "Read source", "status": "completed"},
        {"name": "Human review", "status": "pending"},
        {"name": "Cognee memory", "status": "blocked", "detail": "Waiting for review"},
    ])
    store.save_run(run)
    other = store.new_run("record_ingestion", "different-record")
    store.reconcile_review_run(item["id"])
    assert next(saved for saved in store.runs() if saved["id"] == run["id"])["status"] == "awaiting_review"

    store.update(item["id"], status="approved", memory_status=memory_status)
    store.reconcile_review_run(item["id"])
    updated = next(saved for saved in store.runs() if saved["id"] == run["id"])
    assert updated["status"] == "completed"
    assert updated["steps"][0] == run["steps"][0]
    assert updated["steps"][1]["status"] == "completed"
    assert updated["steps"][2]["status"] == step_status
    assert "Waiting for review" not in str(updated)
    assert next(saved for saved in store.runs() if saved["id"] == other["id"]) == other

    store.reconcile_review_run(item["id"])
    assert next(saved for saved in store.runs() if saved["id"] == run["id"]) == updated


def test_storage_review_reconciles_after_more_than_one_hundred_new_runs(tmp_path):
    store = Store(tmp_path / "records.sqlite3")
    item = store.insert(record())
    ingestion = store.new_run("record_ingestion", item["id"])
    for _ in range(105):
        store.new_run("unrelated")
    store.update(item["id"], status="approved", memory_status="indexed")
    store.reconcile_review_run(item["id"])
    with store.connect() as db:
        row = db.execute("SELECT json_extract(data, '$.status') FROM runs WHERE id=?", (ingestion["id"],)).fetchone()
    assert row[0] == "completed"
