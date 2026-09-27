# Cognee memory for BodyBrain

BodyBrain uses a real Cognee dataset for persistent semantic memory. The adapter
accepts approved documents, ingests them, waits for graph construction to finish,
and retrieves source chunks scoped to that dataset. It does not substitute local
search and label the result as Cognee. When disabled or unavailable, its status
and operations report that explicitly.

## Connect a hosted instance

For Cognee Cloud, copy your account's **API Base URL** from the dashboard's
**API Keys** page. Cloud uses a per-tenant host; the API key's display name does
not identify this host. For a hackathon instance, use the URL supplied by the
organizer instead.

```dotenv
COGNEE_MODE=rest
COGNEE_URL=https://your-tenant.aws.cognee.ai
COGNEE_API_KEY=your-cognee-cloud-key
COGNEE_DATASET=bodybrain
```

Replace `your-tenant` with the exact host shown in your dashboard. Do not use
the old shared `https://api.cognee.ai` endpoint. See the current
[Cognee API setup instructions](https://docs.cognee.ai/api-reference/introduction).

Cloud authentication uses `X-Api-Key`. An authenticated self-hosted instance
instead uses the token obtained from that instance's login endpoint:

```dotenv
COGNEE_MODE=rest
COGNEE_URL=http://127.0.0.1:8000
COGNEE_BEARER_TOKEN=your-self-hosted-access-token
COGNEE_DATASET=bodybrain
```

Set only one authentication method. For a self-hosted instance with authentication
disabled, leave both credentials empty. The URL may include `/api/v1`; the adapter
normalizes it. Dataset names must identify datasets owned by the authenticated
account; shared datasets requiring a UUID are not supported by this first version.

The Cognee plugin for Codex is a separate integration. Its `~/.cognee/.env` and
`COGNEE_BASE_URL` configure the coding assistant. BodyBrain reads the repository's
`.env` and `COGNEE_URL`; it does not require the Codex plugin or Codex hooks.

REST mode requires only the backend's `httpx` dependency. The Cognee server owns
its graph, vector, relational, and document storage; keep its persistent volumes
when restarting it. BodyBrain's SQLite database and Cognee's memory are separate
stores and both need to persist for evidence links to remain useful.

## Optional local Python SDK

The SDK is imported only when an actual operation is requested in `sdk` mode.
It is intentionally optional because it installs its own database, embedding,
and model dependencies. The upstream version inspected for this implementation
is `1.6.1`. From the repository root, install into the backend's environment:

```sh
uv pip install --python backend/.venv/bin/python 'cognee==1.6.1'
```

Configure the backend:

```dotenv
COGNEE_MODE=sdk
COGNEE_DATASET=bodybrain
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=your-authorized-model-provider-key
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=openai/text-embedding-3-large
EMBEDDING_DIMENSIONS=3072
```

Use Cognee's documented provider environment variables to choose your LLM and
embedding model. `LLM_API_KEY` belongs to the model provider; `COGNEE_API_KEY`
belongs to Cognee Cloud and is not an LLM key. In this example, embeddings use
`LLM_API_KEY` unless `EMBEDDING_API_KEY` is set separately. Use a provider key whose
permissions cover both selected models and whose allowed use includes Cognee.
An organizer key described as being for ClawMax does not establish that permission.

The adapter delegates extraction configuration to Cognee. Cognee 1.6.1 also
documents a keyless GLiNER/fastembed path; do not assume that omitting model keys
produces the same behavior as the explicit provider configuration above. Verify
the selected configuration with a synthetic record and a real retrieval round trip.

Restart the backend after changing `.env`. Installing the SDK does not enable it;
`COGNEE_MODE=sdk` selects embedded memory. This optional installation is outside
the project's current core dependency lock, so a subsequent plain `uv sync` may
remove it; rerun the SDK installation command if needed.

The app passes a persistent `storage_path` to the adapter. SDK relational, graph,
and vector storage goes under `<storage_path>/system`, and ingested data goes
under `<storage_path>/data`. Keep both directories across restarts. Run one
BodyBrain worker for this embedded mode; SDK path configuration is process-global
and multiple embedded writers are not supported by the adapter.

## API contract and provenance

The public adapter methods are:

```python
memory = CogneeMemory(
    mode="rest",
    base_url="https://your-cognee-instance",
    api_key="...",  # or bearer_token for self-hosted authentication
    dataset="bodybrain",
)
await memory.remember(document_id, approved_text, metadata)
await memory.recall(query, limit=5)
await memory.forget(document_id)  # REST: removes this document only
await memory.status(probe=True)
```

- `remember` sends multipart `data` and `datasetName` to `POST /api/v1/add`, then
  JSON `datasets` and `run_in_background: false` to `POST /api/v1/cognify`.
  Only completed pipeline records produce `status: indexed`. Queued, errored,
  empty, and malformed responses raise `CogneeError`.
- `recall` uses `POST /api/v1/search` with `search_type: CHUNKS`, `query`, `datasets`,
  and `top_k`. This retrieves source text without a generated answer. A returned
  score is the provider's raw distance, where lower is better, not confidence.
- SDK mode calls the corresponding `cognee.add`, `cognee.cognify`, and
  `cognee.search(query_type=cognee.SearchType.CHUNKS)` methods.
- Documents carry a stable `bodybrain_<document_id>.txt` upload name, a node-set
  reference, reviewed metadata, and repeated `[[bodybrain-document:<id>]]`
  markers so retrieved chunks can be associated with the original record.
- `recall` returns `results` with `text`, `document_ids`, and the raw provider
  record, plus a combined `document_ids` list. These are candidate IDs, **not
  verified citations**. The application must check the source and exact quote
  against its approved SQLite records before answering or highlighting anatomy.
- `status` distinguishes configured from reachable. A successful `/health` probe
  does not prove authentication, dataset permissions, or model readiness. A
  missing SDK never prevents the rest of the backend from starting.
- REST `forget` resolves the exact configured dataset and uploaded
  `bodybrain_<document_id>.txt` filename across all data pages, then deletes only
  that data item. It never deletes the dataset or other documents. Ambiguous
  listings, inaccessible datasets, and unfinished deletion responses fail safely.
  SDK uploads historically use generated filenames; SDK deletion is explicitly
  unsupported until equivalent source identity is available.

Identical upload retries use the same filename/content. A new version of a report
should have a new BodyBrain document ID; Cognee's add endpoint refuses changed
content under an existing filename. If adding succeeds and graph construction
fails, the app can retain the failure state and retry indexing that document.

The connection contract is covered by mocked tests, including failed/queued
pipelines, source provenance, dataset scoping, safe errors, and lazy SDK setup:

```sh
PYTHONPATH=backend python3 -m unittest discover -s backend/tests -p test_cognee_memory.py -v
```

These tests do not prove live instance connectivity. A configured instance and an
approved sample upload are required to verify the complete memory round trip.

After enabling Cognee, newly approved records queue indexing automatically.
Previously approved records marked `unconfigured` need an explicit index retry
through the record UI or `POST /api/records/{id}/index`. Startup resumes only
records already marked `pending`; it does not bulk-upload older records.

## Verified upstream references

- [Model-provider configuration](https://docs.cognee.ai/setup-configuration/llm-providers)
- [Pinned SDK environment template](https://github.com/topoteretes/cognee/blob/v1.6.1/.env.template)
- [REST deployment and authentication](https://docs.cognee.ai/api-reference/introduction)
- [REST multipart ingestion contract](https://github.com/topoteretes/cognee/blob/main/cognee/api/v1/add/routers/get_add_router.py)
- [REST foreground graph construction](https://github.com/topoteretes/cognee/blob/main/cognee/api/v1/cognify/routers/get_cognify_router.py)
- [REST search payload and dataset scoping](https://github.com/topoteretes/cognee/blob/main/cognee/api/v1/search/routers/get_search_router.py)
- [SDK search signature](https://github.com/topoteretes/cognee/blob/main/cognee/api/v1/search/search.py)
- [SDK persistent storage configuration](https://github.com/topoteretes/cognee/blob/main/cognee/api/v1/config/config.py)
- [Source chunk retrieval behavior](https://github.com/topoteretes/cognee/blob/main/cognee/modules/retrieval/chunks_retriever.py)
