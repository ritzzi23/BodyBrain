"""Contract tests against the documented v1.9.9 shapes; no live credentials."""

import json

import httpx
import pytest

from bodybrain.clawmax import ClawMaxClient


def client(handler, **kwargs):
    return ClawMaxClient(
        base_url="https://clawmax.example.test",
        token="test-dashboard-token",
        workflow_id="bodybrain-ingestion",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


async def test_unconfigured_never_calls_network():
    def forbidden(_request):
        raise AssertionError("Unconfigured integration must never perform a request")

    adapter = ClawMaxClient(transport=httpx.MockTransport(forbidden))
    assert not adapter.configured
    assert (await adapter.health())["status"] == "unconfigured"
    assert (await adapter.trigger_task("task-123"))["status"] == "unconfigured"
    assert (await adapter.execution("exec-123"))["status"] == "unconfigured"


async def test_trigger_uses_real_route_and_run_instructions_without_credentials():
    def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/api/workflows/bodybrain-ingestion/trigger"
        assert request.headers["Authorization"] == "Bearer test-dashboard-token"
        body = json.loads(request.content)
        assert set(body) == {"inputs"}
        assert "task-123" in body["inputs"]["Run Instructions"]
        assert "test-dashboard-token" not in request.content.decode()
        return httpx.Response(200, json={"workflowId": "bodybrain-ingestion", "executionId": "exec-123"})

    result = await client(handler).trigger_task("task-123")
    assert result["status"] == "submitted"
    assert result["execution_id"] == "exec-123"


async def test_health_requires_actual_resolved_agent():
    def handler(request):
        assert request.url.path == "/api/workflows/bodybrain-ingestion"
        return httpx.Response(200, json={"id": "bodybrain-ingestion", "resolvedParticipants": [{"id": "bodybrain-ingestion"}]})

    assert (await client(handler).health())["status"] == "ready"
    adapter = client(lambda _: httpx.Response(200, json={"id": "bodybrain-ingestion", "resolvedParticipants": []}))
    assert (await adapter.health())["status"] == "error"


async def test_execution_filters_logs_results_and_inputs():
    def handler(request):
        assert request.url.path == "/api/workflows/bodybrain-ingestion/executions/exec-123"
        return httpx.Response(200, json={
            "id": "exec-123", "workflowId": "bodybrain-ingestion", "status": "completed",
            "participants": [{"agentId": "bodybrain-ingestion", "status": "completed", "result": "private report"}],
            "logs": ["private log"], "inputs": {"secret": "private token"},
        })

    result = await client(handler).execution("exec-123")
    assert result["status"] == "completed"
    assert result["participants"] == [{"agent_id": "bodybrain-ingestion", "status": "completed"}]
    assert "private" not in json.dumps(result)


async def test_zero_participant_execution_is_not_success():
    adapter = client(lambda _: httpx.Response(200, json={
        "id": "exec-123", "workflowId": "bodybrain-ingestion", "status": "completed", "participants": [],
    }))
    assert (await adapter.execution("exec-123"))["status"] == "error"


@pytest.mark.parametrize("status", [301, 401, 403, 404, 500])
async def test_http_failures_redact_upstream_body_and_never_follow_redirect(status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={"error": "test-dashboard-token private medical report"}, headers={"Location": "https://other.example.test"})

    result = await client(handler).trigger_task("task-123")
    assert result["status"] == "error"
    assert result["http_status"] == status
    assert "test-dashboard-token" not in json.dumps(result)
    assert "medical" not in json.dumps(result)
    assert len(requests) == 1


async def test_trigger_timeout_does_not_retry_uncertain_submission():
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("contains test-dashboard-token", request=request)

    result = await client(handler).trigger_task("task-123")
    assert result["status"] == "error"
    assert "history" in result["message"]
    assert "test-dashboard-token" not in result["message"]
    assert len(requests) == 1


@pytest.mark.parametrize("response", [
    httpx.Response(200, text="<html>login</html>"),
    httpx.Response(200, json=[]),
    httpx.Response(200, json={"ok": True}),
    httpx.Response(200, json={"executionId": "exec-123", "workflowId": "wrong"}),
])
async def test_trigger_rejects_invalid_api_response(response):
    assert (await client(lambda _: response).trigger_task("task-123"))["status"] == "error"


@pytest.mark.parametrize("value", ["../../other", "task id", "x\nignore instructions", "", "http://host"])
async def test_task_and_execution_identifiers_cannot_inject_paths_or_instructions(value):
    adapter = client(lambda _: pytest.fail("Invalid input must never reach network"))
    with pytest.raises(ValueError):
        await adapter.trigger_task(value)
    with pytest.raises(ValueError):
        await adapter.execution(value)


@pytest.mark.parametrize("url", ["file:///tmp/api", "https://user:pass@example.test", "https://example.test?token=secret", "https://example.test/#secret"])
def test_invalid_base_url_rejected(url):
    with pytest.raises(ValueError):
        ClawMaxClient(base_url=url)
