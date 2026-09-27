"""Small ClawMax v1.9.9 dashboard API adapter.

The API contract was verified against Maximilien-ai/clawmax tag v1.9.9,
commit 381f4ff928a74dfee60f4cb628f40068e8c70c37. Never treat submission as
successful document ingestion: BodyBrain's authenticated callback is the result.
"""

from __future__ import annotations

import re
from typing import Any, Literal, TypedDict
from urllib.parse import urlsplit

import httpx


class ClawMaxResult(TypedDict, total=False):
    provider: Literal["clawmax"]
    status: str
    configured: bool
    workflow_id: str
    execution_id: str
    message: str
    http_status: int
    participants: list[dict[str, str]]


class ClawMaxClient:
    """Use one client per workflow, or pass an explicit workflow_id per call.

    ``base_url`` is the dashboard origin, optionally with a deployment prefix,
    not its /api path. ``token`` is DASHBOARD_TOKEN or a valid session bearer.
    Tokens and upstream bodies are intentionally absent from returned errors.
    """

    def __init__(
        self,
        base_url: str = "",
        token: str = "",
        workflow_id: str = "",
        *,
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.strip().rstrip("/")
        self._token = token.strip()
        self.workflow_id = workflow_id.strip()
        self.timeout = timeout
        self._transport = transport
        if self.base_url:
            parsed = urlsplit(self.base_url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("CLAWMAX_URL must be an HTTP(S) dashboard URL without credentials or query parameters")
        if self.workflow_id:
            self._validate_workflow_id(self.workflow_id)

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self._token and self.workflow_id)

    @staticmethod
    def _validate_workflow_id(workflow_id: str) -> None:
        if not re.fullmatch(r"[a-z0-9-]{1,200}", workflow_id):
            raise ValueError("Invalid ClawMax workflow ID")

    def _base_result(self, workflow_id: str, status: str, **fields: Any) -> ClawMaxResult:
        return {
            "provider": "clawmax",
            "status": status,
            "configured": bool(self.base_url and self._token and workflow_id),
            "workflow_id": workflow_id,
            **fields,
        }

    def _get_workflow_id(self, workflow_id: str | None) -> str:
        selected = self.workflow_id if workflow_id is None else workflow_id
        if selected:
            self._validate_workflow_id(selected)
        return selected

    async def _request(
        self, method: str, path: str, workflow_id: str, body: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, ClawMaxResult | None]:
        if not (self.base_url and self._token and workflow_id):
            return None, self._base_result(
                workflow_id,
                "unconfigured",
                message="Configure CLAWMAX_URL, CLAWMAX_TOKEN, and the workflow ID to enable ClawMax.",
            )
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                transport=self._transport,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
                    json=body,
                )
        except httpx.TimeoutException:
            # A timed-out POST can have been accepted. Never automatically retry it.
            return None, self._base_result(
                workflow_id, "error", message="ClawMax request timed out; check its execution history before retrying."
            )
        except httpx.RequestError:
            return None, self._base_result(workflow_id, "error", message="ClawMax could not be reached.")
        if not response.is_success:
            descriptions = {
                401: "ClawMax rejected the configured token.",
                403: "ClawMax denied this request.",
                404: "The configured ClawMax workflow or execution was not found.",
            }
            return None, self._base_result(
                workflow_id,
                "error",
                http_status=response.status_code,
                message=descriptions.get(response.status_code, "ClawMax returned an unsuccessful response."),
            )
        try:
            data = response.json()
        except ValueError:
            return None, self._base_result(workflow_id, "error", message="ClawMax returned invalid JSON.")
        if not isinstance(data, dict):
            return None, self._base_result(workflow_id, "error", message="ClawMax returned an unexpected response.")
        return data, None

    async def health(self, workflow_id: str | None = None) -> ClawMaxResult:
        """Read the actual workflow and its resolved agents; never starts work."""
        selected = self._get_workflow_id(workflow_id)
        data, error = await self._request("GET", f"/api/workflows/{selected}", selected)
        if error is not None:
            return error
        assert data is not None
        if data.get("id") != selected or not isinstance(data.get("resolvedParticipants"), list):
            return self._base_result(selected, "error", message="ClawMax returned unexpected workflow details.")
        if not data["resolvedParticipants"]:
            return self._base_result(selected, "error", message="The ClawMax workflow has no resolved agents. Apply the BodyBrain agent bundle.")
        return self._base_result(selected, "ready", message="ClawMax workflow is reachable and has agent participants.")

    async def trigger(
        self, inputs: dict[str, str], workflow_id: str | None = None
    ) -> ClawMaxResult:
        """Submit a real workflow. Inputs are persisted by ClawMax: no secrets.

        v1.9.9 injects ``Run Instructions`` into the runtime prompt. Other input
        keys alone are not sufficient to tell the executing agent its task ID.
        """
        selected = self._get_workflow_id(workflow_id)
        if not isinstance(inputs, dict) or any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in inputs.items()
        ):
            raise ValueError("ClawMax workflow inputs must map strings to strings")
        data, error = await self._request(
            "POST", f"/api/workflows/{selected}/trigger", selected, {"inputs": inputs}
        )
        if error is not None:
            return error
        assert data is not None
        execution_id = data.get("executionId")
        if (
            not isinstance(execution_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", execution_id)
            or data.get("workflowId") != selected
        ):
            return self._base_result(selected, "error", message="ClawMax did not return a valid execution reference.")
        return self._base_result(
            selected,
            "submitted",
            execution_id=execution_id,
            message="ClawMax accepted the workflow; its result is still pending.",
        )

    async def trigger_task(self, task_id: str, workflow_id: str | None = None) -> ClawMaxResult:
        """Only an opaque task identifier leaves BodyBrain in the trigger body."""
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id):
            raise ValueError("Invalid BodyBrain task ID")
        return await self.trigger(
            {"Run Instructions": f"Process BodyBrain task {task_id} using the installed BodyBrain skill. Fetch the task from the configured backend, follow the assigned task type, and submit the validated result. Never approve findings."},
            workflow_id=workflow_id,
        )

    async def execution(self, execution_id: str, workflow_id: str | None = None) -> ClawMaxResult:
        selected = self._get_workflow_id(workflow_id)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", execution_id):
            raise ValueError("Invalid ClawMax execution ID")
        data, error = await self._request(
            "GET", f"/api/workflows/{selected}/executions/{execution_id}", selected
        )
        if error is not None:
            return error
        assert data is not None
        status = data.get("status")
        if (
            data.get("id") != execution_id
            or data.get("workflowId") != selected
            or status not in {"running", "completed", "failed", "paused"}
            or not isinstance(data.get("participants"), list)
        ):
            return self._base_result(selected, "error", message="ClawMax returned unexpected execution details.")
        participants = [
            {"agent_id": str(participant.get("agentId", "")), "status": str(participant.get("status", "unknown"))}
            for participant in data["participants"]
            if isinstance(participant, dict)
        ]
        if not participants:
            return self._base_result(
                selected, "error", execution_id=execution_id,
                message="ClawMax ran without agent participants; no BodyBrain work was performed.",
            )
        return self._base_result(
            selected, status, execution_id=execution_id, participants=participants,
            message="ClawMax execution status. BodyBrain task validation determines whether its result was accepted.",
        )
