"""Small durable store. Source records remain authoritative, independent of providers."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import sqlite3
import uuid


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_data(serialized: str) -> dict:
    record = json.loads(serialized)
    # Older databases keep their sources unchanged while gaining version metadata.
    for key, default in {"revision_number": 1, "revises_record_id": None, "superseded_by": None, "deletion_error": None, "source_kind": "original"}.items():
        record.setdefault(key, default)
    if record.get("remote_memory_present") is None:
        # Capture a legacy upload obligation before retry/configuration updates
        # can replace pending/failed/indexed with an unrelated status.
        record["remote_memory_present"] = record["memory_status"] in {"indexed", "pending", "failed"}
    record.setdefault("memory_target", None)
    return record


class StateConflict(RuntimeError):
    """A record no longer has the state required by a pending operation."""


def private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Windows chmod does not implement POSIX owner/group access permissions.
    if os.name == "posix":
        path.chmod(0o700)


def private_file(path: Path) -> None:
    if os.name == "posix":
        try:
            path.chmod(0o600)
        except FileNotFoundError:
            # SQLite may remove its sidecars when the last connection closes.
            pass


def write_private_source(path: Path, content: bytes) -> None:
    """Create source data with private permissions before any bytes are written."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(descriptor, "wb") as source:
            source.write(content)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


class Store:
    def __init__(self, path: Path):
        self.path = path
        private_directory(path.parent)
        # Precreate privately; SQLite otherwise uses the process umask for a new DB.
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        self._private_database_files()
        with self.connect() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > 1:
                raise StateConflict('This database requires a newer BodyBrain version')
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS records (
                    id TEXT PRIMARY KEY,
                    digest TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL,
                    memory_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS deleted_record_ids (
                    id TEXT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS relay_jobs (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                );
                PRAGMA user_version=1;
            """)

    def _private_database_files(self) -> None:
        for suffix in ("", "-wal", "-shm", "-journal"):
            private_file(Path(str(self.path) + suffix))

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            try:
                self._private_database_files()
            finally:
                conn.close()

    def records(self, approved_only: bool = False) -> list[dict]:
        with self.connect() as db:
            sql = "SELECT data FROM records" + (" WHERE status='approved'" if approved_only else "") + " ORDER BY created_at DESC"
            return [record_data(row[0]) for row in db.execute(sql)]

    def get(self, record_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT data FROM records WHERE id=?", (record_id,)).fetchone()
            return record_data(row[0]) if row else None

    def by_digest(self, digest: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT data FROM records WHERE digest=?", (digest,)).fetchone()
            return record_data(row[0]) if row else None

    def insert(self, record: dict) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            parent_id = record.get("revises_record_id")
            if parent_id:
                parent = db.execute("SELECT status FROM records WHERE id=?", (parent_id,)).fetchone()
                if not parent or parent[0] != "approved":
                    raise StateConflict("Only an active approved record can be revised")
                if db.execute("SELECT 1 FROM records WHERE status='pending_review' AND json_extract(data, '$.revises_record_id')=?", (parent_id,)).fetchone():
                    raise StateConflict("This record already has a pending revision")
            # The uniqueness constraint protects even simultaneous duplicate uploads.
            db.execute("INSERT OR IGNORE INTO records VALUES (?,?,?,?,?,?)", (
                record["id"], record["digest"], record["status"], record["memory_status"], record["created_at"], json.dumps(record),
            ))
            return record_data(db.execute("SELECT data FROM records WHERE digest=?", (record["digest"],)).fetchone()[0])

    def update(self, record_id: str, *, expected_status: str | None = None, **updates) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM records WHERE id=?", (record_id,)).fetchone()
            if not row:
                raise KeyError(record_id)
            record = record_data(row[0])
            if expected_status and record["status"] != expected_status:
                raise StateConflict("Record changed while processing this request")
            record.update(updates, updated_at=now())
            db.execute("UPDATE records SET status=?, memory_status=?, data=? WHERE id=?", (
                record["status"], record["memory_status"], json.dumps(record), record_id,
            ))
            return record

    @staticmethod
    def _purge_related(db, record_id: str, *, purge_runs: bool = True) -> None:
        """Remove entire frozen tasks: their answers may quote any snapshot source."""
        tasks = []
        for row in db.execute("SELECT id,data FROM tasks"):
            task = json.loads(row["data"])
            refs = {task.get("record_id"), *task.get("allowed_record_ids", [])}
            refs.update(record.get("id") for record in task.get("records", []))
            refs.update(c.get("record_id") for c in (task.get("result") or {}).get("citations", []))
            if record_id in refs:
                tasks.append(row["id"])
        for task_id in tasks:
            db.execute("DELETE FROM runs WHERE json_extract(data, '$.task_id')=?", (task_id,))
            db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        if purge_runs:
            db.execute("DELETE FROM runs WHERE json_extract(data, '$.record_id')=?", (record_id,))

    def begin_delete(self, record_id: str) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM records WHERE id=?", (record_id,)).fetchone()
            if not row:
                raise KeyError(record_id)
            record = json.loads(row[0])
            if record["status"] == "approved" and db.execute("SELECT 1 FROM records WHERE status='pending_review' AND json_extract(data, '$.revises_record_id')=?", (record_id,)).fetchone():
                raise StateConflict("Delete the pending revision before deleting this record, or approve the revision first.")
            record.update(status="deleting", deletion_error=None, updated_at=now())
            # An opaque UUID tombstone prevents stale workers from recreating
            # activity after all source text and the record row are removed.
            db.execute("INSERT OR IGNORE INTO deleted_record_ids VALUES (?)", (record_id,))
            db.execute("UPDATE records SET status='deleting',data=? WHERE id=?", (json.dumps(record), record_id))
            self._purge_related(db, record_id)
            return record

    def finish_delete(self, record_id: str) -> None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._purge_related(db, record_id)
            db.execute("DELETE FROM records WHERE id=? AND status='deleting'", (record_id,))

    def approve_revision(self, record_id: str, findings: list[dict]) -> dict:
        """Commit both version states together after remote retirement succeeds."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM records WHERE id=?", (record_id,)).fetchone()
            if not row:
                raise StateConflict("Revision no longer exists")
            child = json.loads(row[0])
            parent_row = db.execute("SELECT data FROM records WHERE id=?", (child.get("revises_record_id"),)).fetchone()
            parent = json.loads(parent_row[0]) if parent_row else None
            if child["status"] != "pending_review" or not parent or parent["status"] != "approved":
                raise StateConflict("Revision or its parent changed")
            parent.update(status="superseded", superseded_by=record_id, updated_at=now())
            child.update(status="approved", findings=findings, reviewed_at=now(), updated_at=now())
            for record in (parent, child):
                db.execute("UPDATE records SET status=?,memory_status=?,data=? WHERE id=?", (record["status"], record["memory_status"], json.dumps(record), record["id"]))
            # Frozen agent answers based on the retired version must disappear.
            self._purge_related(db, parent["id"], purge_runs=False)
            return child

    def new_run(self, kind: str, record_id: str | None = None) -> dict:
        run = {"id": str(uuid.uuid4()), "kind": kind, "record_id": record_id, "status": "running", "created_at": now(), "steps": []}
        self.save_run(run)
        return run

    def save_run(self, run: dict):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if run.get("record_id"):
                row = db.execute("SELECT status FROM records WHERE id=?", (run["record_id"],)).fetchone()
                if (row and row[0] in {"deleting", "superseded"}) or db.execute("SELECT 1 FROM deleted_record_ids WHERE id=?", (run["record_id"],)).fetchone():
                    return False
            if run.get("task_id") and not db.execute("SELECT 1 FROM tasks WHERE id=?", (run["task_id"],)).fetchone():
                return False
            db.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?)", (run["id"], run["created_at"], json.dumps(run)))
            return True

    def runs(self) -> list[dict]:
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT data FROM runs ORDER BY created_at DESC LIMIT 100")]

    def reconcile_review_run(self, record_id: str) -> None:
        """Keep the original ingestion run consistent with durable review state."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM records WHERE id=?", (record_id,)).fetchone()
            if not row:
                raise KeyError(record_id)
            record = json.loads(row[0])
            if record["status"] != "approved":
                return
            memory_status = record["memory_status"]
            memory_steps = {
                "indexed": ("completed", "Approved excerpts indexed in Cognee"),
                "pending": ("pending", "Approved excerpts queued for Cognee indexing"),
                "failed": ("failed", "Cognee indexing failed; the reviewed record is saved locally"),
                "unconfigured": ("unconfigured", "Cognee is not configured; the reviewed record is saved locally"),
                "not_indexed": ("pending", "Approved excerpts have not been indexed"),
            }
            step_status, detail = memory_steps.get(memory_status, (memory_status, ""))
            rows = db.execute(
                "SELECT data FROM runs WHERE json_extract(data, '$.kind')='record_ingestion' AND json_extract(data, '$.record_id')=?",
                (record_id,),
            ).fetchall()
            for row in rows:
                run = json.loads(row[0])
                steps = [step for step in run.get("steps", []) if step.get("name") not in {"Human review", "Cognee memory"}]
                steps.extend([
                    {"name": "Human review", "status": "completed", "detail": "Selected source excerpts approved"},
                    {"name": "Cognee memory", "status": step_status, "detail": detail},
                ])
                run.update(status="completed", steps=steps)
                run.setdefault("completed_at", now())
                db.execute("UPDATE runs SET data=? WHERE id=?", (json.dumps(run), run["id"]))

    def save_task(self, task: dict):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            refs = {task.get("record_id"), *task.get("allowed_record_ids", [])}
            refs.update(record.get("id") for record in task.get("records", []))
            for record_id in refs - {None}:
                row = db.execute("SELECT status FROM records WHERE id=?", (record_id,)).fetchone()
                if not row or row[0] in {"deleting", "superseded"}:
                    return False
            db.execute("INSERT OR REPLACE INTO tasks VALUES (?,?)", (task["id"], json.dumps(task)))
            return True

    def task(self, task_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT data FROM tasks WHERE id=?", (task_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def ingestion_task(self, record_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT data FROM tasks WHERE json_extract(data, '$.kind')='ingestion' AND json_extract(data, '$.record_id')=? AND json_extract(data, '$.status') IN ('pending','completed') LIMIT 1", (record_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def save_relay_job(self, job: dict) -> None:
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO relay_jobs VALUES (?,?)", (job["task"]["task_id"], json.dumps(job)))

    def relay_jobs(self) -> list[dict]:
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT data FROM relay_jobs")]

    def remove_relay_job(self, task_id: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM relay_jobs WHERE id=?", (task_id,))
