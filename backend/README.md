# BodyBrain backend

FastAPI and SQLite power report import, human review, source-backed recall,
anatomy mappings, and persistent timelines. Cognee and ClawMax adapters are
implemented; they remain **unconfigured until connection settings are supplied**.
Mocked contract tests do not prove a live external workflow.

## Run locally

From the repository root, install Python 3.12 dependencies with `uv`:

```sh
uv sync --project backend --python 3.12 --frozen
npm install
```

Create a root `.env` using [.env.example](../.env.example) if you do not already
have one. The default configuration starts without provider credentials.

```sh
npm run dev
```

This starts both the [UI on port 3016](http://127.0.0.1:3016) and the API on port
8080. To start only the API, run `npm run backend`.

- [Interactive API documentation](http://127.0.0.1:8080/docs)
- [OpenAPI schema](http://127.0.0.1:8080/openapi.json)
- [Backend health and configuration](http://127.0.0.1:8080/api/health)
- [Integration probes](http://127.0.0.1:8080/api/integrations)

The API binds to `127.0.0.1` and is designed for one local user. The Vite UI
proxies `/api` to the backend. `BODYBRAIN_API_TOKEN`, if enabled, requires a Bearer
header for user API requests. The separate `BODYBRAIN_AGENT_TOKEN` protects agent
task retrieval, anatomy lookup, and callbacks. It does not authorize human review.

For an independently authorized hosted deployment, configure exact
`BODYBRAIN_ALLOWED_HOSTS` and `BODYBRAIN_ALLOWED_ORIGINS`. Public hostnames require
a user API token. User and agent tokens must be different. The default is local
only and does not open a tunnel or expose a network service.

## Record lifecycle

1. Import a text-based PDF, UTF-8 TXT/Markdown file, or pasted text.
2. Read the original page excerpts and review the proposed anatomy mappings.
   Local extraction identifies explicit mentions and preserves other source
   passages for review. With per-import opt-in, configured ClawMax ingestion can
   submit a replacement draft. Neither approves its own findings. Exact passage
   extraction preserves decimals and wrapped lines; long passages stay whole,
   and limits produce visible warnings.
3. Select the findings to approve. Unselected findings cannot enter recall or
   permanent memory. An approved record can no longer be remapped or overwritten
   by an agent.
4. Cognee indexes approved excerpts in the background when configured. Status is
   `indexed` only after the provider confirms successful graph construction.
   Failures remain visible and can be retried.
5. Ask a question or select a body structure. Answers show complete, reviewed
   source quotations with record/page references. Missing evidence produces an
   explicit no-evidence response.

Original source files and SQLite review state persist under `BODYBRAIN_DATA_DIR`
(default `.bodybrain` in the repository). Cognee has its own persistent memory
store. A record saved locally while Cognee is unconfigured is not described as
indexed. Retrying after configuration does not require uploading the source again.

Timeline dates come from an explicit user date or a labeled ISO report/visit/event
date. Missing clinical dates stay unknown; upload dates are not substituted.

## User API

| Route | Purpose |
|---|---|
| `GET /api/health` | Storage, record counts, configured integrations |
| `GET /api/integrations` | Probe Cognee and configured ClawMax workflows |
| `GET /api/backup` | Download a manifest-checked ZIP snapshot of SQLite and original sources |
| `POST /api/notes` | Idempotent browser-note draft: `client_id`, `text`, `concept_id`, optional `event_date` |
| `POST /api/history/retention` | Preview completed history older than `older_than_days`; `apply: true` removes it |
| `POST /api/records` | Multipart file import: `file`, optional `title`, `record_type`, `event_date` |
| `POST /api/records/text` | JSON import: `title`, `text`, optional `record_type`, `event_date` |
| `GET /api/records` | Saved records, review state, indexing state |
| `GET /api/records/{id}` | Source text, pages, proposed findings, mappings |
| `GET /api/records/{id}/source` | Download the original file |
| `POST /api/records/{id}/revisions` | Create a pending correction with `title`, `text`, `record_type`, and optional `event_date` |
| `DELETE /api/records/{id}` | Remove one version and its source/activity after scoped Cognee cleanup; retry if cleanup fails |
| `PATCH /api/records/{id}/mapping` | Update a pending finding's `concept_id` or clear it |
| `POST /api/records/{id}/approve` | Approve explicit `finding_ids`; `{}` approves all proposed findings |
| `POST /api/records/{id}/index` | Queue/retry an approved record's Cognee indexing |
| `POST /api/records/{id}/process` | Submit a pending record to configured ClawMax ingestion |
| `GET /api/anatomy/search?q=...` | Find concepts from the actual 3D atlas catalog |
| `POST /api/chat` | Ask with `question` and optional `concept_id` |
| `GET /api/timeline?concept_id=...` | Approved clinical events |
| `GET /api/summary?concept_id=...` | Reviewed source excerpts and mapped concepts |
| `POST /api/demo` | Explicitly import three labeled synthetic records for review |
| `GET /api/runs` | Ingestion, review, indexing, and workflow execution states |
| `GET /api/tasks/{id}` | Poll a ClawMax task and its validated result |

Revision records have `revision_number`, `revises_record_id`, `superseded_by`, and
`source_kind`. A corrected transcription has a new source ID and must be reviewed.
Only one pending revision may target an active approved parent. Approving it
retires the parent's remote document before atomically making the child approved
and the parent `superseded`. Historical sources remain readable but do not enter
answers or the active timeline. Original PDFs are retained as the original version;
the editable correction is a separate text transcription.

Deletion marks the selected version `deleting` and excludes its evidence while
cleanup runs. HTTP 503 preserves `deletion_error` and the retained source for a
retry. Startup does not upload deleting records. Deleting a parent with a pending
revision returns HTTP 409: approve or delete its draft first. Other versions are
unchanged by deletion. The database retains an opaque deleted-record ID to reject
delayed activity writes, without its source text or metadata.

The worker records an attempted remote write and a credential-free memory target
before indexing, including writes that later fail or time out. Cleanup refuses a
changed provider destination. Legacy records without destination metadata use the
current configuration with a conservatively retained cleanup obligation.
Per-record locks and transactional status checks coordinate this single backend
process; multiple API workers are not supported. REST document deletion is
supported; the optional SDK's older generated-filename uploads cannot yet be
removed safely and report a retryable cleanup failure instead of success.

If ClawMax evidence is configured, chat returns an `agent_task_id` alongside the
immediate evidence response when `allow_agent: true` is supplied and relevant
evidence exists. Poll the task for completion. The agent receives only the
approved excerpts selected for that question and optional anatomy scope;
callback citations must belong to that snapshot
and match a complete human-approved quotation. Agent prose is stored as a draft;
the presented verified answer is rendered from validated citations.

File imports accept `allow_agent` as a multipart boolean; text imports and chat
accept it in JSON. It defaults to `false`. Demo loading accepts
`POST /api/demo?allow_agent=true` for explicit synthetic agent processing; its
default remains local. `POST /api/records/{id}/process` explicitly requests an
agent task for an existing pending record. User and worker authentication remain
separate. Ingestion callbacks must quote complete source passages, including
original punctuation and line breaks; detached substrings are rejected.

## Connect optional providers

For Cognee Cloud, set `COGNEE_MODE=rest`, `COGNEE_URL`, `COGNEE_API_KEY`, and
`COGNEE_DATASET`. Copy the per-tenant `COGNEE_URL` from the Cloud dashboard's
API Keys page (for example, `https://your-tenant.aws.cognee.ai`); the old shared
`api.cognee.ai` URL is not the current Cloud endpoint.
Self-hosted authenticated Cognee uses `COGNEE_BEARER_TOKEN`
instead of the Cloud key. The optional local SDK setup pins `cognee==1.6.1` and
requires its model-provider configuration. See the [Cognee guide](../integrations/cognee/README.md)
for exact contracts, persistence, authentication, and SDK installation.

For ClawMax, install the supplied BodyBrain organization/agent/skill bundle into
your existing workspace and configure `CLAWMAX_URL`, `CLAWMAX_TOKEN`, both
workflow IDs, and `BODYBRAIN_AGENT_TOKEN`. The worker runtime must reach
`BODYBRAIN_BACKEND_URL` and use the same agent token. See the
[ClawMax guide](../integrations/clawmax/README.md) for installation and network
requirements. A hosted agent cannot access your laptop through its own
`127.0.0.1` address. The separate `npm run backend:worker-proxy` command exposes
only authenticated worker callbacks on loopback port 8081; tunnel that port if
needed, not the ordinary backend. Local startup does not start a tunnel. Hosted
ClawMax also needs operator-supported credential injection into the actual agent
tool process; browser-local keys are insufficient on v1.9.10-test-cognee2.

Both providers report real connection and execution state. A successful HTTP
health probe does not demonstrate dataset permissions or successful ingestion,
and a submitted ClawMax execution is not a completed BodyBrain task. Validate the
live setup with a synthetic report, review, Cognee indexing, and a source-backed
question before using it for the hackathon demonstration.

The alternative `CLAWMAX_TRANSPORT=cognee_relay` uses separate Cognee task/result
datasets and an already-installed hosted worker. It needs no public callback URL.
See [relay setup](../integrations/clawmax/README.md#automatic-cognee-relay-transport).
`scripts/smoke-relay.py` exercises synthetic hosted ingestion, human review,
evidence validation, and scoped cleanup in isolated local storage. It is a live
provider test, not part of the offline test suite. Failed cleanup retains its
state for `--cleanup-only <state-directory>`; do not discard that state while
remote cleanup is pending. Add `--with-memory` to also require real Cognee
indexing and source-linked retrieval in a new synthetic dataset. Run
`backend/.venv/bin/python scripts/smoke-memory.py` for an independent memory check;
it also retains state for `--cleanup-only <state-directory>`.

The September 28 recheck passed memory indexing, source-linked retrieval, and
scoped deletion of indexed memory. Hosted ingestion/evidence passed earlier,
but current relay readiness is blocked: raw relay-file deletion returns HTTP
500 and accumulated heartbeats filled the provider's 1,000-file listing, which
repeats when requesting the next page. The client refuses this incomplete list.
See audit section 35 for deployment status and the remaining provider repair.

## Backups and history

```sh
PYTHONPATH=backend backend/.venv/bin/python -m bodybrain.backup create --data-dir .bodybrain --output .runtime/backups/manual-backup.zip
PYTHONPATH=backend backend/.venv/bin/python -m bodybrain.backup restore .runtime/backups/manual-backup.zip --data-dir .bodybrain-restored
```

Choose a new output filename and a nonexistent restore directory. The archive
includes SQLite and each record's original source; the SHA-256 manifest, source
inventory, path validation, 2 GB size limit, and SQLite integrity check protect
against corruption and malformed paths. Prefer backup while record edits are
idle. A source removed during CLI backup causes a visible failure and retry.
POSIX-created archives and restored files are private, but are not encrypted.

Restore keeps record review state and remote-cleanup identities. It marks
approved records not indexed, drops task payloads, retains minimal relay cleanup
tombstones, and marks unfinished activity interrupted. It never restores `.env`,
credentials, browser notes/bookmarks/chat, hosted transcripts, or provider stores.
Explicitly check provider state before retrying indexing. A restore is not a
rollback of Cognee or hosted ClawMax activity.

Schema version 1 establishes the migration baseline for existing version-0
databases. Newer unknown schema versions are refused rather than modified.

History retention defaults to preview, accepts 1–3650 days, and removes only old
completed/failed task results and completed/failed/interrupted activity. Relay
cleanup references protect related history. Sources, records, active work, and
external provider data remain unchanged. No automatic source-retention schedule
is enabled.

## Validation and current scope

```sh
npm run test:backend
```

This command isolates even import-time application creation in a temporary data
directory and disables dotenv/provider configuration. Direct pytest invocation
must supply equivalent isolation when importing `bodybrain.main`.

Tests cover persistent record/review flows, source validation, anatomy mapping,
rejected excerpts, missing evidence, file limits, workflow callbacks, and mocked
provider contracts. Provider tests make no live requests with personal records.

Uploads are limited to 10 MB, 100 PDF pages, and 150,000 extracted characters.
Scanned/image-only PDFs need OCR before import. The backend does not interpret
raw scans, reconstruct individual anatomy, diagnose conditions, or synchronize
fitness accounts. Local retrieval uses reviewed-excerpt matching, with Cognee
source matches improving ranking when available; it is labeled separately when
Cognee is unavailable.
