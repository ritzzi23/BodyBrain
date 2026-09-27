"""Credential-free, immutable envelopes shared with the hosted ClawMax worker."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import hashlib
import json
import re
from uuid import UUID

MAX_BYTES = 2 * 1024 * 1024
TASK_SCHEMA = "bodybrain.clawmax.task.v1"
RESULT_SCHEMA = "bodybrain.clawmax.result.v1"


def canonical_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _time(value: str) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("Invalid relay timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Relay timestamps require a timezone")
    return parsed.astimezone(timezone.utc)


def _id(value: str) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Invalid relay task identifier")
    return value


def _load(raw: bytes) -> dict:
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("Relay envelope exceeds its size limit")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate relay envelope key")
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON number")))
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("Invalid relay JSON encoding or nesting") from exc
    if not isinstance(value, dict):
        raise ValueError("Expected a relay object")
    return value


def make_task(task_id: str, kind: str, payload: dict, *, ttl_seconds: int = 900) -> dict:
    created = utc_now()
    task = {"schema": TASK_SCHEMA, "task_id": _id(task_id), "kind": kind,
            "created_at": created.isoformat(), "expires_at": (created + timedelta(seconds=ttl_seconds)).isoformat(),
            "payload": payload}
    task["digest"] = hashlib.sha256(canonical_bytes(task)).hexdigest()
    return parse_task(canonical_bytes(task))


def parse_task(raw: bytes) -> dict:
    task = _load(raw)
    if set(task) != {"schema", "task_id", "kind", "created_at", "expires_at", "payload", "digest"}:
        raise ValueError("Unexpected relay task fields")
    if task["schema"] != TASK_SCHEMA or not isinstance(task["kind"], str) or task["kind"] not in {"ingestion", "evidence"}:
        raise ValueError("Unsupported relay task")
    _id(task["task_id"])
    if not isinstance(task["payload"], dict):
        raise ValueError("Invalid relay task payload")
    created, expires = _time(task["created_at"]), _time(task["expires_at"])
    if not 0 < (expires - created).total_seconds() <= 3600:
        raise ValueError("Invalid relay task lifetime")
    if created > utc_now() + timedelta(minutes=2):
        raise ValueError("Relay task creation time is in the future")
    digest = task["digest"]
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Invalid relay digest")
    if digest != hashlib.sha256(canonical_bytes({k: v for k, v in task.items() if k != "digest"})).hexdigest():
        raise ValueError("Relay task integrity check failed")
    return task


def task_filename(task: dict) -> str:
    return f"bb_task_{_id(task['task_id'])}_{task['digest']}.txt"


def result_filename(task: dict) -> str:
    return f"bb_result_{_id(task['task_id'])}_{task['digest']}.txt"


def is_expired(task: dict) -> bool:
    return _time(task["expires_at"]) <= utc_now()


def make_result(task: dict, status: str, result: dict | None = None, error: str | None = None, *, execution: dict | None = None) -> dict:
    value = {"schema": RESULT_SCHEMA, "task_id": task["task_id"], "task_digest": task["digest"],
             "status": status, "result": result, "error": error, "completed_at": utc_now().isoformat()}
    if execution is not None:
        value["execution"] = execution
    return parse_result(canonical_bytes(value), task)


def parse_result(raw: bytes, task: dict) -> dict:
    value = _load(raw)
    fields = {"schema", "task_id", "task_digest", "status", "result", "error", "completed_at"}
    if set(value) not in (fields, fields | {"execution"}):
        raise ValueError("Unexpected relay result fields")
    if value["schema"] != RESULT_SCHEMA or value["task_id"] != task["task_id"] or value["task_digest"] != task["digest"]:
        raise ValueError("Relay result does not match the requested task")
    if not isinstance(value["status"], str) or value["status"] not in {"completed", "failed"}:
        raise ValueError("Invalid relay result state")
    if value["status"] == "completed" and (not isinstance(value["result"], dict) or value["error"] is not None):
        raise ValueError("Invalid completed relay result")
    if value["status"] == "failed" and (value["result"] is not None or not isinstance(value["error"], str) or not 1 <= len(value["error"]) <= 300):
        raise ValueError("Invalid failed relay result")
    finished = _time(value["completed_at"])
    if finished > utc_now() + timedelta(minutes=2) or finished < _time(task["created_at"]) - timedelta(minutes=2):
        raise ValueError("Invalid relay completion time")
    execution = value.get("execution", {})
    if not isinstance(execution, dict) or set(execution) - {"agent_id", "session_id", "provider", "model", "duration_ms", "input_tokens", "output_tokens"}:
        raise ValueError("Invalid relay execution metadata")
    for key, item in execution.items():
        if key in {"duration_ms", "input_tokens", "output_tokens"}:
            if type(item) is not int or not 0 <= item <= 1_000_000_000:
                raise ValueError("Invalid relay execution counter")
        elif not isinstance(item, str) or len(item) > 200:
            raise ValueError("Invalid relay execution label")
    return value
