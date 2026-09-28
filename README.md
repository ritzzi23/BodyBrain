# BodyBrain

A full-body anatomy explorer with an evidence-backed memory backend. React, TypeScript, Three.js, FastAPI, SQLite, and configurable ClawMax/Cognee integrations.

Project source and submission materials: [ritzzi23/BodyBrain](https://github.com/ritzzi23/BodyBrain).

## Hosted frontend

The Vercel build is an anatomy explorer with browser notes and bookmarks.
**Records & memory** explains how to run the full application locally. The hosted
frontend does not upload records, contact Cognee or ClawMax, or connect to a shared
records database. Notes and bookmarks stay in this browser's storage on this site;
they are separate from the local application's browser storage.

Import this repository into Vercel using the Vite framework. The checked-in
`vercel.json` runs `npm ci` and `VITE_FRONTEND_ONLY=true npm run build`, then serves
`dist/`. No provider credentials or environment variables are required for this
deployment. To preview the hosted mode locally:

```sh
VITE_FRONTEND_ONLY=true npm run build
npm run preview
```

A normal `npm run build` retains the full local workflow. The persistent FastAPI
backend, SQLite records, and agent workers are not deployed by this Vercel setup.
See the [submission guide](submission/SUBMISSION_GUIDE.md) for the project pitch,
native ClawMax export, and current provider limitations.

## Run locally

Use **Node.js 22.13 or newer**, **Python 3.12**, and [uv](https://docs.astral.sh/uv/).

```sh
npm install
uv sync --project backend --python 3.12
npm run dev
```

Open [http://127.0.0.1:3016](http://127.0.0.1:3016). `npm run dev` starts the UI and API together. For separate terminals, use `npm run dev:ui` and `npm run backend`. Interactive API docs: [http://127.0.0.1:8080/docs](http://127.0.0.1:8080/docs).

```sh
npm run build    # Type-check and create the production build in dist/
npm run preview  # Serve that build locally (run backend separately)
npm run test:backend  # Ingestion, evidence, persistence, and provider contracts
npm run test:frontend # API payloads and asynchronous workspace state
```

For everyday local use of the built app:

```sh
npm run build
backend/.venv/bin/python scripts/local-service.py
```

Keep that terminal running. The supervisor restarts the UI/API if a child exits;
stop it with Ctrl-C. `backend/.venv/bin/python scripts/check-local.py` checks the
UI, API, and hosted relay heartbeat. Do not run the development server and this
supervisor together because they use the same ports.

The optional `backend/.venv/bin/python scripts/install-local-service.py` installs
a macOS login service. It is installed on this Mac, and a controlled supervisor
restart restored both UI and API automatically. Login/reboot recovery still needs
a real login/reboot check. Stop the terminal supervisor before installing the
service. Launch logs live in `~/Library/Logs/BodyBrain`; records stay in `.bodybrain`.
Use `--uninstall` to remove the login registration while retaining records.
See the latest [audit update](PROJECT_AUDIT.md#35-cognee-clawmax-and-local-startup-recheck--september-28-2026).

## Included

- Real adult male reference anatomy: **2,234 meshes, 3,432 named concepts, and 15 systems**.
- Full-body orbit, pan, zoom, auto-rotation, preset camera views, fullscreen, and reset.
- Structure search, five regional collections, system visibility switches, and layer presets.
- Selection, isolation, hiding, labels, opacity adjustment, and a slider to spread structures apart.
- Spreading a selected structure separates only its modeled pieces. Clear the selection to spread all visible anatomy; single-piece structures cannot be subdivided by the slider.
- Structure details, source attribution, bookmarks, personal notes, and a timeline of saved notes.
- JSON backup/import of notes and bookmarks, responsive side panels, and keyboard controls documented in Help.

## Records and memory

Two dataset sample apps are available: **Synthea clinical history** on port 3018
and **Fitbit daily activity/sleep** on port 3019. Run `npm run datasets:prepare`
followed by `npm run datasets:run` after building. They use separate local stores,
disable external providers, and require record review. See
[dataset setup, provenance, and limitations](datasets/README.md).

Open **Records & memory** in the header. Upload a text-based PDF, TXT, or Markdown file, or paste a record. Review its exact source passages and atlas mappings, approve selected findings, then ask questions and inspect the timeline. **Load synthetic demo** creates three explicitly fictional records, still requiring review.

Original files and reviewed records persist under `.bodybrain/` in SQLite and private source files. Records survive restarts. Dates are only inferred from explicitly labeled ISO dates; missing dates stay unknown. Scanned PDFs need OCR outside this version.

An explicit event date can be supplied for both files and pasted text. Short notes
and passages without anatomical mentions can also be reviewed and recalled.
Selecting an atlas structure scopes chat and the record timeline; choose **Use all
records** to widen the scope. Recent conversations survive reloads in this
browser (up to 40 exchanges, within a bounded storage budget) and can be cleared
from the chat panel. Answers citing deleted, replaced, or no-longer-approved
records are removed when the record list refreshes. Import drafts survive closing
the workspace but not a page reload. New browser notes also create pending
backend drafts; older notes can be added using **Save to records**.

Use **Create correction** on a reviewed record to create a new transcription,
change its date or title, or review its anatomical links again. The current
version remains active until the draft is approved. Approval replaces its memory
with the new version; the earlier source stays accessible in **Version history**.

**Delete record** removes one version's source, findings, related activity, and
Cognee REST memory after confirmation. Other versions remain in history and are
not automatically restored to active memory. If cleanup fails, the record is
excluded from answers and shows **Retry deletion**. Resolve any pending correction
before deleting its active parent.

ClawMax is optional and can be connected later. Local passage extraction, review,
anatomy mapping, and Cognee retrieval work without it. ClawMax controls appear only
when the corresponding integration is available; extraction and citation selection
require an unchecked opt-in for each import or question.
Approval saves locally and also queues Cognee indexing when
Cognee is configured. The API defaults `allow_agent` to `false`; requesting the
explicit record-processing endpoint is another way to start an ingestion task.

Copy `.env.example` to `.env` and configure your providers:

- [Cognee setup](integrations/cognee/README.md): persistent reviewed memory and attributable chunk retrieval.
- [ClawMax setup](integrations/clawmax/README.md): real ingestion/evidence workflows, two-agent template, and authenticated callbacks.

Without provider configuration, records/review/timeline and exact local evidence recall still work. The UI labels this **local evidence**; it does not claim ClawMax or Cognee was used. Connection adapters have mock contract tests; a live provider run requires your service URLs, runtime, and credentials. See [the audit](PROJECT_AUDIT.md) for this workspace's verified connection status.

On POSIX systems, startup enforces owner-only data directories (`0700`) and files
(`0600`), including existing SQLite files and retained sources. The backend test
command uses temporary storage and disables dotenv/provider settings so test
collection cannot open your normal database.

See [backend details and API reference](backend/README.md) for configuration and boundaries.

## Quick notes and bookmarks

Notes and bookmarks use browser `localStorage`. They belong to the current browser profile and site origin on this device; opening another browser, changing the hostname or port, or clearing site data creates a different or empty workspace. There is no account or synchronization. Use **Back up notes and bookmarks** and **Import browser backup** in My memories or Timeline. Import merges notes by ID, accepts the older notes-only export, and does not upload or approve records. This JSON backup does not include chat history or backend records.

Saving a quick note also creates a record draft connected to the selected
structure. If the API is unavailable, the browser copy remains available with
**Save to records** for retry. A human must approve the draft before recall.
Removing a browser note leaves its backend record intact.

The model is reference anatomy, not a reconstruction of the user’s body. The backend extracts document text and maps anatomical mentions; it does not interpret raw medical scans or diagnose conditions.

## Records backups and activity retention

Use **Download records backup** in Records & memory to save a ZIP containing
SQLite review/history state and original sources. It excludes `.env`, provider
credentials, browser storage, and hosted provider data. Archives contain private
document text; store them securely. They are not encrypted by the application.

Restore only into a new directory while the normal app is stopped:

```sh
PYTHONPATH=backend backend/.venv/bin/python -m bodybrain.backup restore bodybrain-backup.zip --data-dir .bodybrain-restored
```

Set `BODYBRAIN_DATA_DIR` to the restored directory before restarting. Restore
checks the manifest, hashes, source inventory, and database. It preserves review
state, disables implicit reindexing, and does not replay hosted jobs. Retry
indexing explicitly after checking provider state. See [backup details](backend/README.md#backups-and-history).

**Activity retention** previews and removes old completed task/activity history.
It keeps records, sources, pending work, remote-cleanup obligations, browser chat,
and hosted transcripts. Record deletion is a separate explicit action. The latest
live relay test verified hosted ingestion and evidence, but Cognee returned HTTP
500 during scoped cleanup; deletion of affected remote data is still blocked.

## Sources

The explorer adapts [Human Atlas](https://github.com/ashemag/human-atlas), under the [MIT license](HUMAN_ATLAS_LICENSE). Anatomical data comes from BodyParts3D, © The Database Center for Life Science, licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). See [full dataset attribution and adaptations](public/ATTRIBUTION.md).

The original project idea, hackathon theme, and development links remain in their existing files.
