from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Literal
import asyncio
import hmac
import logging
import uuid

from fastapi import FastAPI, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .anatomy import complete_source_quote
from .config import Settings
from .clawmax import ClawMaxClient
from .cognee_memory import CogneeMemory
from .db import StateConflict, now
from .demo import DEMO_RECORDS
from .evidence import citations_for, render_answer, verified_quote
from .ingestion import InvalidDocument
from .service import CleanupFailure, Service, include_source_passages
from .relay_protocol import is_expired


class TextRecord(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=150_000)
    record_type: str = Field(default="personal_record", max_length=60)
    event_date: date | None = None
    allow_agent: bool = False


class Approval(BaseModel):
    finding_ids: list[str] | None = None


class MappingEdit(BaseModel):
    finding_id: str
    concept_id: str | None


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    concept_id: str | None = None
    allow_agent: bool = False


class AgentFinding(BaseModel):
    quote: str = Field(min_length=1, max_length=2000)
    page: int = Field(ge=1)
    anatomy_query: str = Field(min_length=1, max_length=200)
    concept_id: str | None = None
    laterality: Literal["left", "right", "bilateral"] | None = None


class Citation(BaseModel):
    record_id: str
    page: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=150_000)


class AgentResult(BaseModel):
    findings: list[AgentFinding] | None = Field(default=None, max_length=150)
    answer: str | None = Field(default=None, max_length=12000)
    citations: list[Citation] | None = Field(default=None, max_length=30)


def create_app(settings: Settings | None = None, memory=None, clawmax_ingest=None, clawmax_evidence=None) -> FastAPI:
    settings = settings or Settings()
    if any(host not in {"localhost", "127.0.0.1", "testserver"} for host in settings.allowed_hosts) and not settings.api_token:
        raise ValueError("Set BODYBRAIN_API_TOKEN before allowing a network-accessible backend hostname")
    if settings.api_token and settings.agent_token and settings.api_token == settings.agent_token:
        raise ValueError("Use distinct API and agent callback tokens")
    memory = memory or CogneeMemory(mode=settings.cognee_mode, base_url=settings.cognee_url or None, api_key=settings.cognee_api_key or None, bearer_token=settings.cognee_token or None, dataset=settings.cognee_dataset, storage_path=str(settings.data_dir / "cognee"))
    clawmax_ingest = clawmax_ingest or ClawMaxClient(settings.clawmax_url, settings.clawmax_token, settings.clawmax_ingest_workflow)
    clawmax_evidence = clawmax_evidence or ClawMaxClient(settings.clawmax_url, settings.clawmax_token, settings.clawmax_evidence_workflow)
    service = Service(settings, memory, clawmax_ingest, clawmax_evidence)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        worker = asyncio.create_task(service.index_worker())
        relay_worker = asyncio.create_task(service.relay_worker()) if service.relay else None
        for record in service.store.records():
            if record["status"] == "approved":
                if record["memory_status"] == "pending":
                    await service.queue_index(record["id"])
                service.store.reconcile_review_run(record["id"])
            elif record["status"] == "pending_review" and not record["findings"]:
                # Repair drafts stranded by the old minimum passage length. Never
                # rewrite a human-reviewed record or replace existing mapping edits.
                warnings = list(record["warnings"])
                findings = include_source_passages(record["pages"], [], warnings)
                service.store.update(record["id"], expected_status="pending_review", findings=findings, warnings=warnings)
        try:
            yield
        finally:
            worker.cancel()
            if relay_worker:
                relay_worker.cancel()
            jobs = list(service.jobs)
            for job in jobs:
                job.cancel()
            await asyncio.gather(worker, *([relay_worker] if relay_worker else []), *jobs, return_exceptions=True)

    app = FastAPI(title="BodyBrain API", version="0.1.0", lifespan=lifespan, description="Local single-user backend. Sources and review state are authoritative; optional ClawMax and Cognee providers are reported explicitly.")
    app.state.service = service

    @app.exception_handler(StateConflict)
    async def state_conflict(request: Request, exc: StateConflict):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": str(exc)}, status_code=409)
    @app.exception_handler(CleanupFailure)
    async def cleanup_failure(request: Request, exc: CleanupFailure):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": str(exc)}, status_code=503)
    allowed_origins = set(settings.allowed_origins)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))
    app.add_middleware(CORSMiddleware, allow_origins=list(allowed_origins), allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type", "Authorization"])

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin not in allowed_origins:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "This local API does not accept requests from that origin."}, status_code=403)
        if settings.api_token and request.url.path.startswith("/api/") and not request.url.path.startswith("/api/agent/"):
            provided = request.headers.get("authorization", "")
            if not hmac.compare_digest(provided, f"Bearer {settings.api_token}"):
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "API token required"}, status_code=401)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def get_record(record_id: str) -> dict:
        record = service.store.get(record_id)
        if not record:
            raise HTTPException(404, "Record not found")
        return record

    def enqueue_dispatch(kind: str, **kwargs):
        job = asyncio.create_task(service.dispatch(kind, **kwargs))
        service.jobs.add(job)
        def finished(task):
            service.jobs.discard(task)
            if not task.cancelled() and task.exception() is not None:
                # Retrieve the exception without leaking document text or credentials.
                logging.getLogger(__name__).error("Background workflow failed (%s)", type(task.exception()).__name__)
        job.add_done_callback(finished)
        return job

    async def agent_auth(authorization: Annotated[str | None, Header()] = None):
        if not settings.agent_token:
            raise HTTPException(503, "Agent callbacks are not configured")
        if not authorization or not hmac.compare_digest(authorization, f"Bearer {settings.agent_token}"):
            raise HTTPException(401, "Agent token required")

    @app.get("/api/health")
    async def health():
        records = service.store.records()
        cognee = await memory.status()
        relay_configured = bool(service.relay and service.relay.configured)
        return {"status": "ok", "storage": "sqlite", "scope": "local_single_user", "integrations": {
            "cognee": cognee,
            "clawmax": {"transport": settings.clawmax_transport,
                        "configured": relay_configured if service.relay else bool(clawmax_ingest.configured and clawmax_evidence.configured and settings.agent_token),
                        "ingestion_configured": relay_configured if service.relay else clawmax_ingest.configured,
                        "evidence_configured": relay_configured if service.relay else clawmax_evidence.configured,
                        "callbacks_configured": relay_configured if service.relay else bool(settings.agent_token)},
        }, "counts": {"records": len(records), "approved": sum(r["status"] == "approved" for r in records)}}

    @app.get("/api/integrations")
    async def integrations():
        if service.relay:
            cognee_status, relay_status = await asyncio.gather(memory.status(probe=True), service.relay.health())
            ingestion_status = {**relay_status, "workflow_id": settings.clawmax_ingest_workflow}
            evidence_status = {**relay_status, "workflow_id": settings.clawmax_evidence_workflow}
        else:
            cognee_status, ingestion_status, evidence_status = await asyncio.gather(memory.status(probe=True), clawmax_ingest.health(), clawmax_evidence.health())
        return {"cognee": cognee_status, "clawmax": {"ingestion": ingestion_status, "evidence": evidence_status}}

    @app.get("/api/records")
    def records():
        return {"records": service.store.records()}

    @app.post("/api/records/text", status_code=201)
    async def add_text(body: TextRecord):
        try:
            record = await run_in_threadpool(service.create_record, body.text.encode(), "record.txt", body.title, body.record_type, body.event_date.isoformat() if body.event_date else None)
        except InvalidDocument as exc:
            raise HTTPException(422, str(exc)) from exc
        if body.allow_agent and record["status"] == "pending_review":
            enqueue_dispatch("ingestion", record_id=record["id"])
        return record

    @app.post("/api/records", status_code=201)
    async def upload(file: UploadFile = File(...), title: str = Form(""), record_type: str = Form("personal_record"), event_date: date | None = Form(None), allow_agent: bool = Form(False)):
        if len(title) > 200 or len(record_type) > 60:
            raise HTTPException(422, "Title or record type is too long")
        content = await file.read(settings.max_upload_bytes + 1)
        await file.close()
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(413, "Upload limit is 10 MB")
        try:
            record = await run_in_threadpool(service.create_record, content, file.filename or "record.txt", title, record_type, event_date.isoformat() if event_date else None)
        except InvalidDocument as exc:
            raise HTTPException(422, str(exc)) from exc
        if allow_agent and record["status"] == "pending_review":
            enqueue_dispatch("ingestion", record_id=record["id"])
        return record

    @app.get("/api/records/{record_id}")
    def record_detail(record_id: str):
        return get_record(record_id)

    @app.get("/api/records/{record_id}/source")
    async def source(record_id: str):
        record = get_record(record_id)
        if record["status"] == "deleting":
            raise HTTPException(409, "This record is being deleted")
        path = service.source_dir / record["id"]
        if not path.is_file():
            raise HTTPException(404, "Original source file is unavailable")
        media_type = "application/pdf" if record["source_format"] == "pdf" else "text/plain; charset=utf-8"
        return FileResponse(path, filename=record["filename"], media_type=media_type, content_disposition_type="attachment")

    @app.post("/api/records/{record_id}/revisions", status_code=201)
    async def revise(record_id: str, body: TextRecord):
        async with service.lock_records(record_id):
            parent = get_record(record_id)
            if parent["status"] != "approved":
                raise HTTPException(409, "Only an active approved record can be revised")
            try:
                return await run_in_threadpool(service.create_record, body.text.encode(), "revision.txt", body.title, body.record_type, body.event_date.isoformat() if body.event_date else None, revises=parent)
            except InvalidDocument as exc:
                raise HTTPException(422, str(exc)) from exc

    @app.delete("/api/records/{record_id}")
    async def delete(record_id: str):
        get_record(record_id)
        await service.delete_record(record_id)
        return {"status": "deleted", "record_id": record_id}

    @app.patch("/api/records/{record_id}/mapping")
    async def edit_mapping(record_id: str, edit: MappingEdit):
        async with service.lock_records(record_id):
            return apply_mapping(record_id, edit)

    def apply_mapping(record_id: str, edit: MappingEdit):
        record = get_record(record_id)
        if record["status"] != "pending_review":
            raise HTTPException(409, "Only pending records can be remapped")
        if edit.concept_id and edit.concept_id not in service.anatomy.by_id:
            raise HTTPException(422, "Unknown atlas concept")
        finding = next((f for f in record["findings"] if f["id"] == edit.finding_id), None)
        if not finding:
            raise HTTPException(404, "Finding not found")
        finding.update(concept=service.anatomy.by_id.get(edit.concept_id), mapping_status="matched" if edit.concept_id else "unmapped", mapping_method="user_selected")
        return service.store.update(record_id, expected_status="pending_review", findings=record["findings"])

    @app.post("/api/records/{record_id}/approve")
    async def approve(record_id: str, body: Approval):
        record = get_record(record_id)
        async with service.lock_records(record_id, *([record["revises_record_id"]] if record.get("revises_record_id") else [])):
            record = get_record(record_id)
            if record["status"] == "approved":
                service.store.reconcile_review_run(record_id)
                return record
            if record["status"] != "pending_review":
                raise HTTPException(409, "Only a pending record can be approved")
            ids = set(body.finding_ids if body.finding_ids is not None else [f["id"] for f in record["findings"]])
            if not ids or not ids.issubset({f["id"] for f in record["findings"]}):
                raise HTTPException(422, "Choose at least one valid finding to approve")
            for finding in record["findings"]:
                finding["approved"] = finding["id"] in ids
                if finding["approved"] and not verified_quote(record, finding["page"], finding["quote"]):
                    raise HTTPException(422, "A finding no longer matches the original source")
            if record.get("revises_record_id"):
                parent = service.store.get(record["revises_record_id"])
                if not parent or parent["status"] != "approved":
                    raise HTTPException(409, "The original version is no longer active; this revision cannot replace it")
                await service.retire_memory(parent)
                service.store.approve_revision(record_id, record["findings"])
            else:
                service.store.update(record_id, expected_status="pending_review", status="approved", findings=record["findings"], reviewed_at=now())
            await service._queue_index(record_id)
            service.store.reconcile_review_run(record_id)
            run = service.store.new_run("human_review", record_id)
            run.update(status="completed", steps=[{"name": "Human review", "status": "completed", "detail": f"{len(ids)} excerpts approved"}])
            service.store.save_run(run)
            return get_record(record_id)

    @app.post("/api/records/{record_id}/index")
    async def index(record_id: str):
        record = get_record(record_id)
        if record["status"] != "approved":
            raise HTTPException(409, "Review the record before indexing")
        if record["memory_status"] == "indexed":
            return record
        await service.queue_index(record_id)
        return get_record(record_id)

    @app.post("/api/records/{record_id}/process")
    async def process_with_agent(record_id: str):
        record = get_record(record_id)
        if record["status"] != "pending_review":
            raise HTTPException(409, "Reviewed records cannot be reprocessed by an agent")
        task = await service.dispatch("ingestion", record_id=record_id)
        if task is None:
            raise HTTPException(409, "Configure the selected ClawMax connection before processing")
        return task

    @app.get("/api/anatomy/search")
    def anatomy_search(q: str = "", limit: int = 20):
        return {"concepts": service.anatomy.search(q[:200], min(max(limit, 1), 100))}

    @app.get("/api/timeline")
    def timeline(concept_id: str | None = None):
        records = service.store.records(approved_only=True)
        if concept_id:
            records = [r for r in records if any(f.get("approved") and f.get("concept", {}) and f["concept"]["id"] == concept_id for f in r["findings"])]
        return {"events": sorted(records, key=lambda r: (r.get("event_date") is None, r.get("event_date") or r["created_at"]))}

    @app.post("/api/chat")
    async def chat(body: Question):
        question = body.question.strip()
        if not question:
            raise HTTPException(422, "Enter a question")
        if body.concept_id and body.concept_id not in service.anatomy.by_id:
            raise HTTPException(422, "Unknown atlas concept")
        approved = service.store.records(approved_only=True)
        warnings = []
        provider_ids = None
        provider_passages = {}
        mode = "local_evidence"
        status = await memory.status()
        if status.get("configured") and approved:
            try:
                result = await memory.recall(question, limit=8)
                provider_ids = set(result.get("document_ids", [])) & {r["id"] for r in approved}
                for match in result.get("results", []):
                    for record_id in set(match.get("document_ids", [])) & provider_ids:
                        if isinstance(match.get("text"), str):
                            provider_passages.setdefault(record_id, []).append(match["text"])
                mode = "cognee"
                if not provider_ids:
                    warnings.append("Cognee returned no source-linked matches. Showing matching reviewed excerpts from local storage.")
                    mode = "local_evidence"
            except Exception:
                warnings.append("Cognee recall is unavailable. Showing local reviewed evidence; no agent-generated answer.")
        elif not status.get("configured"):
            warnings.append("Cognee is not connected. This response uses local reviewed excerpts.")
        approved = service.store.records(approved_only=True)
        citations, concepts = citations_for(approved, question, body.concept_id, provider_ids, provider_passages=provider_passages)
        if re_causal(question):
            warnings.append("These records document findings and observations. They do not independently establish the cause of symptoms.")
        task = await service.dispatch("evidence", question=question, concept_id=body.concept_id, evidence=citations) if body.allow_agent and citations else None
        # Provider awaits can overlap deletion or revision approval. Render only
        # currently authoritative sources, never the pre-await snapshot.
        citations, concepts = citations_for(service.store.records(approved_only=True), question, body.concept_id, provider_ids, provider_passages=provider_passages)
        return {"answer": render_answer(citations), "citations": citations, "concepts": concepts, "retrieval_mode": mode, "warnings": warnings, "workflow_run_id": task.get("run_id") if task else None, "agent_task_id": task["id"] if task else None}

    @app.get("/api/summary")
    def summary(concept_id: str | None = None):
        citations, concepts = citations_for(service.store.records(approved_only=True), concept_id=concept_id, limit=60)
        return {"summary": render_answer(citations, summary=True), "citations": citations, "concepts": concepts}

    @app.post("/api/demo", status_code=201)
    async def demo(allow_agent: bool = False):
        records = []
        for item in DEMO_RECORDS:
            record = await run_in_threadpool(service.create_record, item["text"].encode(), "synthetic-demo.txt", item["title"], item["record_type"])
            records.append(record)
            if allow_agent and record["status"] == "pending_review":
                enqueue_dispatch("ingestion", record_id=record["id"])
        return {"records": records}

    @app.get("/api/runs")
    async def runs():
        pending = [r["task_id"] for r in service.store.runs() if r.get("task_id") and r["status"] == "submitted"]
        if pending:
            await asyncio.gather(*(service.refresh_task(task_id) for task_id in pending[:8]))
        return {"runs": service.store.runs()}

    @app.get("/api/tasks/{task_id}")
    async def user_task(task_id: str):
        task = await service.refresh_task(task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        return task

    @app.get("/api/agent/anatomy", dependencies=[Depends(agent_auth)])
    def agent_anatomy(q: str = ""):
        return anatomy_search(q)

    @app.get("/api/agent/tasks/{task_id}", dependencies=[Depends(agent_auth)])
    async def agent_task(task_id: str):
        task = service.store.task(task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        result = dict(task, anatomy_catalog_url="/api/agent/anatomy")
        if task["kind"] == "ingestion":
            record = get_record(task["record_id"])
            if record["status"] != "pending_review":
                raise HTTPException(409, "This record has already been reviewed")
            result["record"] = record
        else:
            result["records"] = task.get("records", [])
        return result

    @app.post("/api/agent/tasks/{task_id}/result", dependencies=[Depends(agent_auth)])
    async def agent_result(task_id: str, body: AgentResult):
        task = service.store.task(task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        refs = [task["record_id"]] if task.get("record_id") else task.get("allowed_record_ids", [])
        async with service.lock_records(*refs):
            if task.get("execution", {}).get("transport") == "cognee_relay":
                job = next((item for item in service.store.relay_jobs() if item["task"]["task_id"] == task_id), None)
                if not job or is_expired(job["task"]):
                    raise HTTPException(409, "The relay task has expired")
            return apply_agent_result(task_id, body)

    def apply_agent_result(task_id: str, body: AgentResult):
        task = service.store.task(task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        if task["status"] != "pending":
            raise HTTPException(409, "Task is no longer awaiting a result")
        if task["kind"] == "ingestion":
            record = get_record(task["record_id"])
            if record["status"] != "pending_review":
                raise HTTPException(409, "Human-reviewed records cannot be overwritten by an agent")
            if body.findings is None:
                raise HTTPException(422, "Return findings, using an empty list if no anatomical claims are supported")
            findings = []
            for finding in body.findings:
                if not verified_quote(record, finding.page, finding.quote):
                    raise HTTPException(422, "Agent quotation does not occur on the stated source page")
                page_text = next(page["text"] for page in record["pages"] if page["page"] == finding.page)
                if not complete_source_quote(page_text, finding.quote):
                    raise HTTPException(422, "Return complete source passages, preserving punctuation, line breaks, negation, and context")
                if finding.concept_id and finding.concept_id not in service.anatomy.by_id:
                    raise HTTPException(422, "Agent returned an unknown anatomical concept")
                findings.append({"id": str(uuid.uuid4()), **finding.model_dump(exclude={"concept_id"}), "concept": service.anatomy.by_id.get(finding.concept_id), "mapping_status": "matched" if finding.concept_id else "unmapped", "approved": False, "evidence_type": "source_mention", "mapping_method": "agent_proposed"})
            if findings:
                warnings = list(record["warnings"])
                findings = include_source_passages(record["pages"], findings, warnings)
                service.store.update(record["id"], expected_status="pending_review", findings=findings, warnings=warnings, extraction_mode="clawmax_agent")
            result = {"finding_count": len(findings), "review_required": True, "local_draft_preserved": not findings}
        else:
            citations = []
            concepts = {}
            for citation in body.citations or []:
                if citation.record_id not in task.get("allowed_record_ids", []):
                    raise HTTPException(422, "This record is outside the task's approved evidence scope")
                record = get_record(citation.record_id)
                if record["status"] != "approved" or not verified_quote(record, citation.page, citation.quote):
                    raise HTTPException(422, "Evidence must come from reviewed records and match its source")
                if not any(f.get("approved") and f["page"] == citation.page and citation.quote == f["quote"] for f in record["findings"]):
                    raise HTTPException(422, "Use the complete quotation selected during human review, preserving negation and context")
                snapshot = next((r for r in task.get("records", []) if r["id"] == citation.record_id), None)
                if not snapshot or not verified_quote(snapshot, citation.page, citation.quote):
                    raise HTTPException(422, "This passage was not included in the task snapshot")
                citations.append({**citation.model_dump(), "title": record["title"], "event_date": record.get("event_date")})
                for finding in record["findings"]:
                    if finding.get("approved") and finding.get("concept") and finding["quote"] == citation.quote and finding["page"] == citation.page:
                        concepts[finding["concept"]["id"]] = finding["concept"]
            # Retain the agent draft separately; only validated excerpts are presented
            # as the verified answer. Citation existence alone does not prove prose.
            result = {"answer": render_answer(citations), "agent_draft": body.answer, "citations": citations, "concepts": list(concepts.values()), "verification": "exact_source_quotes"}
        task.update(status="completed", result=result, completed_at=now())
        service.store.save_task(task)
        run = next((r for r in service.store.runs() if r["id"] == task.get("run_id")), None)
        if run:
            step = "ClawMax result through Cognee" if task.get("execution", {}).get("transport") == "cognee_relay" else "ClawMax agent callback"
            run.update(status="completed", steps=[{"name": step, "status": "completed"}, {"name": "Source validation", "status": "completed"}])
            service.store.save_run(run)
        return {"status": "accepted", "task_id": task_id, "result": result}

    async def apply_remote_result(task_id: str, payload: dict):
        return await agent_result(task_id, AgentResult.model_validate(payload))

    service.apply_remote_result = apply_remote_result
    return app


def re_causal(question: str) -> bool:
    import re
    return bool(re.search(r"\b(caus(?:e|es|ing|ed)|diagnos(?:is|es|e|ed|ing|tic)?|should i take|dosage)\b", question, re.I))


app = create_app()
