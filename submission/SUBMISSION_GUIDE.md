# BodyBrain submission guide

Prepared September 28, 2026 from the supplied AgentForge Demo & Evaluation
screenshot and the verified local project. This release prepares the current
source for GitHub and the anatomy frontend for Vercel. Portal submission and
video sharing are separate tasks.

**Project source:** https://github.com/ritzzi23/BodyBrain

**Live hosted demo:** https://bodybrain.vercel.app

The hosted frontend supports anatomy exploration, browser notes, and bookmarks.
Its **Records & memory** panel links to local setup instructions. Run the full
application locally for record imports, review, recall, Cognee, and ClawMax; the
Vercel deployment does not host the persistent API or any private record store.

For the seven-point demo checklist, use the
[recording-ready pitch](DEMO_VIDEO_PITCH.md), including narration, screen cues,
the exact synthetic input, and repeatable pass conditions.

## 1. Requirements shown in the screenshot

| Item | Requirement |
| --- | --- |
| Project | ClawMax Workspace/Agent ZIP **or** an accessible project link |
| Native export path | ClawMax → Agents → agent's three-dot menu → Export |
| Project sharing | Screenshot accepts Google Drive, GitHub, or another HTTPS link; it also shows an Upload a file option |
| Optional short note | Tell reviewers what to open or run first |
| Video | **5–10 minutes**; show the Personal Brain, the agent using its memory, and the actual result of one real task |
| Cognee | **No export required**; show adding data, Cognify, Search, and how the agent uses the result in the video |
| Video link | Google Drive, YouTube, Loom, or another shareable HTTPS link |
| Access | Confirm organizers can open/download the project and watch the video without requesting access |
| Deadline | Screenshot says final video due **September 28, 2026, 12:00 PM ET** |
| Submission action | Save the project artifact/link and save the demo link in their respective form sections |

The screenshot does not show a grading rubric, upload size limit, or mandatory
project-description field. Do not infer those requirements. The noon deadline is
explicitly attached to the video; submitting both items before then is prudent.

## 2. Project identity and pitch

**Project name:** BodyBrain

**Tagline:** Personal health memory you can trace back to its source.

**One-sentence pitch:** BodyBrain turns reviewed health records and personal notes
into a searchable, source-linked memory that can be explored through a 3D anatomy
map and used by specialized ingestion and evidence agents.

**Longer description:**

BodyBrain connects health documents, personal observations, and reference anatomy
in one evidence-backed workspace. Users import a text-based PDF, TXT, Markdown
file, or pasted note, inspect the exact source passages and anatomical mappings,
and choose what to approve. Approved content can be indexed with Cognee and
retrieved with document identities, while answers expose the supporting quotes.
Two ClawMax agents support ingestion drafts and evidence-based answer drafts.
The product also includes a dated record timeline, corrections with version
history, browser notes and bookmarks, and local backup/restore. Separate Synthea
and Fitbit sample workspaces demonstrate source-attributed dataset adapters.
BodyBrain is an organizational and educational prototype, not a diagnostic tool
or a patient-specific scan reconstruction.

The ClawMax integration is implemented and has completed earlier hosted ingestion
and evidence tests, but the current relay is blocked by Cognee raw-file deletion
and listing failures. Keep that current limitation in the submission.

## 3. Copy-ready short note for the portal

> BodyBrain — source-grounded personal health memory with a 3D anatomy interface.
> Start with README.md, then submission/SUBMISSION_GUIDE.md. Run `npm install`,
> `uv sync --project backend --python 3.12`, and `npm run dev`; open
> http://127.0.0.1:3016. Use “Load synthetic demo” in Records & memory and review
> findings before approving them. ClawMax agent definitions, workflows, and setup
> are in integrations/clawmax/. Cognee setup is in integrations/cognee/README.md.
> Local review/recall works without provider credentials. Cognee indexing,
> source-linked retrieval, and indexed-document cleanup passed live checks;
> earlier hosted ClawMax ingestion/evidence runs also passed. The current hosted
> relay is blocked by provider raw-file deletion/pagination errors, disclosed in
> the demo. Test data is clearly labeled; this prototype does not diagnose.

Use the final sentence about disclosure only after including it in the recording.
If the submitted artifact is only a native ClawMax export, shorten the note to
the export's agent names and add the separate project link; the application
source/run instructions belong to the project package.

## 4. What to share

The native workspace export is now available as **bodybrain-2026-09-28.zip**.
It contains both BodyBrain agents, both workflows, and the organization template.
Archive integrity and credential-pattern checks passed. The original was left
unchanged; see [the export review](CLAWMAX_EXPORT_REVIEW.md) for the inspection
scope and restoration limitations. Use this file for the native ClawMax ZIP
upload option.

The combined **BodyBrain-complete-submission-2026-09-28.zip** includes the full
source project plus an identical native export under `submission/clawmax/`.
Share this combined package through a project link when you want reviewers to
receive the application and exported agents together. The native export alone
does not include the shared skill implementation or detached relay worker.

The local source package contains the current application, anatomy assets and
attribution, backend tests, dataset adapters, and the ClawMax templates/workflows/
worker code. It is a **project source ZIP**, not a native ClawMax Agent export.
It excludes local record stores, actual environment secrets, runtime caches,
installed dependencies, and Git history. Provider credentials must be supplied
privately by whoever runs the integrations.

Two valid preparation paths:

1. **Project link:** upload the prepared source ZIP to your chosen Drive location
   and use its accessible HTTPS link, or publish the reviewed current source to
   GitHub. Verify access before checking the portal's access box.
2. **Native ClawMax export:** export both `bodybrain-ingestion` and
   `bodybrain-evidence` (or the workspace containing both). Use the portal's file
   upload or an accessible link. Inspect the downloaded archive before sharing;
   exclude credential/session files and private conversation data if present.

The public repository is https://github.com/ritzzi23/BodyBrain . The older
`nyu_personal_agent_hack` repository URL redirects there. Repository visibility
was verified as public during release preparation. Use GitHub for current source
and the native export; previously prepared source ZIPs are snapshots and do not
include later hosted-frontend changes.

The `bodybrain.zip` produced by `integrations/clawmax/package_bundle.py` is a
**skill import archive**. Do not describe that file as a native Agent/Workspace
export. The broader source package includes the definitions needed to recreate
the two agents.

## 5. Eight-minute demo storyboard

| Time | Show | Suggested narration |
| --- | --- | --- |
| 0:00–0:40 | BodyBrain full-body view | “Health information is scattered across reports and personal notes. BodyBrain makes reviewed information searchable and connects it to reference anatomy, with the source always available.” |
| 0:40–1:20 | Search for lumbar spine; select/isolate a structure | “The body is a navigation interface into memory. This is reference anatomy, not a reconstruction of someone's scan.” |
| 1:20–2:20 | Records & memory; import one clearly fictional note or open a synthetic draft | “Imports start as drafts. The system extracts source passages and proposes anatomical links; it does not silently approve them.” |
| 2:20–3:10 | Exact quote, source view, review selection, human approval | “I can inspect and correct the source before making it available for recall. Unapproved findings stay out of answers.” |
| 3:10–4:20 | Cognee Add, Cognify completion, and Search result with source identity | “Cognee indexes the approved content. Retrieval returns attributable source material. A healthy connection alone is not evidence that indexing succeeded.” |
| 4:20–5:30 | Ask the real task question; inspect the returned quote and original record | “The task is to recover what these records actually document. Here is the answer's evidence, including where it came from.” |
| 5:30–6:20 | ClawMax's two agents and a verified completed execution, if available | “The ingestion agent proposes review findings; the evidence agent drafts from permitted passages. BodyBrain validates their outputs. Earlier hosted runs completed; the current relay is blocked by provider file cleanup/listing errors.” |
| 6:20–7:05 | Timeline and correction/version history; optionally show dataset tabs briefly | “History remains inspectable. The clinical and wearable samples are separate source participants, not one linked patient.” |
| 7:05–8:00 | Architecture, delivered result, current limits | “The delivered result is an inspectable health-memory workflow: import, review, index, retrieve, and verify. The next operational step is repairing the hosted relay and verifying sustained agent recovery.” |

### Important gap for the recording

The portal specifically asks to show **the agent using Cognee's retrieved result**.
Today's independent Cognee test passed, and earlier ClawMax tests passed, but
those separate checks do **not** prove a fresh combined end-to-end run today.
The current hosted relay is not ready. If you submit in this state, show the
working components and genuine earlier execution evidence, explain the current
gap, and do not present a local fallback as a successful ClawMax run. This may
leave that requested portion of the demo only partially demonstrated.

If no earlier recording exists, an execution/task log can document the earlier
run but is not a substitute for claiming a new live run. Keep pending results,
local-evidence labels, and error states visible and accurately described.

### Concrete task and source text

Use the built-in **Load synthetic demo** records for a coherent story:

- March 15: fictional lumbar MRI report with an L5–S1 finding.
- March 19: fictional follow-up note referring to physiotherapy.
- April 20: fictional personal recovery observation.

Suggested question:

> What do my approved records document about the lumbar spine and physiotherapy?

Read the answer actually produced; verify each quote. Do not claim an answer
establishes what caused the change or supplies a diagnosis. For the missing-
information boundary, ask what medication dose is recorded: the source records
no dose, so do not invent one.

For a minimal standalone import, use:

```text
SYNTHETIC DEMO RECORD — not a real patient.
Report date: 2026-09-28
No fracture of the left femur.
This record is fictional and is used only to demonstrate source-linked recall.
```

Question: “What does this source document about the left femur?”

Use only synthetic records in a hosted recording test. The separate sample apps
at ports 3018 and 3019 deliberately disable Cognee and ClawMax; use the ordinary
app at port 3016 to demonstrate configured memory integration.

## 6. Architecture explanation for judges

```text
User's source → extraction / optional ClawMax ingestion draft
              → exact-source validation → human review
              → approved local record → Cognee Add + Cognify

Question + anatomy scope → Cognee Search (or labeled local fallback)
                         → approved evidence
                         → optional ClawMax evidence draft
                         → exact-source citation validation → displayed result
```

- Frontend: React, TypeScript, Three.js.
- Backend: FastAPI/Python, SQLite, private source storage.
- Memory: Cognee REST indexing and source-linked chunk retrieval.
- Agents: ClawMax ingestion and evidence roles; optional per-operation consent.
- Transport: an explicit Cognee file relay, separate from approved-memory search.
- Anatomy: 2,234 meshes, 3,432 named concepts, 15 systems; attribution is in
  `public/ATTRIBUTION.md`, with the Human Atlas license retained.
- Dataset adapters: 22 Synthea clinical summaries and 7 Fitbit daily summaries
  in the prepared samples; unrelated subjects and separate local stores.

## 7. Accurate status and boundaries

**Verified:** local import/review/recall; timeline and corrections; independent
live Cognee indexing/retrieval/indexed-document cleanup; earlier hosted ClawMax
ingestion/evidence; 370 backend tests plus 95 subtests; 13 frontend tests and the
production build in the preceding verification; local supervisor restart recovery.

**Currently blocked:** live ClawMax relay readiness, because unindexed-file
deletion returns HTTP 500 and the result dataset listing repeats the same 1,000
files. The heartbeat-growth fix is tested locally and is not deployed to the host.

**Not demonstrated:** reliable hosted container/reboot recovery, clinical accuracy,
diagnosis or treatment advice, patient-specific scan interpretation, live Fitbit
account synchronization, or a causal connection between the two sample datasets.
Physical Mac login/reboot recovery has not been tested either.

## 8. Final submission sequence

1. Finish a 5–10 minute recording and play it back: narration is audible, text is
   readable, and no credentials or private records appear.
2. Share the reviewed project artifact/export and video using the chosen hosts.
3. Open both final links while signed out (or in an incognito window). Confirm
   project download/access and video playback without an access request.
4. In the project section, paste the project link or upload the appropriate ZIP;
   paste the short note; check access confirmation only after verification; save.
5. In the video section, paste the video URL; verify access; check the confirmation;
   click **Save demo link**.
6. Reopen the submission page and confirm both saved entries remain visible.
   Retain a confirmation screenshot before the deadline.

No video has been recorded or uploaded by this preparation. Publishing GitHub
source and the Vercel frontend does not submit the portal form. No portal access
confirmation boxes have been checked and no portal submission has been made.
