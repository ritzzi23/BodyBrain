# BodyBrain × ClawMax

This bundle gives ClawMax two jobs: extract a review draft from an uploaded
report, and answer a question from approved evidence. BodyBrain supports the
original dashboard API/callback transport and an implemented
[automatic Cognee relay](#automatic-cognee-relay-transport). Both preserve
per-operation consent, exact-source validation, and human approval before
Cognee indexing.

Agent registration and worker deployment are separate steps. See
[PROJECT_AUDIT.md](../../PROJECT_AUDIT.md) for this workspace's actual deployment
status. Configuration and local fallback are not proof of a live ClawMax run.
The dashboard instructions below apply to the original transport; the relay
needs neither a dashboard API token nor a public callback service.

## Hosted dashboard installation

The assigned hosted dashboard was verified as **v1.9.10-test-cognee2**. Build the
portable artifacts from the repository root:

```sh
backend/.venv/bin/python integrations/clawmax/package_bundle.py
```

1. In **Skills**, import `.runtime/clawmax-deploy/bodybrain.zip` using **Upload ZIP**.
   The ZIP includes the skill and its Python helper. A laptop directory path is
   not a directory on the hosted server.
2. In **Templates → Actions → Import TEMPLATE.md**, upload
   `.runtime/clawmax-deploy/TEMPLATE.md`. It embeds both agent identities, tool
   policies, and workflow definitions. Importing a template alone does not create
   running agents.
3. Apply **BodyBrain** with no prefix/suffix and a working hosted model. Confirm
   `bodybrain-ingestion` and `bodybrain-evidence` exist as both agents and workflows,
   and the `bodybrain` skill is assigned to both agents.
   Check the deployment prerequisite screen and verify actual tool/skill
   execution. This tag can fall back to `openclaw agent --local` when a gateway is
   unavailable, so a gateway warning alone is not proof that execution is blocked.
A working execution model is also required for backend-triggered runs.
   Browser-only BYOK settings are not proof that unattended API runs can execute.
4. Obtain a dashboard API credential from the instance operator and save it as
   `CLAWMAX_TOKEN` in the project `.env`. This version has no personal API-token
   creation screen. A Cognee key or a model-provider key is not a dashboard token.
5. Configure the callback service and actual worker environment below before
   running either workflow. Browser-local **Workspace Keys** and **Global Keys**
   are not exposed to agent subprocesses.

### Callback service for hosted agents

Start BodyBrain normally, then separately run:

```sh
npm run backend:worker-proxy
```

This service binds to `127.0.0.1:8081` and requires `BODYBRAIN_AGENT_TOKEN`. It exposes
only the three authenticated worker routes listed below. Point a separately
configured TLS tunnel at **8081**, never the ordinary backend on 8080. The proxy
does not expose records, source downloads, chat, review, approval, or deletion.
It forwards to the fixed local backend with bounded bodies/timeouts, no redirects,
no automatic POST retries, and no access log. `npm run dev` never starts a tunnel.

The ClawMax operator must make these values available in the **actual Python tool
process** for just the two BodyBrain agents:

```dotenv
BODYBRAIN_BACKEND_URL=https://<callback-tunnel-host>
BODYBRAIN_AGENT_TOKEN=<same dedicated token as the project .env>
```

On this hosted version, setting arbitrary dashboard environment variables is
insufficient: `safeEnv()` does not pass `BODYBRAIN_*` through. The operator must
provide scoped runtime injection or an equivalent supported integration. The
browser's secret broker currently registers only the built-in test skill; a new
BodyBrain grant alone does not create a callable broker action. Do not place the
token in agent Markdown, workflow inputs, or the trigger's `secrets` field: this
version persists the latter in execution inputs.

Verify connectivity using only synthetic tasks before opting real records into
agent processing. A dashboard health response or an accepted workflow does not
prove model execution or a validated callback.

### Information needed from the hosted instance operator

- An API credential for the assigned dashboard origin, saved locally as
  `CLAWMAX_TOKEN` through a private channel.
- Functioning Python 3 skill execution (gateway or verified local-agent fallback)
  and provider credentials available to API-triggered workflows. A model name
  alone is insufficient. This tag's successful OpenAI-compatible BYOK execution
  persists credentials in the hosted OpenClaw provider config; verify subsequent
  backend-triggered execution rather than inferring it from browser validation.
- A supported way to inject the callback URL and dedicated worker token into
  only the two BodyBrain agents' tool processes. Check presence without printing
  the token. The token should never enter chat, workflow inputs, or template files.

### OpenAI keys restricted to Chat Completions

On this tag, native OpenAI **Check Key** tests Chat Completions, while native
OpenAI agent execution uses Responses. A verified key can therefore still fail
an agent run with `Missing scopes: api.responses.write`. This workspace's key
was validated through the supported **OpenAI-Compatible** path instead:

- Base URL: `https://api.openai.com/v1` (the official OpenAI API).
- Default model: `gpt-4.1-mini`; run **Check Connection**, then save.
- Each agent's **More actions → Edit** model: `openai-compatible/gpt-4.1-mini`.
- No backup model; validate an actual synthetic agent response afterward.

This uses the key's existing Chat Completions access. It does not grant Responses
permissions. The tag's compatible-provider validation uses `max_tokens`, which
is rejected by GPT-5.4 Mini; a discovered model is not automatically compatible
with every client request shape. Unlike the browser-only settings save, compatible
agent execution also persists the API key in the hosted OpenClaw provider
configuration. Do not assume that this key remains exclusively in the browser.
Verify a subsequent backend-triggered workflow separately once its dashboard
API credential and callback connection are configured.

## Filesystem installation for an operator-managed workspace

1. Copy `TEMPLATES/organizations/bodybrain` to the active ClawMax workspace's
   `TEMPLATES/organizations/bodybrain` directory. Review an existing folder before
   replacing it.
2. Copy `SKILLS/custom/bodybrain` to that workspace's `SKILLS/custom/bodybrain`.
   It includes the Python helper, not just the Markdown skill.
3. In ClawMax Templates, select the **BodyBrain** organization template and apply
   it with no prefix/suffix. Select your configured working model. This registers
   the two agents and creates both workflows. Merely copying agent files does
   not register executable agents. Verify both agents can execute Python 3 and
   can see the `bodybrain` skill.
4. Inject the following into the **actual tool process executing the agents**,
   then restart that runtime if necessary. Check the hosted environment restriction
   above; dashboard process variables alone may be filtered out:

   ```dotenv
   BODYBRAIN_BACKEND_URL=http://127.0.0.1:8080
   BODYBRAIN_AGENT_TOKEN=<same worker token configured on the BodyBrain backend>
   ```

   A hosted ClawMax agent cannot use your laptop's `127.0.0.1`. Configure a backend
   address reachable from that runtime. Public hosting/tunnel setup is a separate
   deployment step; this bundle does not expose the local backend. Keep the
   worker token in runtime environment configuration, never workflow inputs or
   Markdown files.
5. Configure `CLAWMAX_URL`, `CLAWMAX_TOKEN`,
   `CLAWMAX_INGEST_WORKFLOW_ID=bodybrain-ingestion`, and
   `CLAWMAX_EVIDENCE_WORKFLOW_ID=bodybrain-evidence` in the BodyBrain backend
   environment. The URL is the dashboard origin (not `/api`). Use the actual IDs
   returned by your template application if you chose a prefix.
6. Verify the integration status from BodyBrain. Then submit one synthetic report,
   run ingestion, review the returned findings in BodyBrain, and approve them.
   Verify actual Cognee indexing separately. Ask a question and check every
   citation against the original report page.

The standalone `WORKFLOWS/*.md` files can alternatively be imported using
ClawMax's workflow Markdown import when you already have the matching agents.
Do not install a second copy of those workflows after applying the template.

## Verified ClawMax API contract

Initially checked against **v1.9.9**, commit
`381f4ff928a74dfee60f4cb628f40068e8c70c37`, and the hosted setup checked against
**v1.9.10-test-cognee2**:

| Operation | Route | Body/result |
|---|---|---|
| Read workflow | `GET /api/workflows/{id}` | Includes `resolvedParticipants` |
| Trigger | `POST /api/workflows/{id}/trigger` | Body `{ "inputs": { "Run Instructions": "...task ID..." } }`; returns `executionId`, `workflowId` |
| Read execution | `GET /api/workflows/{id}/executions/{executionId}` | Includes `status` and `participants` |
| Import workflow | `POST /api/workflows/import-md` | Body `{ "content": "...Markdown..." }` |
| Import portable template | `POST /api/templates/import-md` | Body `{ "content": "...TEMPLATE.md..." }` |
| Import skill archive | `POST /api/skills/import-upload` | ZIP bytes with `x-file-name: bodybrain.zip` |
| Apply local organization template | `POST /api/templates/organizations/import` | Body `{ "templateSlug": "bodybrain" }` |

Authentication is `Authorization: Bearer <token>`. v1.9.9 accepts the dashboard's
`DASHBOARD_TOKEN` or a valid OAuth session bearer. Use a credential issued for your
own instance; nothing here retrieves credentials from a browser.

The model-provider key used by a ClawMax agent is a separate credential. An
organizer may provide that key before inviting you to the ClawMax workspace.
Configure it in the workspace's provider/BYOK settings when access is available;
do not put it in BodyBrain's `CLAWMAX_TOKEN` or `COGNEE_API_KEY` fields. Confirm
with the issuer before reusing an event key for Cognee model calls. See ClawMax's
[provider-key policy](https://github.com/Maximilien-ai/clawmax/blob/v1.9.9/README.md).

ClawMax persists workflow inputs, so the integration sends **no source text,
question, backend token, or LLM key** in the trigger body. `Run Instructions` is
intentional: v1.9.9 injects that field into the execution prompt; arbitrary input
fields alone do not convey the task to the agent. Agent execution will necessarily
process source context through its configured model provider after fetching it.

`submitted` means an execution was accepted, never that extraction, approval, or
Cognee indexing completed. ClawMax's execution state and BodyBrain's validated
task state are separate. A workflow with no resolved agents is an error. A timed
out trigger is not automatically retried, because it may already have started.

Imports and chat do not automatically dispatch just because ClawMax is
configured. The UI requires per-operation opt-in, sent as `allow_agent=true` in
the import/chat payload (or demo query parameter). Evidence tasks contain only
relevant approved passages selected for the question and anatomy scope. A
question with no matching approved evidence does not dispatch a task.

Source: [workflow routes](https://github.com/Maximilien-ai/clawmax/blob/v1.9.9/SYSTEM/dashboard/server/routes/workflows.ts),
[workflow runtime](https://github.com/Maximilien-ai/clawmax/blob/v1.9.9/SYSTEM/dashboard/server/lib/workflows.ts),
[authentication](https://github.com/Maximilien-ai/clawmax/blob/v1.9.9/SYSTEM/dashboard/server/lib/github-auth.ts),
[template routes](https://github.com/Maximilien-ai/clawmax/blob/v1.9.9/SYSTEM/dashboard/server/routes/templates.ts).

Hosted-version sources: [portable template parser](https://github.com/Maximilien-ai/clawmax/blob/v1.9.10-test-cognee2/SYSTEM/dashboard/server/lib/templates.ts),
[runtime environment filtering](https://github.com/Maximilien-ai/clawmax/blob/v1.9.10-test-cognee2/SYSTEM/dashboard/server/lib/safe-env.ts),
[registered secret-broker actions](https://github.com/Maximilien-ai/clawmax/blob/v1.9.10-test-cognee2/SYSTEM/dashboard/server/lib/skill-secret-broker.ts),
[workflow input persistence](https://github.com/Maximilien-ai/clawmax/blob/v1.9.10-test-cognee2/SYSTEM/dashboard/server/lib/workflows.ts).

## Automatic Cognee relay transport

`cognee_relay` is implemented. After a user opts an import or question into agent
processing, BodyBrain publishes an immutable task file to an isolated Cognee
inbox. A hosted Python worker polls every five seconds, invokes the registered
BodyBrain agent through `openclaw agent --local`, and returns a task-bound result
file. BodyBrain collects and validates it automatically. Idle polling makes no
LLM calls. These are explicit file transfers, not semantic memory searches or
native Cognee plugin hooks.

Use the existing authorized Cognee credentials and configure the backend:

```dotenv
COGNEE_MODE=rest
COGNEE_URL=https://<your-cognee-host>
CLAWMAX_TRANSPORT=cognee_relay
CLAWMAX_RELAY_INBOX=bodybrain_clawmax_jobs
CLAWMAX_RELAY_OUTBOX=bodybrain_clawmax_results
```

The backend uses its existing `COGNEE_API_KEY` or `COGNEE_BEARER_TOKEN`, never
both. The hosted worker requires `COGNEE_API_KEY` in its actual runtime
environment. On the assigned cognee2 host, **Partners → Cognee** provides that
managed environment credential; its **Check Keys** configuration check alone
is not live authentication. Keep the inbox, outbox, and `COGNEE_DATASET` for
approved evidence distinct. The relay does not require `CLAWMAX_TOKEN`, a
public callback URL, or enabling the native Cognee memory plugin.

Build and deploy the hash-pinned worker using
[relay/README.md](relay/README.md). Its nonsecret configuration selects the
Cognee URL, dataset names, registered agent IDs, and model. Defaults are
`bodybrain-ingestion`, `bodybrain-evidence`, and `lmstudio/gpt-4.1-mini`; the
hosted model provider must already work. The installer inherits credentials
without embedding them and refuses to replace an active worker's files.

The transport preserves these boundaries:

- Imports and questions dispatch only with `allow_agent=true`; the UI discloses
  that opted-in text travels through Cognee. An evidence task contains only
  relevant, approved source passages for its question and anatomy scope.
- Task IDs, digests, expiry, result shape, and exact source quotations are
  validated. Ingestion output remains a review draft; the user approves findings
  before they become memory. Neither relay delivery nor an agent result grants
  approval.
- Source deletion or correction revokes obsolete work. Relay files and cached
  worker result bytes are cleaned up, while ID/digest tombstones prevent replay.
  Hosted OpenClaw session transcripts have separate runtime retention; deleting
  a BodyBrain record does not erase that hosted history.
- These are actual registered-agent CLI executions, but they do not create
  native ClawMax workflow execution rows or update its workflow budget tracking.
  BodyBrain Activity records its own submission and validation progress.
- The detached worker has no automatic restart guarantee. A host restart or
  process failure requires an explicit restart or an operator-managed supervisor.

The interface says **ClawMax via Cognee: configured** without inferring that the
worker is live. A recent relay heartbeat proves recent worker contact; a
validated synthetic ingestion and evidence round trip is required to establish
end-to-end operation. Live smoke confirmation is pending for this implementation;
record its outcome in [PROJECT_AUDIT.md](../../PROJECT_AUDIT.md).

## Worker callback contract

The helper exposes only three operations, using `BODYBRAIN_AGENT_TOKEN` as bearer:

- `GET /api/agent/tasks/{task_id}`: retrieve task context.
- `GET /api/agent/anatomy?q=...`: resolve anatomy against BodyBrain's atlas catalog.
- `POST /api/agent/tasks/{task_id}/result`: submit findings or answer/citations.

Task results must contain complete, exact source passages, preserving original
line breaks, decimal numbers, negation, and context. Detached fragments are
rejected even if they are substrings of the source. Mappings must come from the catalog;
unresolved terms remain unassigned. Evidence citations may only reference the
approved sources in that task. Review/approval is a human action. The worker
helper has no review or index command.

## Validation and limitations

`backend/tests/test_clawmax.py` covers real request shapes, authentication,
unconfigured behavior, malformed responses, zero-agent runs, timeout uncertainty,
redirect blocking, and secret redaction with HTTP mock transports. These are
contract tests, not proof of a live hosted execution. Actual runs require your
ClawMax runtime, model configuration, network access, and credentials.

`backend/tests/test_worker_proxy.py` checks the callback boundary, including
denied user routes, malformed requests, size limits, sanitized failures, and
cancellation of in-flight work on timeout. The packager explicitly includes only
the skill Markdown and Python helper, emits SHA-256 metadata, and produces
deterministic upload artifacts without reading `.env`.
