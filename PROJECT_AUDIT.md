# BodyBrain Repository and Functional Audit

> **Dataset integration — September 28, 2026:**
> [Section 33](#33-synthea-and-fitbit-sample-workspaces--september-28-2026)
> adds two runnable local sample datasets. Section 32's operational blockers
> remain open.

> **Latest status — September 28, 2026:** See
> [Section 32](#32-local-release-work-and-live-relay-results--september-28-2026).
> The local app is operational and both hosted relay agents passed synthetic
> ingestion/evidence checks. Full completion is not claimed: remote cleanup
> returns HTTP 500, Mac login startup failed, and hosted restart supervision
> remains unverified. Older findings below are historical where superseded.

> **Remediation update — September 27, 2026:** The first repair batch is implemented
> and verified. [Section 23](#23-first-remediation-batch--september-27-2026) records
> the changes, fresh test results, and remaining work. Sections 1–22 preserve the
> original audit baseline; their defect/configuration tables are historical where
> superseded below. [Section 24](#24-selected-structure-spread-fix--september-27-2026)
> covers the subsequent anatomy explorer correction.
> [Section 25](#25-live-cognee-connection--september-27-2026) records successful live
> Cognee validation. [Section 26](#26-record-lifecycle-and-chat-persistence--september-27-2026)
> covers record correction/deletion and persistent chat. [Section 27](#27-clawmax-hosted-integration-preparation--september-27-2026)
> records the resumed ClawMax setup, imported template, callback proxy, and hosted
> prerequisites still blocking execution. [Section 28](#28-clawmax-openai-provider-setup--september-27-2026)
> records OpenAI verification and the subsequent two-agent deployment.
> Production readiness remains outstanding.

**Audit date:** September 27, 2026<br>
**Repository:** `nyu_personal_agent_hack`<br>
**Audit status:** Static review, local functional verification, and live synthetic Cognee verification<br>
**Purpose:** Consolidate the repository architecture, current readiness, verified functionality, unavailable features, confirmed defects, risks, limitations, and recommended next steps.

> This report contains no secret values. Configuration is described only through variable names and redacted readiness signals.

## 1. Executive summary

BodyBrain is a local-first, single-user application that combines an interactive 3D human anatomy atlas with a source-grounded personal-record memory workflow. The implemented product is a focused vertical slice of the much broader vision in `idea`.

The **local core is operational**:

- TypeScript validation passes.
- The production frontend builds successfully.
- All backend tests pass.
- All shipped anatomy assets are internally consistent.
- Records can be imported, parsed, mapped to anatomy, reviewed, approved, downloaded, placed on a timeline, deduplicated, and queried through exact source citations.
- SQLite persistence and original-source storage work.

The **external personal-agent layer is not operational in this checkout**:

- Cognee is explicitly disabled, even though a Cognee credential is present.
- ClawMax ingestion, evidence, and callback configuration are absent.
- Chat therefore uses local reviewed evidence rather than live semantic memory or agent workflows.

There are also confirmed workflow defects, most importantly an edge case in which a valid record with no generated findings can never be approved. The project is not production-ready because it lacks deletion/retention controls, production authentication/deployment, frontend browser tests, and appropriately private SQLite/directory permissions.

## 2. Audit scope and methodology

### 2.1 Inspected

The audit covered the complete meaningful authored surface:

- All frontend TypeScript, TSX, and CSS under `src/`.
- All backend Python modules under `backend/bodybrain/`.
- All backend tests under `backend/tests/`.
- Root and backend documentation.
- Vite, TypeScript, npm, Python, uv, and environment-example configuration.
- ClawMax workflows, agents, templates, skill instructions, and helper client.
- Cognee integration documentation and adapter implementation.
- Human Atlas and BodyParts3D licensing/attribution.
- Atlas manifest metadata and every raw/compressed model chunk.
- Safe metadata from the local SQLite store and retained source directory.
- Generated build/runtime/vendor directories at the inventory level.

### 2.2 Intentionally not exposed or contacted

- `.env` values were not printed or copied into this report.
- Live Cognee and ClawMax endpoints were not contacted.
- No credentials, medical records, source text, or project code were sent to a third party.
- Raw SQLite pages and retained source contents were not dumped.
- Vendor/runtime source in `node_modules`, `.runtime`, and `backend/.venv` was not read file by file.
- Binary geometry was validated structurally and byte-for-byte, but individual vertices were not manually analyzed.

### 2.3 Commands and checks executed

```sh
npm run check
npm run build
npm run test:backend
```

Additional one-off, isolated checks validated:

- FastAPI application construction.
- An end-to-end record lifecycle in a temporary directory.
- Atlas manifest references, chunk sizes, geometry offsets, gzip decoding, and production asset copies.
- Redacted current configuration readiness.
- Existing data counts and file permissions.
- The zero-finding approval failure.

### 2.4 Audit effects

- No authored source code was changed.
- No existing user/synthetic record was changed.
- Temporary smoke-test data was automatically removed.
- `npm run build` regenerated `dist/` from the current source.
- `PROJECT_AUDIT.md` is the only authored file added by the audit.
- The workspace is not a Git repository (`.git` is absent), so generated-output differences cannot be inspected or reverted through Git.

## 3. Verification results

### 3.1 Frontend type check

`npm run check` completed successfully using `tsc --noEmit`.

**Result:** Pass.

### 3.2 Production build

`npm run build` completed successfully with Vite 8.3.1.

Generated primary assets:

| Asset | Size | Gzip size |
|---|---:|---:|
| `dist/index.html` | 1.26 kB | 0.65 kB |
| `dist/assets/index-BoiEuvzo.css` | 66.74 kB | 13.81 kB |
| `dist/assets/index-DDfLn_V6.js` | 766.27 kB | 209.45 kB |

**Result:** Pass with a warning that the JavaScript chunk exceeds 500 kB. Code splitting is not currently configured.

### 3.3 Backend tests

`npm run test:backend` produced:

- **82 tests passed**.
- **2 subtests passed**.
- Runtime: approximately 5.9 seconds in the final audit run.
- One dependency warning: Starlette's existing `httpx` TestClient integration is deprecated in favor of `httpx2`.

**Result:** Pass.

### 3.4 Isolated end-to-end API smoke test

The test used a temporary data directory and disabled both external providers. It did not touch `.bodybrain`.

Verified steps:

1. Application health returned `ok`.
2. A text medical record was imported.
3. `Report date: 2026-09-20` was extracted correctly.
4. Two anatomical findings were generated.
5. The original source could be downloaded.
6. A selected finding was approved.
7. The approved record transitioned to `memory_status=unconfigured`, correctly reflecting disabled Cognee.
8. Local chat returned one exact-source citation.
9. The approved record appeared on the timeline.
10. Reimporting identical content returned the existing record.
11. Only one record existed in the temporary store after deduplication.
12. The temporary data was removed.

**Result:** Pass.

### 3.5 Anatomy asset integrity

Validated all shipped atlas assets:

- 15 model chunks.
- 2,234 modeled parts.
- 3,432 atlas concepts.
- 59,546,744 raw binary bytes.
- 32,956,129 compressed binary bytes.
- Every `.bin.gz` decoded exactly to its corresponding `.bin`.
- Every positions, normals, and indices range stayed within its declared chunk boundary.
- `dist/models` matched `public/models` after the production build.

**Result:** Pass.

## 4. Current checkout readiness

### 4.1 Application and security configuration

| Signal | Current state |
|---|---|
| FastAPI application import | Pass |
| User API token | Not configured |
| Agent callback token | Not configured |
| Token collision | No collision |
| Allowed hosts | `localhost`, `127.0.0.1`, `testserver` |
| Non-local host enabled | No |

The tokenless configuration is acceptable only for the documented loopback, single-user model. It must not be exposed to a network-accessible hostname without authentication and TLS.

### 4.2 Cognee

| Signal | Current state |
|---|---|
| Mode | `disabled` |
| Adapter configured | No |
| Cognee credential present | Yes, value not inspected |
| Live connectivity | Not probed |

A credential alone does not activate Cognee. With the current mode, approval preserves records locally but does not index them into Cognee.

### 4.3 ClawMax

| Signal | Current state |
|---|---|
| Ingestion workflow configured | No |
| Evidence workflow configured | No |
| Agent callback token configured | No |
| Fully configured | No |
| Live connectivity | Not probed |

No ClawMax workflow can run successfully in the current configuration.

### 4.4 Current persisted state

Only sanitized metadata was inspected.

| Item | Current state |
|---|---:|
| Records | 3 |
| Approved records | 1 |
| Pending-review records | 2 |
| `memory_status=unconfigured` | 1 |
| `memory_status=not_indexed` | 2 |
| Visible runs | 4 |
| Retained source files | 3 |

The records are the explicitly fictional demo data defined in `backend/bodybrain/demo.py`.

### 4.5 Current filesystem permissions

| Path/type | Mode | Assessment |
|---|---|---|
| `.bodybrain/` | `0755` | Too broad for sensitive data |
| `.bodybrain/bodybrain.sqlite3` | `0644` | Group/world-readable; privacy defect |
| `.bodybrain/sources/*` | `0600` | Appropriate |
| `.env` | `0600` | Appropriate |

## 5. Product architecture

```text
index.html
  -> src/main.tsx
     -> src/App.tsx
        |-- fetch /models/atlas.json
        |-- src/anatomy/scene.tsx
        |     -> 15 .bin.gz or .bin chunks
        |     -> Three.js rendering and picking
        |-- browser localStorage notes/bookmarks/theme
        `-- src/BackendPanel.tsx
              -> src/backend-api.ts
              -> /api/* through Vite proxy

FastAPI backend/bodybrain/main.py:create_app
  -> Settings
  -> Service
     |-- Store -> SQLite JSON records/runs/tasks
     |-- original source files
     |-- Anatomy -> atlas IDs and conservative matching
     |-- in-memory Cognee index queue
     `-- ClawMax task snapshots and execution polling
  -> CogneeMemory -> disabled, REST, or local SDK mode
  `-- ClawMaxClient -> workflow trigger and execution APIs

ClawMax worker, when configured
  -> receives opaque task ID
  -> calls authenticated /api/agent/* endpoints
  -> submits exact quotes and concept IDs
  `-> backend validates every callback against local sources
```

### 5.1 Frontend layers

- `index.html` applies the saved light/dark theme before React mounts.
- `src/main.tsx` mounts the application.
- `src/App.tsx` owns atlas loading, regions, systems, visibility, views, selection, help/credits, and browser-only notes/bookmarks.
- `src/anatomy/scene.tsx` loads binary model chunks, builds merged render geometry and part-level picking meshes, handles camera/input/explosion layout, and manages GPU cleanup.
- `src/BackendPanel.tsx` implements record import/review, local/agent chat, timeline, and workflow activity.
- `src/backend-api.ts` contains frontend API contracts and a 120-second JSON fetch wrapper.

### 5.2 Backend layers

- `backend/bodybrain/main.py` is the ASGI/API entry point and security boundary.
- `backend/bodybrain/service.py` implements record creation, source retention, indexing, task dispatch, and execution refresh.
- `backend/bodybrain/db.py` provides the SQLite repository.
- `backend/bodybrain/ingestion.py` validates and parses PDF/TXT/Markdown sources.
- `backend/bodybrain/anatomy.py` performs conservative atlas matching.
- `backend/bodybrain/evidence.py` verifies and ranks approved exact quotations.
- `backend/bodybrain/cognee_memory.py` implements optional Cognee REST/SDK indexing and recall.
- `backend/bodybrain/clawmax.py` implements optional ClawMax workflow submission and execution polling.
- `backend/bodybrain/demo.py` defines the three fictional demo records.

## 6. Primary workflows

### 6.1 Startup and request boundary

1. `Settings` loads the root `.env` without overriding process-level variables.
2. `create_app` rejects non-local hosts unless a user API token is configured.
3. It rejects equal user and agent tokens.
4. Trusted-host and explicit-origin middleware are applied.
5. Non-agent `/api/*` routes require the user token when configured.
6. `/api/agent/*` routes independently require the agent token.
7. Responses receive `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`.
8. One in-process Cognee index worker starts during lifespan.
9. Approved records left with `memory_status=pending` are requeued after restart.

### 6.2 3D anatomy

1. The frontend loads `public/models/atlas.json`.
2. Three model chunks are downloaded concurrently.
3. Gzip is used when the browser supports `DecompressionStream`; raw files are the fallback.
4. Byte lengths are verified before typed-array views are created.
5. Geometry is merged by anatomical system for rendering.
6. Individual meshes remain available for exact picking.
7. GPU textures drive part visibility, offsets, and selection highlighting.
8. Orbit, pan, zoom, keyboard, mouse, touch, isolation, labels, and exploded card layout are supported.
9. WebGL, geometry, textures, materials, listeners, and DOM additions are disposed on unmount.

### 6.3 Browser-only quick notes

- Theme key: `bodybrain.theme`.
- Notes key: `bodybrain.memories.v1`.
- Bookmarks key: `bodybrain.bookmarks.v1`.
- Notes can be exported as JSON.
- Notes/bookmarks have no account, synchronization, backend copy, or relationship to reviewed records.

### 6.4 Record ingestion and review

1. The UI submits a file or pasted text.
2. The backend limits uploads to 10 MB.
3. PDF/TXT/Markdown validation and parsing run in a threadpool.
4. PDF limits include 100 pages and 150,000 extracted characters.
5. Scanned/image-only PDFs are rejected because OCR is not implemented.
6. Only explicitly labeled ISO dates are inferred automatically.
7. Record identity hashes original bytes, record type, and explicitly supplied event date.
8. Conservative anatomical mentions are extracted without diagnostic inference.
9. Original bytes are saved as `.bodybrain/sources/<record-id>` with mode `0600`.
10. Record state and extracted text/pages/findings are stored in SQLite.
11. The record remains `pending_review` until a user selects at least one finding.
12. Every selected quote is reverified against its original page during approval.
13. Approved records become eligible for local evidence and optional Cognee indexing.

### 6.5 Cognee indexing and recall

When enabled:

1. Only approved findings are included in the indexed document.
2. Stable BodyBrain source markers are repeated through the text to preserve provenance after chunking.
3. REST mode requires both add and cognify operations to produce explicit completed pipeline records.
4. SDK mode uses a lazily loaded, optional `cognee==1.6.1` installation.
5. Operations are serialized because SDK configuration and embedded data are process-global.
6. Recall is restricted to the configured dataset and CHUNKS search.
7. Returned IDs are intersected with approved local record IDs.
8. Cognee results can nominate candidates but cannot create or authorize evidence.

### 6.6 ClawMax ingestion

When enabled:

1. BodyBrain stores a local task and workflow run.
2. The trigger body sends only an opaque task ID.
3. The worker retrieves task content from authenticated `/api/agent/*` routes.
4. Record content is treated as untrusted input.
5. The agent submits exact page quotations and optional atlas concept IDs.
6. The backend rejects wrong pages, missing quotes, unknown concepts, repeated callbacks, or modifications after human review.
7. Valid agent findings remain unapproved until human review.
8. A terminal ClawMax execution without a validated BodyBrain callback is considered failed.

### 6.7 Chat and evidence

1. Chat considers only approved records and approved findings.
2. Cognee candidate retrieval is attempted only when configured.
3. Retrieval failures visibly fall back to local evidence.
4. Exact quotations are reverified against stored pages.
5. Citations are ranked by lexical/provider relevance and deduplicated.
6. Causal, diagnostic, and dosage language receives a caution.
7. Local answers are rendered entirely from verified quotations.
8. Optional ClawMax evidence tasks receive a frozen snapshot of approved evidence.
9. Agent citations must exist in that snapshot and still exist in the approved local record.
10. Agent prose is retained as `agent_draft`, but the displayed verified answer is rebuilt from exact quotations.

## 7. Verified working functionality

| Capability | Status | Evidence |
|---|---|---|
| TypeScript correctness | Working | `npm run check` |
| Production frontend compilation | Working | `npm run build` |
| Backend automated suite | Working | 82 tests + 2 subtests |
| FastAPI app construction | Working | Current config import and isolated smoke test |
| SQLite schema and persistence | Working | Automated tests and current store inspection |
| Text import | Working | Isolated smoke test |
| PDF/TXT validation paths | Working in backend tests | Existing ingestion/API tests |
| Explicit date extraction | Working | Isolated smoke test and tests |
| Conservative anatomy matching | Working | Isolated smoke test and tests |
| Original-source retention/download | Working | Isolated smoke test |
| Human approval | Working for records with findings | Isolated smoke test and tests |
| Exact-source quote verification | Working | Evidence/API/provider-flow tests |
| Local cited chat | Working | Isolated smoke test |
| Timeline | Working | Isolated smoke test and tests |
| Duplicate detection | Working as implemented | Isolated smoke test and tests |
| Restart-safe pending Cognee state | Working in tests | Provider-flow tests |
| Agent callback authorization | Working in tests | API/provider-flow tests |
| Agent quote/snapshot validation | Working in tests | Evidence/provider-flow tests |
| Cognee adapter contract | Working with fake/mock providers | Cognee tests |
| ClawMax adapter contract | Working with fake/mock providers | ClawMax/provider-flow tests |
| Atlas manifest/model integrity | Working | Full chunk validator |
| Gzip fallback data | Working structurally | Full gzip round-trip validation |
| Production model copy | Working | `public`/`dist` byte comparison |

## 8. Functionality unavailable in this checkout

### 8.1 Cognee-backed permanent memory

Cognee is disabled. Therefore:

- Approval does not index into Cognee.
- Cognee semantic retrieval is unavailable.
- Records remain usable through local exact-quote evidence.
- The configured credential has no effect until the mode and endpoint/SDK are configured correctly.

### 8.2 ClawMax agent workflows

ClawMax is unconfigured. Therefore:

- Imports use only local extraction.
- Chat uses local/Cognee evidence logic without a ClawMax evidence callback.
- No ClawMax activity or agent completion can be observed.
- A worker cannot authenticate because no callback token is configured.

### 8.3 Production service

The repository provides development commands and a static frontend build, but no production process manager, container, reverse proxy, TLS setup, hosted authentication, deployment manifest, monitoring, backup, or static+API packaging.

## 9. Confirmed functional defects

### 9.1 Valid zero-finding records cannot be approved — reproduced

**Severity:** High<br>
**Files:** `backend/bodybrain/service.py`, `backend/bodybrain/main.py`, `src/BackendPanel.tsx`

A valid short non-anatomical record (`Brief note.`) produced zero findings. Approval returned HTTP 422:

```text
Choose at least one valid finding to approve
```

The record remains permanently `pending_review`.

Cause:

- Fallback passages are created only when no anatomy is found.
- Each fallback line must contain between 20 and 2,000 characters.
- If no line qualifies, `findings=[]`.
- The API and UI require at least one finding for approval.

This contradicts the user-facing claim that an unmapped source can still be reviewed and saved.

### 9.2 File-upload event date is not forwarded

**Severity:** Medium<br>
**Files:** `src/BackendPanel.tsx`, `src/backend-api.ts`, `backend/bodybrain/main.py`

The backend multipart endpoint supports `event_date`, but the UI calls:

```ts
backend.upload(file, title, recordType)
```

The date control is shown only for pasted text. File users must rely on a labeled ISO date in the document or call the API directly.

### 9.3 Selected anatomy does not scope chat

**Severity:** Medium<br>
**Files:** `src/BackendPanel.tsx`, `src/backend-api.ts`, `backend/bodybrain/main.py`

The backend supports `Question.concept_id`, but the frontend invokes `backend.chat(asked)` without a concept. Selecting a structure in the atlas therefore does not constrain evidence retrieval.

### 9.4 Record polling can continue after agent extraction is done

**Severity:** Medium<br>
**File:** `src/BackendPanel.tsx`

`hasPending` treats every `pending_review` record as background work whenever ClawMax is configured. A ClawMax extraction correctly leaves the record pending for human review, so polling can continue for two minutes and then incorrectly report that background work is still pending.

### 9.5 A new question stops automatic polling for older agent answers

**Severity:** Medium<br>
**File:** `src/BackendPanel.tsx`

When a new question is submitted, prior `pending` exchanges are changed to `waiting`. Their later valid results are not automatically applied until polling is manually resumed through Refresh.

### 9.6 Activity history can appear contradictory

**Severity:** Low/Medium<br>
**Files:** `backend/bodybrain/service.py`, `backend/bodybrain/main.py`

Approval creates a new completed `human_review` run but does not update the original `record_ingestion` run from `awaiting_review`. The activity view can show both states at once.

### 9.7 Global `ValueError` handler masks unrelated failures

**Severity:** Medium<br>
**File:** `backend/bodybrain/main.py`

Every `ValueError` is translated into a generic HTTP 409 saying the record changed. Programming, configuration, or provider errors that happen to use `ValueError` can therefore be misreported as optimistic-review conflicts.

### 9.8 Duplicate identity ignores title and filename

**Severity:** Low/Medium<br>
**File:** `backend/bodybrain/service.py`

The digest uses bytes, record type, and explicitly supplied date, but not title or filename. Two legitimately distinct records with identical content/type/date but different titles or filenames reuse the first record.

### 9.9 Agent UI label can imply more synthesis than is displayed

**Severity:** Low<br>
**Files:** `backend/bodybrain/main.py`, `src/BackendPanel.tsx`

The label `ClawMax · source verified` appears after completion, but ClawMax prose is not shown. The backend stores it as `agent_draft` and reconstructs the visible answer from citations. This is a sound safety design, but the label may overstate the displayed agent contribution.

## 10. Functional constraints and product gotchas

1. When any anatomy finding exists, unrelated non-anatomical passages are not offered as fallback findings. Medication, activity, treatment, or clinician-discussion text may therefore never enter approved memory.
2. The system is anatomy-mention recall, not general document RAG.
3. Extraction caps findings at 150 without a user-visible truncation warning.
4. Approved records cannot be remapped or reprocessed.
5. Identical import deduplication returns the original record even if the new title is different.
6. Scanned/image-only PDFs are rejected because OCR is absent.
7. Quick notes and bookmarks are browser-only and are not part of reviewed memory.
8. The `/api/integrations`, `/api/summary`, and manual `/api/records/{id}/process` capabilities have no frontend controls.
9. `DEFAULT_VISIBLE` in `src/anatomy/anatomy.ts` appears unused; `App.tsx` maintains a separate default-system list.
10. ClawMax provider execution completion is not considered task success without a valid BodyBrain callback.
11. Cognee HTTP success alone is not considered successful indexing without completed add and cognify pipeline records.

## 11. Unimplemented roadmap items

The following items appear in `idea` or surrounding product material but have no runtime implementation:

- DICOM ingestion or raw medical-image interpretation.
- Patient-specific anatomy or scan-to-model reconstruction.
- OCR for scanned documents.
- FHIR integration.
- EHR/health-system connectors.
- Strava, wearables, gym, and fitness connectors.
- Medication and prescription entities.
- Clinician entities and relationships.
- Injury episodes and recovery models.
- MONAI integration.
- Full graph traversal beyond optional Cognee retrieval.
- Doctor-sharing workflows.
- Emergency summaries.
- Accounts, multi-user support, or cross-device synchronization.
- Record deletion.
- Provider-side deletion.
- Data-retention configuration.
- Corrections/versioning after approval.
- Backup, restore, or repair tooling.
- Production deployment and observability.

## 12. Security and privacy findings

### 12.1 Positive controls

- Hosted/non-local allowed hosts require a user API token.
- User and agent tokens must be distinct.
- User and agent routes use separate authentication boundaries.
- Origin and trusted-host checks are present.
- Sensitive API responses use `Cache-Control: no-store`.
- Responses include `X-Content-Type-Options: nosniff`.
- Source files are saved with mode `0600`.
- ClawMax triggers receive opaque task IDs instead of record content.
- Provider redirects are disabled.
- Provider clients avoid ambient proxy/environment trust where applicable.
- Provider errors are redacted before reaching users.
- Exact local sources and human approval remain authoritative.

### 12.2 SQLite and directory permissions

The current SQLite file is `0644` and `.bodybrain` is `0755`. On a multi-user machine, another local account may be able to read complete extracted record text, pages, findings, and tasks from SQLite.

Recommended target:

- `.bodybrain`: `0700`.
- `bodybrain.sqlite3`: `0600`.
- `sources/*`: retain `0600`.
- Enforce modes in application initialization, not only through manual shell commands.

### 12.3 No deletion or retention controls

There is no supported path to delete:

- A record.
- Its retained source file.
- Runs/tasks.
- Cognee-indexed content.
- ClawMax task snapshots.

This is a major privacy and correction limitation for personal health information.

### 12.4 Provider disclosure scope

Once ClawMax is configured:

- Import automatically dispatches pending records without a per-import consent prompt.
- The worker/model can retrieve complete pending record content.
- Evidence tasks snapshot all approved findings unless a concept filter is supplied.
- Because the current frontend does not supply `concept_id`, evidence snapshots can be broader than necessary.

### 12.5 Local-only trust assumption

The current API token is empty, but allowed hosts remain local. Requests without an `Origin` are accepted. This is reasonable only for a trusted, local, single-user process; it is not a multi-user authorization model.

### 12.6 External font request

`src/styles.css` imports Google Fonts. This creates a runtime request that can disclose the user's IP address, weakens offline behavior, and may conflict with a strict Content Security Policy.

## 13. Reliability and performance findings

1. The production JS bundle is 766.27 kB and triggers Vite's large-chunk warning.
2. The frontend keeps 2,234 individual picking meshes in addition to merged render geometry.
3. Hover raycasting can test many visible parts, although it is throttled.
4. Lower-end mobile GPU/CPU performance has not been measured.
5. Anatomy extraction applies thousands of atlas-name regular expressions to passages up to 150,000 characters.
6. Parsing runs in a threadpool but can still consume substantial CPU under concurrent uploads.
7. A pathological 10 MB PDF may be expensive despite page/text limits; there is no parser timeout or malware scan.
8. Background dispatch jobs are discarded from `service.jobs` when done without always retrieving unexpected exceptions.
9. SQLite stores most domain state in denormalized JSON blobs.
10. There is no schema version, migration system, backup/repair tooling, or JSON-query indexing.
11. Runs are returned with a hard limit of 100 rather than pagination.
12. Embedded Cognee assumes one application process/worker.
13. Cognee foreground operations serialize and may take up to 120 seconds.
14. ClawMax/Cognee API drift fails safely but disables integrations.

## 14. Test coverage findings

### 14.1 Existing backend coverage

Five backend test modules cover:

- API/import/review/authentication behavior.
- ClawMax request/response and redaction contracts.
- Cognee disabled/REST/SDK behavior.
- Exact-evidence selection and chronology.
- Provider lifecycle, callbacks, snapshots, retry/resume, and polling.

The full suite currently passes.

### 14.2 Missing frontend coverage

There are no frontend unit, component, browser, visual-regression, or end-to-end tests for:

- Atlas download/decoding in a browser.
- WebGL rendering and device compatibility.
- Picking, orbit, pan, zoom, touch, and keyboard controls.
- Exploded layout.
- Browser note/bookmark persistence.
- Review and mapping UI.
- Chat polling.
- Responsive layouts.
- Accessibility and focus management.

### 14.3 Missing backend/integration coverage

Notable missing coverage includes:

- Explicit 10 MB upload-boundary test.
- Explicit 100-page and 150,000-character boundary tests.
- Deletion/retention/migration tests because those features do not exist.
- Crash recovery between source-file and SQLite writes.
- Filesystem permission assertions.
- Concurrent import/review stress tests.
- Direct tests of the ClawMax CLI helper.
- Installation of the packaged ClawMax organization/skill bundle.
- Live Cognee and ClawMax credentials, permissions, models, and callback networking.
- Large-atlas performance in actual browsers/devices.

## 15. Documentation, licensing, and dependency findings

### 15.1 Documentation roles

- `README.md` is the main local setup and product-scope guide.
- `backend/README.md` documents API lifecycle, limits, auth boundaries, and providers.
- `idea` is a broad product vision and is not executable specification.
- `Personal Agent Hackathon` is event/product context.
- `links_for_project_dev` contains external research links.
- Integration README files document Cognee and ClawMax setup/contracts.

### 15.2 Licensing

- `HUMAN_ATLAS_LICENSE` contains the upstream Human Atlas MIT notice.
- `public/ATTRIBUTION.md` attributes BodyParts3D data under CC BY 4.0.
- `dist/` includes dataset attribution but does not appear to include `HUMAN_ATLAS_LICENSE`.
- The repository has no clearly identified license for BodyBrain's original code.

Whether the upstream MIT notice must be copied into every distribution should be reviewed before release. This report is a technical observation, not legal advice.

### 15.3 Main dependency baseline

Frontend direct versions from the lockfile include:

- React / React DOM 19.2.6.
- Three.js 0.159.0.
- Lucide React 1.31.0.
- Vite 8.3.1.
- TypeScript 5.9.3.
- Vite React plugin 6.0.2.

Backend lock versions include:

- Python 3.12 project baseline (`>=3.12,<3.14`).
- FastAPI 0.141.1.
- Starlette 1.7.0.
- Uvicorn 0.54.0.
- HTTPX 0.28.1.
- Pydantic 2.13.5.
- pypdf 6.19.0.
- python-dotenv 1.2.3.
- python-multipart 0.0.32.
- pytest 9.1.1.
- pytest-asyncio 1.4.0.

The optional Cognee SDK is deliberately outside the core lock and should be installed at exactly `cognee==1.6.1` when SDK mode is selected. A later `uv sync` may remove it.

## 16. File responsibility map

### 16.1 Root/configuration

| Path | Responsibility |
|---|---|
| `README.md` | Product scope, local setup, privacy and limitations |
| `idea` | Broad future product vision |
| `Personal Agent Hackathon` | Hackathon context |
| `links_for_project_dev` | Research/development links |
| `HUMAN_ATLAS_LICENSE` | Upstream Human Atlas MIT notice |
| `.env.example` | Safe environment-variable contract |
| `.gitignore` | Excludes secrets, local data, dependencies, builds, runtimes, and caches |
| `package.json` | Frontend/backend developer commands and Node dependencies |
| `package-lock.json` | Reproducible npm dependency graph |
| `backend/pyproject.toml` | Python package, dependencies, and pytest settings |
| `backend/uv.lock` | Reproducible Python dependency graph |
| `tsconfig.json` | Strict TypeScript configuration |
| `vite.config.ts` | React plugin and `/api` proxy/auth injection |
| `index.html` | HTML entry and early theme bootstrap |
| `scripts/dev.mjs` | Combined Uvicorn/Vite development launcher |

### 16.2 Frontend

| Path | Responsibility |
|---|---|
| `src/main.tsx` | React entry point |
| `src/App.tsx` | Main atlas application and browser-local state |
| `src/BackendPanel.tsx` | Record, review, chat, timeline, and activity workspace |
| `src/backend-api.ts` | API types and HTTP client |
| `src/body-regions.ts` | Curated body regions and featured concepts |
| `src/anatomy/anatomy.ts` | Anatomy systems, colors, manifest and scene types |
| `src/anatomy/scene.tsx` | Complete Three.js model/render/input lifecycle |
| `src/anatomy/model-download.ts` | Safe compressed/raw model decoding |
| `src/anatomy/pointer-tap.ts` | Pointer gesture/tap classifier |
| `src/anatomy/explosion-layout.ts` | Exploded-view shelf packing |
| `src/styles.css` | Main layout/component styles |
| `src/themes.css` | Light theme and responsive overrides |
| `src/backend.css` | Backend workspace styles |

### 16.3 Backend

| Path | Responsibility |
|---|---|
| `backend/bodybrain/config.py` | Environment-backed immutable settings |
| `backend/bodybrain/main.py` | API composition, routes, auth, review and callback validation |
| `backend/bodybrain/service.py` | Record/index/task lifecycle |
| `backend/bodybrain/db.py` | SQLite schema and repository |
| `backend/bodybrain/ingestion.py` | PDF/TXT/Markdown parsing and explicit date extraction |
| `backend/bodybrain/anatomy.py` | Atlas search and conservative mention extraction |
| `backend/bodybrain/evidence.py` | Approved exact-quote retrieval and rendering |
| `backend/bodybrain/cognee_memory.py` | Optional Cognee REST/SDK adapter |
| `backend/bodybrain/clawmax.py` | Optional ClawMax adapter |
| `backend/bodybrain/demo.py` | Fictional demo records |
| `backend/bodybrain/__init__.py` | Package declaration |

### 16.4 Tests and integrations

| Path | Responsibility |
|---|---|
| `backend/tests/test_api.py` | API, ingestion, state, auth, demo and PDF behavior |
| `backend/tests/test_clawmax.py` | ClawMax adapter contracts and safe failures |
| `backend/tests/test_cognee_memory.py` | Cognee adapter contracts and normalization |
| `backend/tests/test_evidence.py` | Evidence authorization, ranking, chronology and privacy |
| `backend/tests/test_provider_flow.py` | Full lifecycle with fake providers and real temporary SQLite |
| `integrations/cognee/README.md` | Cognee setup and provenance contract |
| `integrations/clawmax/README.md` | ClawMax setup and callback contract |
| `integrations/clawmax/SKILLS/custom/bodybrain/SKILL.md` | Shared agent workflow and safety instructions |
| `integrations/clawmax/SKILLS/custom/bodybrain/scripts/bodybrain_client.py` | Restricted authenticated worker CLI |
| `integrations/clawmax/WORKFLOWS/*` | Ingestion and evidence workflow prompts |
| `integrations/clawmax/TEMPLATES/organizations/bodybrain/template.json` | Two-agent/two-workflow organization template |
| `integrations/clawmax/TEMPLATES/organizations/bodybrain/agents/*` | Agent identities, constraints, and tool policies |

## 17. API surface

The backend exposes 21 routes grouped as follows:

### Health and integrations

- `GET /api/health`
- `GET /api/integrations`

### Records and review

- `GET /api/records`
- `POST /api/records`
- `POST /api/records/text`
- `GET /api/records/{record_id}`
- `GET /api/records/{record_id}/source`
- `PATCH /api/records/{record_id}/mapping`
- `POST /api/records/{record_id}/approve`
- `POST /api/records/{record_id}/index`
- `POST /api/records/{record_id}/process`

### Retrieval and activity

- `GET /api/anatomy/search`
- `GET /api/timeline`
- `POST /api/chat`
- `GET /api/summary`
- `POST /api/demo`
- `GET /api/runs`
- `GET /api/tasks/{task_id}`

### Authenticated agent worker

- `GET /api/agent/anatomy`
- `GET /api/agent/tasks/{task_id}`
- `POST /api/agent/tasks/{task_id}/result`

## 18. Setup and operation

### 18.1 Requirements

- Node.js 22.13 or newer.
- Python 3.12 (project permits `<3.14`).
- `uv` for Python environment management.

### 18.2 Initial setup

```sh
npm install
uv sync --project backend --python 3.12 --frozen
cp .env.example .env   # only if .env does not already exist
```

Never overwrite an existing `.env`.

### 18.3 Development

```sh
npm run dev
```

Expected endpoints:

- UI: `http://127.0.0.1:3016`
- API: `http://127.0.0.1:8080`
- OpenAPI docs: `http://127.0.0.1:8080/docs`

Separate processes:

```sh
npm run backend
npm run dev:ui
```

### 18.4 Validation

```sh
npm run check
npm run build
npm run test:backend
```

### 18.5 Preview

```sh
npm run preview
```

The backend must be started separately when previewing the static frontend.

## 19. Environment variable contract

Names used by the repository include:

```text
BODYBRAIN_DATA_DIR
BODYBRAIN_API_TOKEN
BODYBRAIN_AGENT_TOKEN
BODYBRAIN_BACKEND_URL
BODYBRAIN_ALLOWED_HOSTS
BODYBRAIN_ALLOWED_ORIGINS
COGNEE_MODE
COGNEE_URL
COGNEE_API_KEY
COGNEE_BEARER_TOKEN
COGNEE_DATASET
CLAWMAX_URL
CLAWMAX_TOKEN
CLAWMAX_INGEST_WORKFLOW_ID
CLAWMAX_EVIDENCE_WORKFLOW_ID
LLM_API_KEY
```

Notes:

- `BODYBRAIN_BACKEND_URL` belongs to the separate ClawMax worker runtime, not backend `Settings`.
- User and agent tokens must be distinct.
- Cognee API-key and bearer-token authentication must not be configured simultaneously.
- Model-provider variables are consumed by Cognee/agent runtimes rather than directly by BodyBrain's core backend.

## 20. Generated, runtime, and persisted artifacts

- `public/models/`: atlas manifest plus 15 raw and 15 gzip chunks; approximately 93.8 MB total.
- `dist/`: generated production UI and copied atlas assets; regenerated during this audit.
- `node_modules/`: installed npm dependencies and Vite caches; vendor/generated.
- `.runtime/`: uv-managed CPython 3.12.11 for macOS arm64; generated.
- `backend/.venv/`: Python virtual environment; generated.
- `backend/.pytest_cache/`, `__pycache__/`: generated test/import caches.
- `.bodybrain/bodybrain.sqlite3`: private application database.
- `.bodybrain/sources/`: retained original source bytes.

Generated/vendor directories are not authoritative source and should remain ignored by version control unless distribution requirements explicitly say otherwise.

## 21. Prioritized action plan

### P0 — security and blocking correctness

1. Enforce `0700` on `.bodybrain` and `0600` on SQLite at creation/startup.
2. Fix zero-finding records so every accepted record has an approvable source passage, or add a deliberate source-only approval state.
3. Design deletion, correction/versioning, retention, and provider-cleanup workflows before real personal health data is used.
4. Add explicit per-import consent before sending record content to an external agent/model.

### P1 — activate the intended product and repair workflows

5. Configure and safely validate Cognee indexing/recall.
6. Configure ClawMax workflows, callback token, worker networking, and models.
7. Forward `event_date` for file uploads.
8. Pass selected `concept_id` into chat.
9. Correct record and chat polling state machines.
10. Reconcile the ingestion activity run when review completes.
11. Narrow the global `ValueError` handler to real state-conflict exceptions.
12. Restrict evidence task snapshots to locally relevant records before external disclosure.

### P2 — quality and production readiness

13. Add frontend component and browser end-to-end tests.
14. Add upload/page/text boundary and filesystem-permission tests.
15. Code-split the frontend bundle.
16. Benchmark the 3D viewer on mobile and low-end devices.
17. Add schema migrations, backup/restore, and pagination.
18. Self-host fonts or remove the external font request.
19. Add production TLS, authentication, deployment, monitoring, and secrets management.
20. Clarify BodyBrain's original-code license and include all required upstream notices in distributions.

## 22. Final assessment

### Ready now

- Local development and production compilation.
- Interactive-atlas code and validated model assets.
- Local record import, review, persistence, timeline, and exact-source chat.
- Synthetic demonstrations.
- Backend contract tests for provider integrations.

### Not ready now

- Live Cognee memory.
- Live ClawMax workflows.
- Production or multi-user deployment.
- Real sensitive health data on a multi-user machine with current permissions.
- General-purpose personal-health memory beyond approved anatomical passages.
- The broader digital-twin roadmap described in `idea`.

### Overall

The repository is a coherent and unusually careful evidence-grounded prototype. Its core local workflow works and is well covered by backend tests. The principal gap is between the implemented local prototype and the advertised persistent personal-agent experience: both optional providers are inactive, important privacy lifecycle operations are absent, and several frontend workflow defects remain. Addressing the P0 items should precede use with real records; P1 is required to demonstrate the intended hackathon agent/memory experience.

## 23. First remediation batch — September 27, 2026

### 23.1 Implemented repairs

| Issue | Resolution |
|---|---|
| Decimal/line-wrap extraction could detach negation | Exact source passages preserve decimals, abbreviations, wrapped lines, and their surrounding context. Long passages remain whole. Ingestion callbacks must return complete passages, not detached substrings. |
| Accepted records with no findings could never be approved | Every nonempty accepted source gets reviewable passages, including one-character notes. Startup repairs existing pending drafts with empty findings without rewriting reviewed records or existing mapping edits. |
| Non-anatomical context disappeared when anatomical mentions existed | Other source passages are included as unmapped review choices beside anatomical findings. Only selected/approved passages enter recall. |
| Extraction limits silently omitted material | Long passages and findings beyond the 150-item cap produce visible warnings; the original source remains intact. |
| SQLite/directories were too broadly readable | POSIX startup enforces `0700` data/source directories and `0600` database, sidecar, and source files. Database/source files are private before their first write. Existing checkout permissions were also repaired without reading or changing record contents. |
| File import omitted explicit dates | File and text forms both expose the date and send it to the API. Submission captures the native date field through FormData; browser verification caught and resolved an input-event synchronization issue. |
| Atlas selection did not scope chat | Selected anatomy is sent as `concept_id` for chat and timeline, with visible scope and an explicit all-records option. Prior exchanges retain their original scope label. |
| Closing the workspace discarded conversation/drafts | The lazily loaded workspace stays mounted after first opening. Native dialog visibility is controlled separately, preserving chat, drafts, and review selections during atlas navigation. This is tab-lifetime state, not persistence across page reloads. |
| Review state was incorrectly treated as background work | Record polling follows actual workflow/indexing states; waiting for human review alone does not keep it active. |
| A new question stopped older task polling | Independent pending exchanges keep receiving their own results. Invalid/unverified agent results do not replace local evidence. |
| Original ingestion activity remained awaiting review | Approval, startup reconciliation, and indexing success/failure reconcile the original run. Human review and Cognee progress have separate step states. |
| All ValueErrors appeared as review conflicts | Only the dedicated `StateConflict` exception maps to HTTP 409; unrelated errors are no longer mislabeled. |
| Configured ClawMax automatically received imports/questions | `allow_agent` defaults to false for text/file imports, chat, and demo loading. The UI offers separate per-operation opt-ins, gated by the relevant configured workflow and worker callbacks. Explicit `/process` requests remain an intentional dispatch operation. |
| Evidence snapshots included unrelated approved findings | Tasks contain only the relevant approved citations selected for the question and optional anatomy scope. No matching evidence means no agent dispatch. |
| Diagnostic caution pattern missed normal words | Diagnosis/diagnosed/diagnose and related forms are now recognized by the existing caution mechanism. |
| Agent label suggested displayed generated prose | The UI labels the contribution as ClawMax citation selection with verified quotes. |
| Workspace was bundled into initial atlas JS | Records workspace JS/CSS now load separately. The atlas bundle itself still triggers the existing large-chunk warning. |
| Test collection could initialize the normal data directory | `npm run test:backend` now uses temporary storage, disables dotenv and provider settings, and cleans up its temporary directory. |

### 23.2 Fresh verification

- `npm run test:backend`: **159 passed, 2 subtests passed**. One existing Starlette/httpx deprecation warning remains.
- `npm run test:frontend`: **5 passed**, covering API payloads/dates/consent/scope and asynchronous evidence state. Node reports its experimental type-stripping notice on the installed runtime.
- TypeScript checking: passed.
- Production frontend build: passed; the existing atlas/main bundle size warning remains.
- New backend tests cover source-context regressions, complete-quote validation, short/unmapped record approval, startup repair, per-operation provider consent, relevant-only snapshots, review status reconciliation, private initial file creation, existing-file permission repair, exception classification, and upload/PDF/text boundaries.
- Isolated browser smoke test on UI port 3017/API port 8081, with temporary data and both providers disabled: imported and approved a two-character note, recalled it with a citation, preserved drafts and conversation across workspace close/reopen, applied anatomy scope to chat/timeline, restored the all-records timeline, and verified a saved explicit date alongside the full negated decimal-containing passage. Review layout was inspected visually.
- No live provider requests were made. Existing record contents, credentials, and the already-running user API process were not changed. Local data permissions were tightened to the target modes.

### 23.3 Operational notes and remaining work

- Restart the existing backend process to load the Python fixes and run startup draft/activity reconciliation. Rebuild/reload the UI as appropriate; `dist/` was regenerated by the final build.
- Integration workers must receive the updated bundled instructions before validating the new complete-passage ingestion contract. Live Cognee/ClawMax setup and end-to-end provider validation remain outstanding.
- Previously reviewed records are not automatically re-extracted. A full correction/versioning workflow still needs implementation; the passage fix applies to new extraction and future ingestion callbacks.
- Record/provider deletion, retention, correction/versioning, backup/restore, schema migrations, and production authentication/deployment remain open.
- Browser checks in this batch were manual automation smoke checks, not a committed comprehensive browser E2E suite. Low-end/mobile performance and broader accessibility/device coverage remain open.
- Further atlas bundle splitting/performance work, font self-hosting, distribution notices, and original-code licensing decisions remain open.
- Content/type/explicit-date deduplication still intentionally ignores title/filename; the UI does not yet offer a separate-event override.
- Exact passages and review gates establish source provenance. They do not guarantee clinical interpretation or fully solve context spanning pages/documents.

## 24. Selected-structure spread fix — September 27, 2026

The spread slider previously forced `isolate: false` on every change, revealing
all visible anatomy even when the user was exploring an isolated structure.

- Spreading with a selection now isolates that selection and packs only its
  visible component meshes. Selected components separate from the start of the
  slider; whole-atlas system spreading is unchanged when nothing is selected.
- The slider states its scope and piece count. It is disabled with an explanation
  for one-piece structures; it cannot split a mesh into anatomy absent from the atlas.
- Reassemble retains the selected structure. Inspecting an included component
  preserves isolation. Clearing/hiding a selection resets the spread, and changing
  selections starts the new structure assembled instead of inheriting animation
  progress from the previous structure.
- Browser verification: heart spread retained exactly 83 visible heart components;
  reassembly stayed at 83; spreading from the surrounding-anatomy view returned to
  those 83; choosing a valve component stayed isolated at one piece with a disabled
  slider; clearing selection restored 741 visible meshes at 0%, and whole-atlas
  spread still worked. The separated heart was visually inspected.
- Existing five frontend tests and the production build/type check passed. The
  existing large atlas bundle warning remains. No backend or record data changed.

## 25. Live Cognee connection — September 27, 2026

Cognee Cloud is now enabled for BodyBrain through the user's per-tenant REST
endpoint. The API key is stored only in the ignored project `.env` with owner-only
permissions. The configured application dataset is `bodybrain`. The local app
was restarted and its API reports Cognee configured and reachable with no error.

- The old shared `api.cognee.ai` endpoint failed TLS before authentication. Current
  [Cognee documentation](https://docs.cognee.ai/api-reference/introduction) requires
  the per-tenant API URL shown in the Cloud dashboard. Setup documentation and
  `.env.example` now explain this requirement.
- The supplied BodyBrain key passed authenticated dataset access on that endpoint.
- A separate temporary BodyBrain store and unique synthetic-only Cognee dataset
  exercised import, pending human review, approval, completed add/cognify runs,
  source-linked CHUNKS retrieval, and exact approved quotations in `/api/chat`.
- Add and cognify returned matching dataset IDs. A fresh adapter retrieved the
  expected document marker and intact synthetic excerpt. Chat reported `cognee`
  retrieval, and another application instance recalled the same approved record
  after restart. Unapproved excerpts were unavailable before review.
- The temporary remote dataset was deleted after the test, and its absence was
  verified. Existing user records were not uploaded by this test.
- The running UI and API returned HTTP 200 through `http://127.0.0.1:3016`.
  New approvals now queue Cognee indexing. Older records marked `unconfigured`
  require the existing **Retry Cognee indexing** action; enabling the provider
  does not bulk-upload previously approved records.
- Cognee's Codex plugin is separate from the application connection. Its
  `~/.cognee/.env` uses `COGNEE_BASE_URL`; BodyBrain uses repository `.env` and
  `COGNEE_URL`. No Codex plugin or hook changes were needed or performed.
- ClawMax remains unconfigured. This connection adds semantic retrieval while
  answers remain verified approved source quotations, not generated medical prose.

This batch changed connection settings and documentation, not application logic.
Validation was the live synthetic round trip above; the earlier unit/build results
in Sections 23–24 were not rerun for these configuration-only changes.

## 26. Record lifecycle and chat persistence — September 27, 2026

ClawMax is deferred while its platform is unavailable. Its adapters and explicit
opt-in paths remain available for future integration; the UI hides unavailable
controls and uses **Records & memory** and **Activity** labels. Local extraction,
human review, anatomy mapping, and Cognee retrieval continue independently.

### Implemented

- **Corrections and re-review:** create a new text transcription with its own
  source ID, title/type/date, findings, and anatomy mappings. Review is required;
  the original remains active until approval. Approval retires its exact Cognee
  document, atomically supersedes it, and queues the replacement for indexing.
  Earlier versions retain their original sources and remain inspectable in history.
- **Deletion:** one version's source, SQLite record, and related activity/task
  snapshots are removed after exact document-scoped Cognee REST cleanup. Failure
  leaves a durable retryable state excluded from recall; it cannot masquerade as
  a completed deletion. Other versions and remote documents are untouched.
- **Concurrent operations:** lifecycle/indexing locks, transactional status
  checks, and task/run guards prevent stale writes from restoring removed evidence.
  Chat rechecks active sources after provider awaits. Pending correction drafts
  serialize deletion with approval, and their active parents cannot be deleted
  until the drafts are resolved.
- **Legacy compatibility:** attempted remote writes retain a cleanup obligation
  across failure, restart, or temporarily disabled Cognee. New writes record the
  provider destination so later cleanup cannot silently target a changed dataset.
- **Chat history:** up to 40 recent exchanges persist in browser storage within
  a size limit. A clear action and storage-failure feedback are included. Whole
  answers citing deleted, superseded, unapproved, or changed source evidence are
  removed on authoritative refresh or successful mutation. History includes source
  citations and anatomy scope; it remains local to this browser/site origin.

### Verification

- Backend: **188 passed, 63 subtests passed**, including 16 record-lifecycle
  regressions for deletion failure/retry, partial remote writes, configuration
  changes, version promotion, original-source preservation, and concurrency.
- Frontend: **13 passed**, including API boundaries, storage restoration and
  failures, history pruning, and independent optional-agent tasks.
- TypeScript and the production build passed. The existing large atlas bundle
  warning remains (approximately 740 kB before gzip).
- Browser checks used an isolated store with providers disabled: import/review,
  cited recall, full-page reload persistence, correction draft/promotion, version
  history, deletion confirmation layout, API deletion, and removal of stale chat
  after refresh. A real-response `workflow_run_id: null` restoration bug found in
  this check was fixed and added to the persistence fixtures.
- Live Cognee used a separate synthetic-only dataset: initial indexing, corrected
  version approval, removal of the original remote file, source-linked retrieval
  of the corrected fact, and deletion of the replacement. The historical local
  source survived until explicitly deleted. The empty test dataset was removed
  afterward. Existing user records were not used for these tests.

### Remaining scope

Backup/restore, broader retention controls, schema migration tooling, cross-device
sync, unifying quick notes with reviewed records, comprehensive committed browser
E2E tests, mobile/accessibility coverage, atlas performance, deployment/accounts,
and remaining licensing decisions are still open. SDK document deletion remains
unsupported; this workspace uses the verified REST integration. Browser history
is not a server-side conversation archive. Lifecycle locks assume one API process.

**ClawMax availability follow-up:** The enterprise page and the user's assigned
dashboard loaded successfully on September 27. The assigned workspace displayed
0 agents and 0 online. BodyBrain still reports ClawMax unconfigured; model
readiness, installed workflows, authentication, and callback connectivity have not
been validated. No ClawMax configuration or workflow run was performed during
this availability check.

## 27. ClawMax hosted integration preparation — September 27, 2026

The user requested integration after the platform became reachable. The assigned
hosted dashboard reports **v1.9.10-test-cognee2**. ClawMax execution is **not yet
live**; template import is not agent deployment or a successful workflow run.

### Completed

- Saved the assigned dashboard origin and both workflow IDs in the ignored
  project `.env`; generated a dedicated random worker token and kept file mode
  `0600`. The dashboard API token remains absent. No credential values are in
  the template, bundle, audit, or trigger inputs.
- Added `integrations/clawmax/package_bundle.py` and a portable `TEMPLATE.md`.
  The pinned upstream parser verified both agent definitions, both full workflow
  objects, and all six embedded agent files against the existing source files.
  Repeated packaging is byte-for-byte deterministic; the ZIP contains only
  `bodybrain/SKILL.md` and `bodybrain/scripts/bodybrain_client.py`.
- Imported **BodyBrain** into the hosted Personal workspace's template catalog
  through its Markdown import form. The UI confirms two agents and two manual
  workflows in the template. The template has not been applied; the workspace
  still has zero deployed agents.
- Implemented a separate callback-only proxy on `127.0.0.1:8081`, launched with
  `npm run backend:worker-proxy`. It authenticates before reading a request body,
  exposes only the three worker routes, reconstructs a fixed loopback upstream,
  and rejects browser origins. Input/output limits, bounded request time,
  cancellation, no redirects/retries, sanitized errors, and no access logging
  bound its forwarding behavior. It does not start a public tunnel.
- Restarted the local application to load the new settings. The UI on port 3016,
  backend on 8080, and callback proxy on 8081 are running locally.

### Verification

- Full backend suite: **253 passed, 63 subtests passed**, including 65 new proxy
  boundary tests. The existing Starlette/httpx deprecation warning remains.
- A real loopback request through the proxy successfully performed authenticated
  atlas lookup. Requests without a token returned 401; record and OpenAPI routes
  returned 404 even with the worker token. UI and backend health returned 200.
- No model calls, real-record transfers, ClawMax workflow executions, public
  tunnels, or Cognee re-indexing were performed for this setup step. Frontend
  source was unchanged; the earlier frontend/build results remain applicable.

### Remaining hosted prerequisites

1. **Dashboard API authentication:** this version has no personal-token creation
   screen. Obtain an operator-issued dashboard credential for `CLAWMAX_TOKEN`.
   Model keys and Cognee keys do not authenticate the workflow API.
2. **Gateway and model:** the live template prerequisite screen reports no
   configured gateway (skills cannot run) and no shared execution model.
   BYOK shows only an OpenAI-compatible `http://127.0.0.1:1234/v1` endpoint; no
   hosted provider key is configured. The issuer/provider of the project's
   existing `LLM_API_KEY` is still unconfirmed; its value was not disclosed or sent.
3. **Install the skill archive:** `.runtime/clawmax-deploy/bodybrain.zip` is ready,
   but Chrome's file chooser rejected file access. Enable the extension's file
   URL access or upload this archive manually using Skills → Upload ZIP. The
   template was imported using the supported text-paste form instead.
4. **Worker runtime and reachability:** the hosted `safeEnv()` filters arbitrary
   `BODYBRAIN_*` variables; browser-local keys do not supply subprocess secrets.
   The operator must wire the callback URL/token into actual tool execution. The
   built-in broker supports only its test skill on this tag. Do not use trigger
   `secrets` as a workaround: this version persists them as execution inputs.
   A TLS tunnel should expose only the callback proxy, never the ordinary API.
5. Apply the template once prerequisites pass, verify resolved agents for both
   workflows, then validate a synthetic ingestion callback, human approval, and
   evidence callback before claiming end-to-end readiness.

See [ClawMax setup](integrations/clawmax/README.md) for the reproducible artifacts,
operator requirements, callback contract, and pinned upstream source links.

## 28. ClawMax OpenAI provider setup — September 27, 2026

- The user supplied an OpenAI key specifically for the assigned hosted ClawMax
  workspace. Entered it into **BYOK → OpenAI** and ran **Check Key**. The UI
  reported **verified** and **OpenAI key is valid and can complete prompts**.
  The pinned implementation performs a small real prompt for this validation.
- Saved the provider configuration. The final workspace default and both agent
  models are `openai-compatible/gpt-4.1-mini`, using OpenAI's official
  `https://api.openai.com/v1` endpoint with Chat Completions. The key is saved in
  dashboard BYOK. On the successful compatible-provider run, ClawMax also stores
  it in the hosted OpenClaw provider configuration; this path is not exclusively
  browser-local. It was not written to repository source, project documentation,
  or substituted for `CLAWMAX_TOKEN`.
- Applied the imported BodyBrain template with unchanged agent IDs. The hosted Agents page now lists
  **BodyBrain Ingestion** (`bodybrain-ingestion`) and **BodyBrain Evidence**
  (`bodybrain-evidence`); the header reports two agents online. This supersedes
  Section 27's zero-agent status. Availability badges do not prove worker
  callbacks or completed record processing.
- Confirmed both manual workflows exist in the hosted Workflows page; no
  workflow execution was triggered. The local backend still lacks the separate
  dashboard API credential needed for programmatic workflow access.
- A synthetic native-OpenAI agent chat failed with HTTP 401 and missing
  `api.responses.write`, although **Check Key** had passed its Chat Completions
  probe. Used the supported **OpenAI-Compatible** provider pointed directly to
  OpenAI; **Check Connection** verified real prompts with `gpt-4.1-mini`. This
  model also works with this ClawMax version's `max_tokens` validation parameter.
  Both agents were saved with the compatible model and no backup model. No API
  permission changes were made, and the key was not sent to a new provider.
- A fresh **BodyBrain Ingestion** chat using the compatible model completed
  successfully and returned the requested `BODYBRAIN_MODEL_READY` marker. The
  prompt contained only synthetic setup instructions and expressly excluded
  records/backend access. This proves browser-initiated model execution, not a
  full BodyBrain task callback or an autonomous backend-triggered workflow.
- A missing gateway is not by itself proof of a blocked run: this tag's chat and
  workflow runtime supports `openclaw agent --local` fallback. Actual tool
  execution still needs verification. Browser-run workflows supply BYOK, whereas
  BodyBrain backend triggers currently do not. The compatible-provider run has
  persisted hosted provider credentials, but backend-triggered execution remains
  untested until a dashboard API credential is supplied. A model name alone is
  not proof of ready provider authentication.
- Pinned source inspection found an additional autonomous-workflow caveat:
  a configured compatible base URL without request BYOK can suppress runtime
  defaults and pass the placeholder `openai-compatible` into the provider-config
  writer, potentially replacing the persisted key. This path has not been live
  tested here. The operator should resolve or verify this credential-resolution
  behavior before enabling backend-triggered execution; browser chat success
  alone is insufficient. Worker skill installation and callback reachability
  also remain outstanding.

Provider validation source:
[integration-validation.ts](https://github.com/Maximilien-ai/clawmax/blob/v1.9.10-test-cognee2/SYSTEM/dashboard/server/lib/integration-validation.ts).
Runtime fallback source:
[workflows.ts](https://github.com/Maximilien-ai/clawmax/blob/v1.9.10-test-cognee2/SYSTEM/dashboard/server/lib/workflows.ts).
Compatible-provider credential persistence:
[agent-execution.ts](https://github.com/Maximilien-ai/clawmax/blob/v1.9.10-test-cognee2/SYSTEM/dashboard/server/lib/agent-execution.ts#L1009).
Autonomous-workflow configuration caveat:
[dashboard-env.ts](https://github.com/Maximilien-ai/clawmax/blob/v1.9.10-test-cognee2/SYSTEM/dashboard/server/lib/dashboard-env.ts#L410),
[safe-env.ts](https://github.com/Maximilien-ai/clawmax/blob/v1.9.10-test-cognee2/SYSTEM/dashboard/server/lib/safe-env.ts#L118).

## 29. ClawMax → Cognee connection — September 27, 2026

The hosted **BodyBrain** workspace now has a verified direct Cognee connection.
This establishes agent access to shared memory; it does not yet replace the
BodyBrain workflow dispatch/callback transport.

- Configured **Partners → Cognee** with the existing BodyBrain Cognee Cloud
  tenant and authorized API key. The UI confirms the key is stored server-side
  for hosted execution. No key was added to source or documentation.
- Saved `bodybrain_clawmax_test` as the partner dataset and `CHUNKS` as the
  search type. The existing application's `bodybrain` dataset is unchanged.
- **Check Keys** only validates configuration presence on this hosted tag. Its
  success was not treated as evidence of authentication or retrieval.
- The UI reports the official Cognee plugin installed. A read-only agent check
  reported its memory tool unavailable and its plugin entry disabled. These
  diagnostic configuration details are agent-reported, not a direct server
  configuration inspection. No native plugin activation was performed.
- The partner dataset/search environment names differ from those consumed by
  the bundled native plugin. Consequently, the live probe explicitly supplied
  its dataset to the Cognee REST API instead of assuming the form isolated it.
- Used the application's Cognee adapter from a separate script to index one
  synthetic document, `clawmax-cognee-probe-20260927`, in
  `bodybrain_clawmax_test`. It contains a randomly generated verification code
  and no patient data. Indexing returned a completed pipeline.
- Through the dashboard, **BodyBrain Evidence** executed a bounded Python
  `http.client` request to `POST /api/v1/search` using its runtime-managed
  `COGNEE_API_KEY`, explicit test dataset, and `CHUNKS`. After correcting tool
  command quoting, it reported HTTP 200 and returned the exact random code and
  source document marker. The expected code was never included in its prompt.
  This verifies hosted agent execution, credential propagation, and Cognee
  retrieval without a dashboard API token or a public BodyBrain callback URL.
- The synthetic probe specification is saved without credentials in
  `.runtime/clawmax-deploy/cognee_probe.json`; its test document is retained for
  reproducibility. No patient records were queried or transferred by this test.

Still outstanding: a structured task/result handoff if Cognee is to carry
BodyBrain jobs, UI integration for that transport, validated worker results,
and a supported launch mechanism. Cognee's memory integration does not start
ClawMax agents. Dashboard-started work can use the existing authenticated UI;
automatic polling requires a worker/schedule and verified unattended model
credentials. The existing direct `/api/workflows` adapter still has no dashboard
API credential and has not completed a live BodyBrain workflow.


## 30. Automatic ClawMax transport through Cognee — September 27, 2026

**Implementation complete; live ingestion/evidence smoke confirmation pending.**
This supersedes Section 29's statement that no task/result adapter exists. It
does not establish a completed hosted round trip or native dashboard workflow.

- Added `CLAWMAX_TRANSPORT=cognee_relay` alongside the original dashboard
  transport. Immutable task/result files use isolated inbox/outbox datasets,
  exact task IDs and digests, expiry, bounded transfers, and verified results.
  The relay uses existing Cognee access without a dashboard API token or a
  public BodyBrain callback. Approved evidence remains in its separate dataset.
- Added a hosted worker that polls every five seconds and invokes the registered
  ingestion/evidence agents through the CLI. Idle polling invokes no LLM. Its
  private SQLite ledger reuses completed results on upload retries, retires
  disappeared/expired tasks, and scrubs cached result bytes. Interrupted agent
  calls can execute again; one worker per dataset pair remains required.
- Added a reproducible, hash-pinned standalone installer containing only the
  named source modules, nonsecret configuration, and documentation. It rejects
  unsafe paths and an active worker lock, uses private file permissions, and
  inherits the hosted Cognee key without serializing it. A detached process and
  a one-second alive check do not provide restart supervision or prove task
  completion. Restart after host/process failure is explicit unless a service
  manager is configured.
- The frontend distinguishes **configured** from live worker verification and
  discloses the Cognee route in each optional consent control. `allow_agent`
  remains operation-specific; exact source checks and human review remain
  mandatory before extracted findings enter memory.
- These are registered-agent executions, but native ClawMax workflow rows and
  workflow budget bookkeeping are not populated by this CLI transport. Hosted
  OpenClaw session transcripts retain their own lifecycle; BodyBrain deletion
  does not erase those transcripts.
- Local frontend typecheck and 13 tests passed. Worker contract tests and the
  packager's compile, manifest, exact embedded-byte, permissions, and corruption
  rejection checks passed without treating them as proof of live integration.
  Hosted synthetic task results and subsequent cleanup are still to be recorded.

See [ClawMax integration](integrations/clawmax/README.md#automatic-cognee-relay-transport)
and [worker packaging and supervision](integrations/clawmax/relay/README.md).

## 31. Fresh repository and runtime reconciliation — September 27, 2026

This section records an independent reinspection after Section 30. It supersedes
older test-count snapshots where the numbers differ, but it does **not** change
Section 30's conclusion that a complete live BodyBrain → Cognee relay → hosted
ClawMax → validated BodyBrain round trip remains unproven.

### 31.1 Fresh source validation

- `npm run check` passed with TypeScript emitting no errors.
- `npm run test:frontend` passed all **13 tests**.
- `npm run test:backend` passed **345 tests and 95 subtests** in approximately
  18.8 seconds. The isolated test launcher used temporary storage and did not
  modify `.bodybrain`.
- The only reported test warning was the existing Starlette deprecation notice
  for its `httpx` TestClient integration.
- The production frontend build was not rerun in this pass. No Cognee or ClawMax
  provider operation was invoked by these checks, so these results verify local
  contracts rather than live integration readiness.

### 31.2 Running local application

Direct checks against the already-running processes returned HTTP 200 from the UI
at `http://127.0.0.1:3016/` and from `/api/health` through both port 3016 and the
API at `http://127.0.0.1:8080/`.

The health response reported:

- `status=ok`, `storage=sqlite`, and `scope=local_single_user`;
- three records, of which one is approved;
- Cognee configured in REST mode for dataset `bodybrain`, with no recorded last
  error; and
- ClawMax callbacks configured, but overall, ingestion, and evidence execution
  all reported unconfigured.

Cognee's health value was `reachable: null`; this endpoint did not perform a live
provider probe, so the response is not current proof of Cognee reachability.
Likewise, no `/api/integrations` provider probe was triggered during this pass.

There is a source/runtime mismatch that must be resolved before relay testing:
the current `backend/bodybrain/main.py` health contract includes the selected
ClawMax `transport`, while the running API response omitted that field. The
running process therefore appears to predate the current source contract or to
be serving a different loaded module version. Restart the local backend from this
checkout and recheck health before interpreting its ClawMax readiness signals.

### 31.3 Version-control and data boundaries

- The outer BodyBrain workspace still has no `.git` metadata and is not inside a
  parent repository. It therefore has no branch, index, commit history, or Git
  diff from which authored BodyBrain changes can be reconstructed. Its files
  should not be described as committed or uncommitted until a repository exists.
- `.runtime/clawmax` is a separate clean, shallow, detached upstream checkout at
  `d3d8199ad4855b175276907065645e3c265fc03b`, tagged
  `v1.9.10-test-cognee4`. It is runtime/vendor reference material, not the
  BodyBrain repository.
- That pinned ClawMax commit fixes catalog-partner configuration crashes by
  tolerating missing legacy validation state and suppressing the generic
  **Check Keys** path for status-only partners; its regression coverage is
  source-structure-oriented rather than a rendered wizard interaction.
- `.bodybrain/sources/7f08d6c8-37b6-4a54-8dde-56bae80f7447` is retained source
  data for the synthetic **DEMO — Recovery update** record, not authored code.
  The corresponding record is pending review and not indexed, so it is excluded
  from approved recall. Manually editing the UUID-named file could make the
  downloadable original disagree with SQLite's parsed pages, digest, findings,
  and review state; demo-definition changes belong in `backend/bodybrain/demo.py`.

### 31.4 Remaining integration milestone

The next defensible end-to-end milestone remains a synthetic-only relay exercise:

1. Restart the backend against the current checkout and confirm health reports
   the intended `cognee_relay` transport as configured.
2. Confirm exactly one hosted relay worker is running for the configured,
   mutually distinct approved-memory, inbox, and outbox datasets.
3. Publish a synthetic ingestion task, receive a hosted-agent result, and verify
   BodyBrain accepts only complete source quotations while preserving mandatory
   human review.
4. Approve the synthetic record, then run a scoped evidence task and verify that
   the displayed answer is rebuilt from validated approved citations rather
   than unverified agent prose.
5. Delete the synthetic record and verify inbox, outbox, task snapshots, source
   bytes, and document-scoped Cognee memory cleanup without using real records.

Until those steps are recorded, the relay should be described as implemented and
locally tested—not live end-to-end complete. Before further authored changes, a
BodyBrain Git repository and reviewed baseline commit are also strongly
recommended so later work has a recoverable history.

The accompanying external shared-chat page could not be read from the automated
environment because its access challenge did not complete. No statement in this
section relies on unseen chat content; the findings above come from the local
source tree, audit ledger, isolated test runs, repository metadata, and local
health responses.

## 32. Local release work and live relay results — September 28, 2026

**Current scope: one user, locally on this Mac. The app is usable; the whole
project is not complete.** This updates Sections 30–31 with actual hosted task
results and the subsequent implementation. Public hosting was not requested.

### 32.1 Implemented since Section 31

- Quick notes now create idempotent backend drafts linked to their selected
  anatomy. Older/browser-only notes have a retry action. Human review remains
  mandatory; removing a browser note does not delete its backend record.
- Browser backup/import covers notes and bookmarks, validates imported content,
  merges by ID, and supports the previous notes-only format. Browser chat stays
  in its separate bounded history; it is not included in these backups.
- Records backup downloads and CLI backup/restore include SQLite and original
  sources, a versioned SHA-256 manifest, path/inventory validation, size limits,
  and database integrity checks. Restore requires a new directory, preserves
  review state, prevents automatic reindexing/task replay, and retains minimal
  remote-cleanup identities. Credentials and provider/browser data are excluded.
  Archives contain private plaintext and are not encrypted by the application.
- A private pre-change backup of the three existing local records was saved at
  `.runtime/backups/before-local-release-20260927.zip` with mode `0600`.
- Schema version 1 establishes a migration baseline; unsupported future schema
  versions are refused. This is not a general migration framework for future
  application versions.
- Activity retention previews and explicitly removes old completed task/activity
  history while protecting pending work and remote-cleanup references. Records,
  sources, browser chat, and hosted transcripts have separate lifecycles.
- The records panel probes relay heartbeat state instead of equating configured
  settings with a live worker. It distinguishes idle/working/offline/probe failure.
- The 3D viewer loads as a separate module with a visible loading state. The main
  entry chunk decreased from approximately 740 KB to 242 KB minified; the viewer
  still occupies approximately 503 KB and triggers the build's size warning.
  Total anatomy geometry was not reduced or benchmarked on physical low-end
  devices. The external Google Fonts import was removed and focus visibility
  improved. The upstream Human Atlas notice is now copied into `public/` so it
  accompanies generated builds.
- Added a local UI/API supervisor, duplicate-instance lock, health/heartbeat
  checker, macOS login installer with post-registration verification, isolated
  relay smoke script, and isolated browser-test server. The previous runtime
  smoke entry point now delegates to the correctly isolated script.

### 32.2 Live hosted relay verification

The local environment now selects `CLAWMAX_TRANSPORT=cognee_relay`. The API was
restarted from this checkout and reports the transport correctly. Its UI and API
returned healthy responses after restart, and the hosted worker heartbeat was
ready/online/idle at `2026-09-28T04:32:25Z`.

`scripts/smoke-relay.py` used separate temporary local storage and only the
synthetic sentence `No fracture of the left femur.`:

- Hosted `bodybrain-ingestion` completed, preserved the complete source quote,
  and left the record pending human review.
- After explicit approval in the isolated test, hosted `bodybrain-evidence`
  completed and returned a citation accepted by exact-source validation.
- Reported execution durations were 4,839 ms and 4,192 ms respectively, using
  model `gpt-4.1-mini` through the runtime's `lmstudio` provider label.
- The result file `.runtime/clawmax-deploy/relay-smoke-result.json` records
  `status=validated`, `stage=cleanup_pending`, `human_review_preserved=true`,
  and `exact_citations=true`. **It does not report a fully passed test.**
- The smoke disabled approved-memory indexing to isolate the relay. Section 25
  records earlier live Cognee indexing/recall; this run does not establish fresh
  combined relay + memory-indexing + deletion success.

Cleanup of the synthetic relay data failed. Cognee returned HTTP 500 from the
document-scoped dataset DELETE route and from the documented scoped `/forget`
route. The cause inside the hosted provider has not been established. No entire
dataset was deleted. The synthetic record remains in a deleting state in the
isolated smoke store with cleanup state retained for retry; the normal three
local records were not used by this smoke. Use the `state_dir` in the result file
with `scripts/smoke-relay.py --cleanup-only` after provider deletion is repaired.
The state was copied with private permissions into
`.runtime/clawmax-deploy/relay-smoke-state` so it survives temporary-directory
cleanup; the result file points to that retained copy. Preserve it until scoped
cleanup succeeds.

These are registered-agent CLI executions over Cognee. Native dashboard workflow
rows/budget bookkeeping are not populated by this transport. Hosted agent session
transcripts remain governed by the hosted runtime's own retention policy.

### 32.3 Verification and local operation

- TypeScript check and production build passed. The remaining warning is the
  size of the separate anatomy viewer chunk.
- **352 backend tests and 95 subtests passed**, including notes, backup/restore,
  malformed archive rejection, schema compatibility, and retention protections.
- **13 frontend state/API/history tests passed.** These are not rendered
  component tests or a full automated browser suite.
- Interactive Chrome checks against an isolated API verified paste → review →
  approval → exact-source answer, chat persistence after reload, a narrow layout
  without horizontal page overflow, and quick note → pending backend draft.
  Reproduction steps are in `scripts/BROWSER_CHECKS.md`. Test servers were stopped
  afterward; ordinary user storage and providers were not used for these checks.
- The local supervisor recovered automatically after its API child was
  intentionally terminated; both UI and API returned healthy responses afterward.
  A second supervisor instance was rejected by its lock. Python script syntax
  checks passed. This verifies child-process recovery while the parent is alive.
- macOS accepted the login service registration but refused to execute its
  Python process with `Operation not permitted` / `EX_CONFIG (78)`. The failed
  job and its plist were removed, so it does not keep retrying. The installer now
  checks sustained process startup and removes failed registrations. The exact
  OS permission cause and successful login/reboot behavior remain unresolved.
- The app is currently served at `http://127.0.0.1:3016`, backed by the loopback
  API on port 8080. Terminal startup is documented in README. Closing the parent
  terminal/session or rebooting the Mac is not covered by the verified recovery.

### 32.4 Remaining work and limits

| Item | Current status / next evidence needed |
| --- | --- |
| Hosted cleanup | Blocking: provider-scoped deletion must stop returning HTTP 500; rerun retained synthetic cleanup and prove remote/source cleanup completes. |
| Mac login/reboot startup | Blocking unattended local operation: resolve OS launch failure, then verify login/reboot startup and healthy UI/API. Foreground startup works. |
| Hosted worker supervision | A systemd user-unit example exists, but the hosted operator has not installed or verified it. Test crash and host-reboot recovery with exactly one worker. |
| Browser/component regression coverage | Interactive checks and state tests exist; a comprehensive automated rendered-component/browser suite remains open. |
| Larger collections | Record-list pagination and scalability measurements remain open. Backup/schema baseline is implemented. |
| Device/accessibility performance | Narrow-layout and keyboard/focus improvements exist; physical mobile/low-end performance and full accessibility audits remain open. |
| Version control | Rechecked September 28: the outer BodyBrain workspace has baseline commit `bfc8094` (`Initial BodyBrain implementation`, September 27, 2026). Later local-release and dataset changes remain uncommitted; the vendor checkout is separate. This supersedes the earlier no-Git observations. |
| Distribution license | Upstream attribution/notices are present; an original-code license has not been chosen by the owner. |
| Public/multi-user operation | Accounts, TLS deployment, cross-device sync, and production operations are outside the selected local scope and are not implemented/verified as a hosted product. |
| Broader health roadmap | Raw-scan interpretation, OCR, personalized geometry, wearables, and diagnostic functions are not delivered by this local app. |

Section 21's original P0/P1 defects are substantially repaired and live ingestion
and evidence are now demonstrated, but provider cleanup is an unresolved lifecycle
blocker. P2 contains both completed work and the explicit open items above. This
is a working local application with validated hosted features, not a claim that
every original audit recommendation or the broader product vision is finished.

## 33. Synthea and Fitbit sample workspaces — September 28, 2026

The user selected Synthea medical history plus Fitbit summaries from their two
dataset research lists. The implementation uses the official Synthea CSV sample
and the April–May 2016 archive from Zenodo record 53894. Publisher metadata and
usage statements were checked; URLs, versions, sizes, hashes, and attribution are
recorded in `datasets/sources.json` and `datasets/README.md`.

- Downloaded approximately 31 MB into ignored `.runtime/datasets/raw`; verified
  SHA-256 for both archives and the publisher's MD5 for Fitbit. Synthea is pinned
  to official sample-repository commit `9959d9178ea28f4ec10f17ee238b6fabe6eb0de5`.
- Prepared **22 Synthea drafts** for one synthetic patient: up to four recent
  rows per category across conditions, medications, encounters, procedures,
  care plans, and observations. Their source dates span 2009-03-30–2026-02-09.
  This is a selected sample, not a complete longitudinal record.
- Prepared **7 Fitbit daily drafts**, dated 2016-05-06–2016-05-12, for one study
  participant, with exact same-subject/date sleep joins. Missing sleep remains
  missing; identical duplicate rows do not inflate totals; conflicting duplicates
  and invalid measurements are rejected. No heart-rate or recovery metric is
  inferred from activity or sleep.
- Each normalized TXT summary retains source row values, source member and row
  references, original subject/date, archive hash, attribution, and transformation
  disclosure. The untouched archives remain separately available. These summaries
  are derived records, not verbatim medical reports.
- Added bounded CSV adapters, idempotent imports, dataset/subject workspace
  markers, pinned download/prepare tooling, and a two-app launcher. Workspace
  locking prevents preparation concurrent with the dataset server launcher.
- Synthea runs at `http://127.0.0.1:3018` (API 8083); Fitbit runs at
  `http://127.0.0.1:3019` (API 8084). They have separate SQLite/source stores and
  browser origins. Providers and dotenv are disabled for both; no hosted uploads
  or approvals were performed by sample preparation. The normal `.bodybrain`
  records remain in the ordinary app on port 3016.
- All **29 prepared records remain pending human review**. A visible workspace
  label identifies the sample context. Rendered Chrome checks confirmed both
  record lists and the Fitbit measurement/source review screen. Review and exact
  citation recall were tested using disposable fabricated test fixtures.
- **364 backend tests and 95 subtests passed**; **13 frontend tests passed**;
  TypeScript and production build passed. Existing warnings remain: the anatomy
  viewer chunk exceeds 500 KB and Starlette reports its httpx TestClient
  deprecation. Dataset tests cover participant/date separation, duplicate and
  invalid-value handling, missingness, source provenance, review gating, exact
  citations, repeat imports, and refusing personal or provider-enabled stores.

The normal upload form still accepts PDF/TXT/MD. This phase adds a CLI dataset
sample workflow, not universal CSV/FHIR ingestion, device account synchronization,
imaging interpretation, or clinical conclusions. Other suggested datasets were
not downloaded. Synthea and Fitbit subjects are unrelated and are not represented
as one real patient. Section 32's Cognee cleanup, login-startup, and hosted
supervision issues are not resolved by this work.

## 34. Resumed dataset handoff and verification — September 28, 2026

Read the latest shared conversation and its final expanded activity, then checked
the current files and running apps. The remaining dataset handoff was review-screen
verification and documentation; the archives, adapters, and isolated workspaces
were already present.

- Fixed Synthea recent-row selection to compare full source timestamps and UTC
  offsets. Previously, multiple events on one day were ordered only by CSV row
  position, which could select an earlier event. Two regression cases cover
  shuffled same-day events and offsets crossing calendar midnight. Source field
  values and displayed calendar event dates are preserved.
- Dataset records now show **Normalized source** and **Open summary** in the
  review panel, with an explicit CSV transformation explanation. Ordinary
  uploads and corrected transcriptions retain their existing source labels.
- Reverified both archive byte counts and pinned SHA-256 hashes without
  downloading them again. Read-only comparison confirmed the current adapters
  reproduce exactly the 22 Synthea and 7 Fitbit summaries already stored, so
  no reimport or source replacement was needed.
- Chrome checks confirmed separate workspace labels, connected backends,
  unconfigured providers, the two record lists, historical medication wording,
  Fitbit zero values versus missing sleep, and normalized source provenance.
  Reproduction steps are in `scripts/BROWSER_CHECKS.md`. These are interactive
  checks, not a new automated browser suite.
- The resumed checks did not approve records or alter their sources. All 29
  were pending at the initial read; Synthea approval state changed during live
  use while verification was in progress. Those decisions were preserved.
  Section 33's all-pending count describes preparation, not a permanent state.
- **366 backend tests and 95 subtests passed**, including **14 dataset tests**.
  **13 frontend tests passed**; TypeScript, production build, and Git whitespace
  checks passed. The existing anatomy chunk-size and Starlette/httpx deprecation
  warnings remain.
- Corrected Section 32.4's stale version-control status: baseline commit
  `bfc8094` exists; later release and dataset changes are still uncommitted.

The dataset handoff is complete for the chosen local sample scope. Existing
servers remain available on ports 3018 and 3019. The earlier Cognee cleanup,
Mac login-startup, and hosted-worker supervision issues were not repaired or
reverified during this dataset continuation and remain separately open.

## 35. Cognee, ClawMax, and local startup recheck — September 28, 2026

The following supersedes the earlier integration/startup status. Live checks
were completed around 15:29 UTC. Dataset source files and user review decisions
were preserved.

- **Local UI/API and automatic process recovery work.** The macOS login service
  is installed. Starting launchd in `/private/tmp` with logs under
  `~/Library/Logs/BodyBrain` resolved the startup failure; Python enters the
  original project directory and all records remain in place. The installer now
  verifies UI/API responses as well as a stable supervisor PID. A controlled
  supervisor termination changed PID 37935 to 37981 and restored HTTP 200 on
  API 8080 and UI 3016 automatically. Physical login/reboot was not performed.
- **Cognee memory passed a live synthetic test.** New `scripts/smoke-memory.py`
  verified indexing, retrieval of the synthetic source document ID, scoped
  deletion, and subsequent absence. Its isolated state is retained at
  `.runtime/clawmax-deploy/memory-smoke-u9ncy3og`. `scripts/smoke-relay.py
  --with-memory` now supports requiring this memory path in the full hosted test.
- **ClawMax relay is currently blocked.** Both exact scoped deletion routes still
  return HTTP 500 for the retained synthetic relay file. A fresh unindexed
  synthetic file in a new dataset reproduces the failure. Indexed memory's
  deletion success does not prove raw relay cleanup works. Provider health and
  authenticated reads succeed; the internal server failure needs provider logs.
- **The outbox reached the provider's listing cap.** Requests at offsets 0 and
  1000 both return the same 1,000 IDs. The live OpenAPI route has no pagination
  query parameters. The client fails closed; the integration status now explains
  the incomplete/repeated listing instead of showing only a generic error.
  `scripts/check-local.py` reports Cognee, ingestion, and evidence separately and
  returns failure while either hosted integration is unavailable.
- **Fixed heartbeat growth locally.** The worker makes room before publishing
  its third heartbeat and saves upload intent before the network call. Deletion
  outages, lost upload responses, restart recovery, and ownership mismatches are
  covered by regression tests. The updated installer is prepared in
  `.runtime/clawmax-deploy/relay-retention-fix`. Hosted deployment remains pending:
  automatic approval review rejected uploading internal worker code to Cognee
  without specific transfer authorization, and explicit approval was requested.
- **Hosted restart supervision remains unverified.** Read-only hosted diagnostics
  found one detached worker, parent PID 1, and no detected systemd, supervisord,
  cron, or s6 executable. The example service unit still requires a supported
  host/operator startup mechanism; a heartbeat cannot prove container recovery.
- **Validation:** 370 backend tests and 95 subtests passed. The modified startup
  and diagnostic scripts compile, and Git whitespace checks pass. The existing
  Starlette/httpx deprecation warning remains. No frontend code changed in this
  integration recheck; Section 34 records its latest test/build verification.

The credential-free private report `.runtime/provider-repair-report.md` records
exact synthetic reproduction IDs and recovery steps. It has not been sent to
Cognee. Retained smoke cleanup manifests and the existing worker ledger must not
be discarded while deletion remains blocked. No dataset reset, relay indexing,
credential expansion, or approval of user records was used as a workaround.

## 36. GitHub release and hosted frontend — September 28, 2026

The current source, dataset adapters, backup/retention features, regression tests,
submission guide, demo narration, and reviewed native ClawMax export are included
in the release. GitHub resolves the original repository URL to the public
`ritzzi23/BodyBrain` repository.

The user selected a frontend-only Vercel deployment. `vercel.json` builds with
`VITE_FRONTEND_ONLY=true`: anatomy exploration, browser notes, and bookmarks are
available; every records action opens local setup guidance. The records panel is
not mounted, so it does not poll unavailable APIs, and saving notes does not try
to create backend drafts. The normal local build retains records functionality.
The persistent API, private sources, credentials, and hosted worker are outside
this deployment. The Cognee/ClawMax limitations in Section 35 remain unresolved.

Release validation: 370 backend tests and 95 subtests, 13 frontend tests,
TypeScript checking, and both normal and frontend-only production builds passed.
The Three.js scene chunk still produces Vite's advisory 500 kB size warning.
Chrome checks verified anatomy selection, the hosted guidance dialog, and a
fictional browser-only note saving with the correct success message.

A bounded publish audit found no obvious credentials or private records in
intended source files and the native workspace ZIP. Actual environment files,
local record stores, runtime artifacts, dependencies, and Vercel CLI state are
excluded. Publishing these deliverables does not submit the hackathon portal or
create a demo video.
