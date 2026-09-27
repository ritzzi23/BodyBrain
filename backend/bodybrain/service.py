import asyncio
from contextlib import asynccontextmanager
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
import uuid

from .anatomy import Anatomy, FINDING_LIMIT_WARNING, MAX_FINDINGS, source_passages
from .config import Settings
from .db import Store, now, private_directory, private_file, write_private_source
from .evidence import citations_for, verified_quote
from .ingestion import explicit_date, parse_document
from .cognee_relay import CogneeRelay
from .relay_protocol import make_task, is_expired


class CleanupFailure(RuntimeError):
    """Safe public error; the durable record remains available for retry."""


def include_source_passages(pages: list[dict], findings: list[dict], warnings: list[str]) -> list[dict]:
    """Keep non-anatomical context available for review, including short notes."""
    findings = list(findings)
    represented = {(finding["page"], finding["quote"]) for finding in findings}
    for page in pages:
        for quote in source_passages(page["text"], warnings=warnings):
            if (page["page"], quote) in represented:
                continue
            if len(findings) >= MAX_FINDINGS:
                if FINDING_LIMIT_WARNING not in warnings:
                    warnings.append(FINDING_LIMIT_WARNING)
                return findings
            findings.append({"id": str(uuid.uuid4()), "quote": quote, "page": page["page"], "anatomy_query": "Unmapped source passage", "concept": None, "mapping_status": "unmapped", "laterality": None, "evidence_type": "source_passage", "approved": False})
            represented.add((page["page"], quote))
    return findings


class Service:
    relay: CogneeRelay | None = None

    def __init__(self, settings: Settings, memory, clawmax_ingest, clawmax_evidence):
        self.settings = settings
        self.store = Store(settings.db_path)
        self.anatomy = Anatomy(settings.atlas_path)
        self.memory = memory
        self.clawmax_ingest = clawmax_ingest
        self.clawmax_evidence = clawmax_evidence
        self.relay = CogneeRelay(settings) if getattr(settings, "clawmax_transport", "dashboard") == "cognee_relay" else None
        self.apply_remote_result = None
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.queued: set[str] = set()
        self.jobs: set[asyncio.Task] = set()
        self.record_locks: dict[str, asyncio.Lock] = {}
        self.source_dir = settings.data_dir / "sources"
        private_directory(self.source_dir)
        for source in self.source_dir.iterdir():
            if source.is_file():
                private_file(source)

    @asynccontextmanager
    async def lock_records(self, *record_ids: str):
        locks = [self.record_locks.setdefault(record_id, asyncio.Lock()) for record_id in sorted(set(record_ids))]
        acquired = []
        try:
            for lock in locks:
                await lock.acquire()
                acquired.append(lock)
            yield
        finally:
            for lock in reversed(acquired):
                lock.release()

    def create_record(self, content: bytes, filename: str, title: str, record_type: str, event_date: str | None = None, *, revises: dict | None = None) -> dict:
        pages = parse_document(content, filename, self.settings.max_text_chars)
        text = "\n\n".join(page["text"] for page in pages)
        # Include dated/type metadata in identity; identical bytes with different
        # confirmed event dates must not silently reuse a previous record.
        # Re-reviewing identical text intentionally creates a new immutable source.
        revision_key = str(uuid.uuid4()) if revises else ""
        digest = hashlib.sha256(content + f"\0{record_type}\0{event_date or ''}{revision_key}".encode()).hexdigest()
        existing = self.store.by_digest(digest)
        if existing:
            return existing
        record_id = str(uuid.uuid4())
        warnings = []
        findings = self.anatomy.extract(pages, warnings=warnings)
        if any(f["concept"] is None for f in findings):
            warnings.append("Some explicit anatomy mentions have no exact model match. They remain unhighlighted.")
        if not findings:
            warnings.append("No anatomical mentions were mapped automatically. You can still review the source and save it for recall.")
        findings = include_source_passages(pages, findings, warnings)
        date = event_date or explicit_date(text)
        if not date:
            warnings.append("No explicit event date was identified. Upload time is not treated as the clinical event date.")
        record = {
            "id": record_id, "digest": digest, "title": title or Path(filename).name,
            "filename": Path(filename).name, "record_type": record_type, "event_date": date,
            "status": "pending_review", "memory_status": "not_indexed",
            "text": text, "pages": pages, "findings": findings, "warnings": warnings,
            "created_at": now(), "updated_at": now(), "source_format": filename.rsplit(".", 1)[-1].lower(),
            "extraction_mode": "anatomical_mentions", "index_error": None,
            "revision_number": revises.get("revision_number", 1) + 1 if revises else 1,
            "revises_record_id": revises["id"] if revises else None, "superseded_by": None,
            "source_kind": "corrected_transcription" if revises else "original",
            "deletion_error": None, "memory_target": None, "remote_memory_present": False,
        }
        path = self.source_dir / record_id
        write_private_source(path, content)
        try:
            inserted = self.store.insert(record)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        if inserted["id"] == record_id:
            run = self.store.new_run("record_ingestion", record_id)
            run.update(status="awaiting_review", steps=[
                {"name": "Read source", "status": "completed"},
                {"name": "Match anatomical mentions", "status": "completed", "detail": f"{len(findings)} source excerpts; no clinical inference"},
                {"name": "Human review", "status": "pending"},
                {"name": "Cognee memory", "status": "blocked", "detail": "Waiting for review"},
            ])
            self.store.save_run(run)
        else:
            path.unlink(missing_ok=True)
        return inserted

    def memory_target(self) -> dict:
        target = getattr(self.memory, "target_identity", None)
        if isinstance(target, dict):
            return target
        # Test/custom adapters may not implement target_identity. Never store keys.
        return {"mode": self.settings.cognee_mode, "base_url": self.settings.cognee_url.rstrip("/"), "dataset": self.settings.cognee_dataset}

    async def retire_memory(self, record: dict) -> None:
        # A failed/interrupted provider write may have committed before failing.
        # Legacy records lack the durable attempted-write flag: use current target.
        could_exist = record.get("remote_memory_present")
        if could_exist is None:
            could_exist = record["memory_status"] in {"indexed", "pending", "failed"}
        if not could_exist:
            return
        target = record.get("memory_target")
        if target is not None and target != self.memory_target():
            raise CleanupFailure("Cognee configuration differs from this record's memory destination. Restore the original configuration and retry.")
        try:
            result = await self.memory.forget(record["id"])
            if not isinstance(result, dict) or result.get("status") not in {"deleted", "not_found"}:
                raise RuntimeError("Unconfirmed memory deletion")
        except Exception as exc:
            raise CleanupFailure("Cognee could not confirm removal of this record's memory. Check the connection and retry; the local record has been retained.") from exc
        current = self.store.get(record["id"])
        if current:
            self.store.update(record["id"], memory_status="retired", remote_memory_present=False, index_error=None)

    async def delete_record(self, record_id: str) -> None:
        record = self.store.get(record_id)
        if record and record["status"] == "pending_review":
            # A draft is already excluded from recall. Serialize its deletion
            # with approval so a retiring parent cannot lose its replacement
            # midway through the remote-retirement / atomic-promotion sequence.
            async with self.lock_records(record_id):
                if not self.store.get(record_id):
                    return
                self.store.begin_delete(record_id)
                await self._delete_record_locked(record_id)
            return
        # Hide it and revoke task snapshots before waiting for an in-flight index.
        self.store.begin_delete(record_id)
        async with self.lock_records(record_id):
            await self._delete_record_locked(record_id)

    async def _delete_record_locked(self, record_id: str) -> None:
        record = self.store.get(record_id)
        if not record:  # A concurrent retry has already completed.
            return
        try:
            for job in self.store.relay_jobs():
                if record_id in job.get("record_ids", []):
                    await self._cleanup_relay(job)
            await self.retire_memory(record)
            (self.source_dir / record_id).unlink(missing_ok=True)
            self.store.finish_delete(record_id)
        except Exception as exc:
            message = str(exc) if isinstance(exc, CleanupFailure) else "Local source cleanup failed. The record is hidden from recall; retry deletion."
            self.store.update(record_id, expected_status="deleting", deletion_error=message)
            raise CleanupFailure(message) from exc

    async def queue_index(self, record_id: str):
        async with self.lock_records(record_id):
            await self._queue_index(record_id)

    async def _queue_index(self, record_id: str):
        record = self.store.get(record_id)
        if not record or record["status"] != "approved":
            return
        status = await self.memory.status()
        record = self.store.get(record_id)
        if not record or record["status"] != "approved":
            return
        if not status.get("configured"):
            self.store.update(record_id, expected_status="approved", memory_status="unconfigured", index_error="Cognee is not configured. The reviewed record is saved locally.")
            return
        if record_id in self.queued:
            return
        self.queued.add(record_id)
        self.store.update(record_id, expected_status="approved", memory_status="pending", index_error=None)
        await self.queue.put(record_id)

    async def index_worker(self):
        while True:
            record_id = await self.queue.get()
            try:
                async with self.lock_records(record_id):
                    await self._index_record(record_id)
            finally:
                self.queued.discard(record_id)
                self.queue.task_done()

    async def _index_record(self, record_id: str):
        record = self.store.get(record_id)
        if not record or record["status"] != "approved":
            return  # Deleted, superseded, and orphaned queued jobs are harmless.
        run = self.store.new_run("memory_index", record_id)
        run["steps"] = [{"name": "Cognee indexing", "status": "running"}]
        self.store.save_run(run)
        try:
            target = self.memory_target()
            if record.get("memory_target") is not None and record["memory_target"] != target:
                raise CleanupFailure("Restore the original Cognee destination before retrying indexing.")
            self.store.update(record_id, expected_status="approved", memory_target=target, remote_memory_present=True)
            lines = [f"BODYBRAIN_SOURCE_ID: {record_id}", f"Title: {record['title']}", f"Record type: {record['record_type']}", f"Event date: {record.get('event_date') or 'unknown'}"]
            for finding in record["findings"]:
                if finding.get("approved"):
                    concept = finding.get("concept")
                    lines.extend([f"Source: {record_id}; page: {finding['page']}", f"Atlas concept: {concept['id'] if concept else 'unmapped'}", finding["quote"]])
            await self.memory.remember(record_id, "\n".join(lines), {"title": record["title"], "event_date": record.get("event_date"), "record_type": record["record_type"]})
            current = self.store.get(record_id)
            if current and current["status"] == "approved":
                self.store.update(record_id, expected_status="approved", memory_status="indexed", index_error=None)
                self.store.reconcile_review_run(record_id)
                run.update(status="completed", steps=[{"name": "Cognee indexing", "status": "completed"}])
        except asyncio.CancelledError:
            run.update(status="interrupted", steps=[{"name": "Cognee indexing", "status": "pending", "detail": "Will resume after restart"}])
            raise
        except Exception:
            message = "Cognee indexing failed. Check configuration and retry. The original record is preserved."
            current = self.store.get(record_id)
            if current and current["status"] == "approved":
                self.store.update(record_id, expected_status="approved", memory_status="failed", index_error=message)
                self.store.reconcile_review_run(record_id)
                run.update(status="failed", steps=[{"name": "Cognee indexing", "status": "failed", "detail": message}])
        finally:
            self.store.save_run(run)

    async def dispatch(self, kind: str, *, record_id: str | None = None, question: str | None = None, concept_id: str | None = None, evidence: list[dict] | None = None) -> dict | None:
        client = self.clawmax_ingest if kind == "ingestion" else self.clawmax_evidence
        if not (self.relay.configured if self.relay else client.configured and self.settings.agent_token):
            return None
        if kind == "ingestion" and record_id:
            record = self.store.get(record_id)
            if not record or record["status"] != "pending_review":
                return None
            previous = self.store.ingestion_task(record_id)
            if previous:
                return previous
        task = {"id": str(uuid.uuid4()), "kind": kind, "status": "pending", "record_id": record_id, "question": question, "concept_id": concept_id, "created_at": now(), "result": None}
        if kind == "evidence":
            # Freeze the reviewed evidence supplied to this task. A later import,
            # unselected passage, or another task's sources are outside its scope.
            snapshots = []
            approved = self.store.records(approved_only=True)
            relevant = evidence if evidence is not None else citations_for(approved, question or "", concept_id, limit=8)[0]
            allowed = {(item["record_id"], item["page"], item["quote"]) for item in relevant}
            for record in approved:
                findings = [f for f in record["findings"] if f.get("approved") and (record["id"], f["page"], f["quote"]) in allowed and verified_quote(record, f["page"], f["quote"]) and (not concept_id or f.get("concept") and f["concept"]["id"] == concept_id)]
                if not findings:
                    continue
                snapshots.append({"id": record["id"], "title": record["title"], "record_type": record["record_type"], "event_date": record.get("event_date"), "findings": findings, "pages": [{"page": p, "text": "\n".join(dict.fromkeys(f["quote"] for f in findings if f["page"] == p))} for p in sorted({f["page"] for f in findings})]})
            if not snapshots:
                return None
            task["records"] = snapshots
            task["allowed_record_ids"] = [r["id"] for r in snapshots]
        if not self.store.save_task(task):
            return None
        run = self.store.new_run(f"clawmax_{kind}", record_id)
        run["task_id"] = task["id"]
        self.store.save_run(run)
        task["run_id"] = run["id"]
        self.store.save_task(task)
        if self.relay:
            refs = [record_id] if record_id else task.get("allowed_record_ids", [])
            async with self.lock_records(*refs):
                if self.store.task(task["id"]) is None:
                    return None
                payload = {"id": task["id"], "kind": kind}
                if kind == "ingestion":
                    record = self.store.get(record_id)
                    if not record or record["status"] != "pending_review":
                        return None
                    payload["record"] = {key: record[key] for key in ("id", "title", "event_date", "pages", "findings")}
                    payload["anatomy_candidates"] = list({f["concept"]["id"]: f["concept"] for f in record["findings"] if f.get("concept")}.values())
                else:
                    payload.update(question=question, concept_id=concept_id, records=task["records"])
                try:
                    envelope = make_task(task["id"], kind, payload)
                except ValueError:
                    # Oversized source/findings envelopes must fail the durable
                    # task instead of leaving an unpollable pending task that
                    # blocks all later ingestion attempts for this record.
                    response = {"provider": "clawmax", "transport": "cognee_relay", "status": "error", "configured": True, "message": "The task could not be prepared for the hosted worker. Continue with local review or retry with a smaller report."}
                else:
                    job = {"task": envelope, "record_ids": refs, "target": self.relay.target_identity}
                    self.store.save_relay_job(job)  # Persist cleanup identity before any remote write.
                    try:
                        await self.relay.publish(envelope)
                        response = {"provider": "clawmax", "transport": "cognee_relay", "status": "submitted", "configured": True, "execution_id": task["id"], "workflow_id": kind, "message": "Task published through Cognee; waiting for the hosted ClawMax worker."}
                    except Exception:
                        response = {"provider": "clawmax", "transport": "cognee_relay", "status": "error", "configured": True, "message": "Could not confirm Cognee task publication. Check integration status before retrying."}
        else:
            response = await client.trigger_task(task["id"])
        # A fast callback may arrive before trigger() returns. Keep its validated
        # completion instead of overwriting it with the submission state.
        task = self.store.task(task["id"])
        if task is None:
            return None  # Deletion revoked this task while the provider awaited.
        run = next((item for item in self.store.runs() if item["id"] == run["id"]), run)
        task["execution"] = response
        run["execution"] = response
        submitted = response.get("status") == "submitted"
        if task["status"] != "completed":
            run["status"] = "submitted" if submitted else "failed"
            task["status"] = "pending" if submitted else "failed"
            run["steps"] = [{"name": "ClawMax workflow", "status": run["status"], "detail": "Waiting for agent callback" if submitted else response.get("message", "Workflow could not be started")}]
        self.store.save_task(task)
        self.store.save_run(run)
        return task

    async def refresh_task(self, task_id: str) -> dict | None:
        task = self.store.task(task_id)
        if not task or task["status"] != "pending":
            return task
        if not task.get("execution", {}).get("execution_id"):
            # A process can stop after persisting the relay envelope (or after
            # Cognee accepts it), before dispatch saves its acknowledgement.
            # The durable job is enough to resume result checks and expiry; it
            # is not proof that publication succeeded, so do not republish it.
            job = next((item for item in self.store.relay_jobs() if item["task"]["task_id"] == task_id), None) if self.relay else None
            if (not job or not self.relay.configured or job["target"] != self.relay.target_identity
                    or "payload" not in job["task"]):
                return task
            task["execution"] = {
                "provider": "clawmax", "transport": "cognee_relay", "status": "recovering",
                "configured": True, "execution_id": task_id, "workflow_id": task["kind"],
                "message": "Recovering an interrupted Cognee handoff; checking for a worker result.",
            }
            self.store.save_task(task)
        checked = task.get("last_checked_at")
        if checked and (datetime.fromisoformat(now()) - datetime.fromisoformat(checked)).total_seconds() < 5:
            return task
        task["last_checked_at"] = now()
        self.store.save_task(task)
        if task.get("execution", {}).get("transport") == "cognee_relay":
            return await self._refresh_relay(task)
        client = self.clawmax_ingest if task["kind"] == "ingestion" else self.clawmax_evidence
        response = await client.execution(task["execution"]["execution_id"])
        task = self.store.task(task_id)
        if task is None:
            return None
        if task["status"] != "pending":
            return task
        task["execution_state"] = response
        if response.get("status") in {"failed", "completed"}:
            task["status"] = "failed"
            task["error"] = "ClawMax finished without a validated BodyBrain result." if response["status"] == "completed" else "ClawMax reported workflow failure. Check the execution in ClawMax."
            run = next((r for r in self.store.runs() if r["id"] == task.get("run_id")), None)
            if run:
                run.update(status="failed", steps=[{"name": "ClawMax workflow", "status": "failed", "detail": task["error"]}])
                self.store.save_run(run)
        self.store.save_task(task)
        return task

    async def _refresh_relay(self, task: dict) -> dict | None:
        job = next((item for item in self.store.relay_jobs() if item["task"]["task_id"] == task["id"]), None)
        if not job or not self.relay or job["target"] != self.relay.target_identity:
            return task
        try:
            result = await self.relay.result(job["task"])
        except Exception:
            # Transient service failures keep the durable task pending until expiry.
            result = None
        error = None
        if is_expired(job["task"]):
            error = "The ClawMax task expired without a validated result. Check the worker before retrying."
        elif result is not None:
            if result["status"] == "failed":
                error = "The hosted ClawMax worker could not complete this task."
            else:
                try:
                    if self.apply_remote_result is None:
                        raise RuntimeError("Result validator unavailable")
                    await self.apply_remote_result(task["id"], result["result"])
                    current = self.store.task(task["id"])
                    if current:
                        current["worker_execution"] = result.get("execution", {})
                        self.store.save_task(current)
                    return current
                except Exception:
                    error = "BodyBrain rejected the ClawMax result because it did not pass source validation."
        current = self.store.task(task["id"])
        if error and current and current["status"] == "pending":
            current.update(status="failed", error=error)
            self.store.save_task(current)
            run = next((r for r in self.store.runs() if r["id"] == current.get("run_id")), None)
            if run:
                run.update(status="failed", steps=[{"name": "ClawMax through Cognee", "status": "failed", "detail": error}])
                self.store.save_run(run)
        return current

    async def _cleanup_relay(self, job: dict) -> None:
        if not self.relay or not self.relay.configured or job["target"] != self.relay.target_identity:
            raise CleanupFailure("Restore this task's Cognee relay configuration before removing its remote files.")
        try:
            await self.relay.cleanup(job["task"])
        except Exception as exc:
            raise CleanupFailure("Could not confirm removal of the ClawMax relay files. Retry cleanup when Cognee is reachable.") from exc
        # Retain only an identity tombstone briefly to remove late worker uploads;
        # source text must not survive local record deletion in this ledger.
        job["task"] = {key: job["task"][key] for key in ("task_id", "digest", "expires_at")}
        self.store.save_relay_job(job)
        expires = datetime.fromisoformat(job["task"]["expires_at"])
        if datetime.now(timezone.utc) > expires + timedelta(minutes=5):
            self.store.remove_relay_job(job["task"]["task_id"])

    async def relay_tick(self) -> None:
        for job in self.store.relay_jobs():
            task = self.store.task(job["task"]["task_id"])
            if task and task["status"] == "pending" and "payload" in job["task"]:
                await self.refresh_task(task["id"])
                task = self.store.task(task["id"])
            if not task or task["status"] != "pending":
                try:
                    await self._cleanup_relay(job)
                except CleanupFailure:
                    pass  # Durable cleanup entry remains retryable, including after restart.

    async def relay_worker(self) -> None:
        while True:
            try:
                await self.relay_tick()
            except Exception:
                pass  # Provider failures never stop local review or record processing.
            await asyncio.sleep(5)
