# Hosted ClawMax relay worker

This worker polls separate Cognee task and result datasets and invokes the
registered `bodybrain-ingestion` and `bodybrain-evidence` agents through the
hosted OpenClaw CLI. It does not need a ClawMax dashboard API token. Each task
requires the user's operation-specific consent; BodyBrain still validates exact
source quotations and requires human approval before saving extracted findings.

Idle polling runs every five seconds and does not invoke an LLM. Valid new tasks
start actual registered-agent executions, with a fresh session for each task.
These CLI executions do **not** create ClawMax workflow execution rows or update
its workflow budget bookkeeping. Model availability remains a property of the
hosted OpenClaw runtime, not proof supplied by this installer.

## Build the portable artifact

From the repository root:

```sh
python3 integrations/clawmax/relay/package_worker.py --base-url https://cognee.example.com
```

Replace the example URL with the intended Cognee endpoint. Optional arguments:

| Argument | Default |
| --- | --- |
| `--output-dir` | `.runtime/clawmax-deploy/relay` |
| `--inbox` | `bodybrain_clawmax_jobs` |
| `--outbox` | `bodybrain_clawmax_results` |
| `--model` | `lmstudio/gpt-4.1-mini` |
| `--ingestion-agent` | `bodybrain-ingestion` |
| `--evidence-agent` | `bodybrain-evidence` |

The package contains `worker.py`, `cognee_transport.py`, `relay_protocol.py`,
`config.json`, this README, a source `manifest.json`, a standalone `installer.py`,
and `artifact-manifest.json`. The artifact manifest hashes the installer as well
as all packaged files. The installer embeds exact source bytes, their hashes,
and the nonsecret configuration, so no adjacent package files are needed on
the target host. The packager reads only the explicitly named source files;
it does not read `.env`, credentials, records, or worker state.

## Install on the hosted runtime

The target needs Python 3.10 or newer on a POSIX host, the registered agents,
the OpenClaw CLI, and its configured model provider. The hosted CLI's read-only
help confirmed the `--local`, `--agent`, `--session-id`, `--model`, `--json`,
`--timeout`, `--message`, and long-message `--message-file` options. Agent
execution still requires a successful task result from the target runtime;
the package build alone does not verify it.

Use the trusted artifact manifest to verify the downloaded `installer.py`
SHA-256 before executing it. The launching environment must already contain
`COGNEE_API_KEY`. Do not put the key in a command argument, configuration file,
installer artifact, or chat message. Run only the verified installer:

```sh
python3 installer.py
```

It installs under `~/.bodybrain-clawmax-relay`, sets controlled directories to
mode `0700` and files to `0600`, validates every embedded and installed hash,
and rejects symlinks and unexpected file types at its controlled paths. It
preserves unrelated files and existing task state. An active worker's
`state/worker.lock` causes installation to stop before sources are overwritten.
Only one installer should run at a time.

The installer releases the worker lock before launching a detached Python
process with `--config` and `--state-dir`. The process inherits the existing
environment; the installer never reads or serializes the Cognee key. Standard
input is disconnected, and both output streams append to private `worker.log`.
The launch PID is written to `worker.pid`. Bytecode caching is disabled for the
worker launch so installed source bytes are used.

Successful installer output contains only `installed`, `pid`, `source_hashes`,
and `process_alive`, checked one second after launch. That check proves only
that the process remained alive for one second. Confirm relay operation with
fresh heartbeats and validated synthetic task results before calling it live.

## Supervision and restart

The detached process is **not** a supervised service. A host restart or process
failure requires an explicit restart, or an operator-provided service manager.
Do not claim durable automatic restart from this installer. Stop the existing
worker, confirm its state lock is released, then rerun the verified installer
to upgrade or restart with the same state. Inspect a recorded PID before
sending a signal because PIDs can be reused.

For an operator-configured supervisor, the foreground command is:

```sh
python3 -B -X pycache_prefix=/dev/null ~/.bodybrain-clawmax-relay/worker.py --config ~/.bodybrain-clawmax-relay/config.json --state-dir ~/.bodybrain-clawmax-relay/state
```

The SQLite ledger saves completed results before uploading them; an upload
retry can therefore reuse a saved result without another model invocation.
After a task disappears from the inbox or expires, the worker scrubs cached
result bytes and retains an ID/digest tombstone to avoid executing it again.
An interrupted agent invocation can execute again after restart. One state
directory admits one worker through an exclusive lock; this is not a
distributed lock across multiple hosts. Keep one active worker per relay
dataset pair. Task data and logs remain private local files; the worker sends
task results and bounded heartbeats through the configured Cognee datasets.

Heartbeat retention deletes this worker's older heartbeats before publishing a
replacement, keeping at most three tracked heartbeat uploads. Upload intent is
recorded before the network call so a lost response remains recoverable after
restart. If scoped deletion or ownership verification fails, no replacement is
uploaded; the visible heartbeat eventually becomes stale. Provider deletion must
work for continuous operation. Do not index relay datasets or discard the worker
ledger to work around a deletion failure.

The file client fails closed when a provider repeats a listing page. A relay
dataset at the provider's listing cap cannot be safely treated as complete;
repair provider pagination and scoped deletion before resuming normal operation.

Hosted OpenClaw session transcripts are retained separately by that runtime.
Deleting a BodyBrain record and its relay files does not erase those hosted
transcripts. Apply the hosted runtime's own retention controls when required.

An example systemd user unit is provided in `bodybrain-relay.service`. It is not
installed by the packager or in the currently verified hosted environment. An
operator with supported host access must adapt it, provide a private
`~/.config/bodybrain/relay.env` through the host's credential mechanism, stop the
detached worker, and enable exactly one supervisor. Verify process-crash and
host-reboot recovery separately; a live heartbeat alone does not prove either.
