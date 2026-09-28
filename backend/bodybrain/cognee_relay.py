"""Async BodyBrain side of the explicit, unindexed Cognee task handoff."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import re

from .cognee_transport import CogneeFiles, CogneeTransportError
from .relay_protocol import canonical_bytes, parse_result, result_filename, task_filename


def matching_file(files: list[dict], name: str) -> dict | None:
    matches = [f for f in files if f["name"] == name or f["name"] + "." + f.get("extension", "") == name]
    if len(matches) > 1:
        raise ValueError("Ambiguous relay file identity")
    return matches[0] if matches else None


class CogneeRelay:
    def __init__(self, settings):
        self.configured = bool(settings.cognee_mode == "rest" and settings.cognee_url and (settings.cognee_api_key or settings.cognee_token))
        self.inbox = settings.clawmax_relay_inbox
        self.outbox = settings.clawmax_relay_outbox
        self.target_identity = {"base_url": settings.cognee_url.rstrip("/"), "inbox": self.inbox, "outbox": self.outbox}
        self.files = CogneeFiles(settings.cognee_url, api_key=settings.cognee_api_key, bearer_token=settings.cognee_token, timeout=15) if self.configured else None

    async def publish(self, task: dict) -> dict:
        if not self.files:
            raise ValueError("Cognee relay is not configured")
        return await asyncio.to_thread(self.files.put_file, self.inbox, task_filename(task), canonical_bytes(task))

    async def result(self, task: dict) -> dict | None:
        def read():
            dataset = self.files.dataset(self.outbox)
            if not dataset:
                return None
            item = matching_file(self.files.list_files(dataset), result_filename(task))
            return parse_result(self.files.read_file(dataset, item["id"]), task) if item else None
        return await asyncio.to_thread(read)

    async def cleanup(self, task: dict) -> None:
        def remove():
            for name, filename in ((self.inbox, task_filename(task)), (self.outbox, result_filename(task))):
                dataset = self.files.dataset(name)
                if dataset:
                    item = matching_file(self.files.list_files(dataset), filename)
                    if item:
                        self.files.delete_file(dataset, item["id"])
        await asyncio.to_thread(remove)

    async def health(self, workflow_id: str = "") -> dict:
        status = {"provider": "clawmax", "transport": "cognee_relay", "configured": self.configured, "workflow_id": workflow_id}
        if not self.configured:
            return {**status, "status": "unconfigured", "message": "Configure Cognee REST access for the ClawMax relay."}
        def read_heartbeat():
            dataset = self.files.dataset(self.outbox)
            if not dataset:
                return None
            items = [item for item in self.files.list_files(dataset) if re.fullmatch(r"bb_heartbeat_\d+(?:\.txt)?", item["name"])]
            for item in sorted(items, key=lambda row: row["name"], reverse=True)[:5]:
                raw = self.files.read_file(dataset, item["id"])
                if len(raw) > 16_384:
                    continue
                beat = json.loads(raw)
                if not isinstance(beat, dict) or beat.get("schema") != "bodybrain.clawmax.heartbeat.v1":
                    continue
                if not isinstance(beat.get("timestamp"), str):
                    continue
                stamp = datetime.fromisoformat(beat["timestamp"].replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    continue
                age = (datetime.now(timezone.utc) - stamp).total_seconds()
                if -30 <= age <= 120:
                    return beat
            return None
        try:
            beat = await asyncio.to_thread(read_heartbeat)
        except CogneeTransportError as exc:
            message = ("Cognee returned an incomplete or repeated file listing. Check relay retention and provider pagination."
                       if exc.code in {"ambiguous_response", "pagination_limit"}
                       else "Could not verify the ClawMax worker through Cognee.")
            return {**status, "status": "error", "error_code": exc.code, "message": message}
        except (ValueError, KeyError, TypeError):
            return {**status, "status": "error", "message": "Could not verify the ClawMax worker through Cognee."}
        if not beat:
            return {**status, "status": "waiting", "worker_online": False, "message": "Cognee relay is configured; waiting for a recent ClawMax worker heartbeat."}
        if beat.get("status") not in {"idle", "working"}:
            return {**status, "status": "error", "worker_online": True, "worker_state": "degraded", "checked_at": beat["timestamp"], "message": "The ClawMax worker is reachable but reports a processing problem."}
        return {**status, "status": "ready", "worker_online": True, "worker_state": beat["status"], "checked_at": beat["timestamp"], "message": "ClawMax worker heartbeat received through Cognee. Each task result is validated separately."}
