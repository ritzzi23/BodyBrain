"""Offline tests for the externally reachable worker-only boundary."""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from bodybrain import worker_proxy


TOKEN = "test-worker-secret"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def proxy(handler):
    return worker_proxy.create_proxy(agent_token=TOKEN, transport=httpx.MockTransport(handler))


def forbidden(_request):
    pytest.fail("Rejected requests must not reach the backend")


@pytest.mark.parametrize("token", ["", " ", "secret\n", "secret token", "private\u2603"])
def test_startup_fails_closed_for_missing_or_invalid_token(token):
    with pytest.raises(ValueError, match="BODYBRAIN_AGENT_TOKEN"):
        worker_proxy.create_proxy(agent_token=token)


def test_factory_reads_environment_without_loading_backend(monkeypatch):
    monkeypatch.delenv("BODYBRAIN_AGENT_TOKEN", raising=False)
    with pytest.raises(ValueError, match="BODYBRAIN_AGENT_TOKEN"):
        worker_proxy.create_proxy()
    monkeypatch.setenv("BODYBRAIN_AGENT_TOKEN", TOKEN)
    assert len(worker_proxy.create_proxy().routes) == 3


@pytest.mark.parametrize("headers", [
    {}, {"Authorization": "Bearer wrong"}, {"Authorization": "Bearer user-api-token"},
    [("Authorization", f"Bearer {TOKEN}"), ("Authorization", "Bearer other")],
])
def test_worker_token_required_before_upstream_call(headers):
    with TestClient(proxy(forbidden)) as client:
        response = client.get("/api/agent/tasks/task-123", headers=headers)
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", [
    "/", "/docs", "/redoc", "/openapi.json", "/api/health", "/api/records",
    "/api/records/record-123/source", "/api/records/record-123/approve",
    "/api/records/record-123/index", "/api/chat", "/api/tasks/task-123",
    "/api/agent/tasks", "/api/agent/tasks/task-123/", "/api/agent/anatomy/",
    "/api/agent/tasks/..%2F..%2Frecords", "/api/agent/tasks/%252e%252e",
    "/api/agent/tasks/task%00id", "/api/agent/tasks/task%3Fother",
    "/api/agent/tasks/" + "a" * 129,
])
def test_unrelated_and_malformed_routes_are_never_forwarded(path):
    with TestClient(proxy(forbidden)) as client:
        response = client.get(path, headers=AUTH, follow_redirects=False)
    assert response.status_code == 404
    assert "location" not in response.headers


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/agent/anatomy"), ("POST", "/api/agent/tasks/task-123"),
    ("GET", "/api/agent/tasks/task-123/result"),
    ("DELETE", "/api/agent/tasks/task-123"),
    ("OPTIONS", "/api/agent/tasks/task-123"), ("HEAD", "/api/agent/anatomy"),
    ("POST", "/api/records/record-123/approve"),
])
def test_only_worker_methods_are_available(method, path):
    with TestClient(proxy(forbidden)) as client:
        response = client.request(method, path, headers=AUTH)
    assert response.status_code in {404, 405}


def test_browser_origins_are_rejected():
    with TestClient(proxy(forbidden)) as client:
        response = client.get("/api/agent/anatomy", headers={**AUTH, "Origin": "https://example.test"})
    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers


def test_all_three_routes_forward_only_to_loopback_with_safe_headers():
    requests = []
    payload = {"findings": [{"quote": "No fracture of the femur.", "page": 1}]}

    def handler(request):
        requests.append(request)
        assert request.url.scheme == "http"
        assert request.url.host == "127.0.0.1"
        assert request.url.port == 8080
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        assert request.headers["host"] == "127.0.0.1:8080"
        assert not any(name in request.headers for name in ["cookie", "forwarded", "x-forwarded-host", "x-forwarded-for"])
        assert request.extensions["timeout"]["read"] == worker_proxy.UPSTREAM_TIMEOUT_SECONDS
        if request.method == "POST":
            assert json.loads(request.content) == payload
            return httpx.Response(200, json={"status": "accepted", "task_id": "task-123"})
        if request.url.path == "/api/agent/anatomy":
            assert dict(request.url.params) == {"q": "heart & /?"}
            return httpx.Response(200, json={"concepts": [{"id": "catalog-id"}]})
        return httpx.Response(200, json={"id": "task-123", "kind": "ingestion"}, headers={"Set-Cookie": "private=secret", "X-Upstream": "private"})

    with TestClient(proxy(handler), base_url="https://callback.example.test") as client:
        headers = {**AUTH, "Cookie": "private=unrelated", "Forwarded": "host=evil.test", "X-Forwarded-Host": "evil.test", "X-Forwarded-For": "8.8.8.8"}
        task = client.get("/api/agent/tasks/task-123", headers=headers)
        assert task.json()["id"] == "task-123"
        assert "set-cookie" not in task.headers and "x-upstream" not in task.headers
        assert client.get("/api/agent/anatomy", params={"q": "heart & /?"}, headers=headers).json()["concepts"]
        result = client.post("/api/agent/tasks/task-123/result", json=payload, headers=headers)
        assert result.json()["status"] == "accepted"
        assert result.headers["cache-control"] == "no-store"
        assert result.headers["x-content-type-options"] == "nosniff"
    assert [(r.method, r.url.path) for r in requests] == [
        ("GET", "/api/agent/tasks/task-123"), ("GET", "/api/agent/anatomy"), ("POST", "/api/agent/tasks/task-123/result"),
    ]


@pytest.mark.parametrize("path", [
    "/api/agent/anatomy?q=heart&q=brain", "/api/agent/anatomy?url=http://evil.test",
    "/api/agent/anatomy?q=" + "x" * 201, "/api/agent/tasks/task-123?url=http://evil.test",
])
def test_query_parameters_cannot_expand_proxy_scope(path):
    with TestClient(proxy(forbidden)) as client:
        assert client.get(path, headers=AUTH).status_code == 400


@pytest.mark.parametrize("content,headers,status", [
    (b"{}", {"Content-Type": "text/plain"}, 415),
    (b"{}", {"Content-Type": "application/json", "Content-Encoding": "gzip"}, 415),
    (b"{}", {"Content-Type": "application/json", "Content-Length": "not-a-number"}, 400),
    (b"{}", {"Content-Type": "application/json", "Content-Length": str(worker_proxy.MAX_REQUEST_BYTES + 1)}, 413),
    (b"not-json", {"Content-Type": "application/json"}, 400),
    (b"[]", {"Content-Type": "application/json"}, 400),
])
def test_results_require_bounded_json_objects(content, headers, status):
    with TestClient(proxy(forbidden)) as client:
        response = client.post("/api/agent/tasks/task-123/result", content=content, headers={**AUTH, **headers})
    assert response.status_code == status


async def test_streamed_body_is_limited_without_content_length(monkeypatch):
    monkeypatch.setattr(worker_proxy, "MAX_REQUEST_BYTES", 16)

    async def chunks():
        yield b'{"findings":'
        yield b'"' + b"x" * 20 + b'"}'

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=proxy(forbidden)), base_url="http://testserver") as client:
        response = await client.post("/api/agent/tasks/task-123/result", content=chunks(), headers={**AUTH, "Content-Type": "application/json"})
    assert response.status_code == 413


@pytest.mark.parametrize("status", [301, 307, 401, 404, 409, 422, 500])
def test_upstream_errors_are_sanitized_and_redirects_not_followed(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="private upstream report " + TOKEN, headers={"Location": "https://evil.test"})

    with TestClient(proxy(handler)) as client:
        response = client.get("/api/agent/tasks/task-123", headers=AUTH)
    assert response.status_code == (status if 400 <= status < 500 else 502)
    assert TOKEN not in response.text and "private" not in response.text
    assert "location" not in response.headers
    assert len(calls) == 1


@pytest.mark.parametrize("exception,status", [(httpx.ConnectError, 502), (httpx.ReadTimeout, 504)])
def test_transport_failures_are_sanitized_without_post_retry(exception, status):
    calls = []

    def handler(request):
        calls.append(request)
        raise exception("private failure " + TOKEN, request=request)

    with TestClient(proxy(handler)) as client:
        response = client.post("/api/agent/tasks/task-123/result", json={"findings": []}, headers=AUTH)
    assert response.status_code == status
    assert TOKEN not in response.text and "private" not in response.text
    assert len(calls) == 1


@pytest.mark.parametrize("body", [b"private invalid JSON", b"[]", b"null", b'{"value": NaN}', b'{"value": 1e999}'])
def test_invalid_upstream_responses_are_sanitized(body):
    with TestClient(proxy(lambda _: httpx.Response(200, content=body))) as client:
        response = client.get("/api/agent/anatomy", headers=AUTH)
    assert response.status_code == 502
    assert "private" not in response.text


def test_upstream_response_size_is_bounded(monkeypatch):
    monkeypatch.setattr(worker_proxy, "MAX_RESPONSE_BYTES", 16)
    with TestClient(proxy(lambda _: httpx.Response(200, json={"private": "x" * 30}))) as client:
        response = client.get("/api/agent/tasks/task-123", headers=AUTH)
    assert response.status_code == 502
    assert "private" not in response.text


async def test_total_request_time_is_bounded(monkeypatch):
    monkeypatch.setattr(worker_proxy, "REQUEST_TIMEOUT_SECONDS", 0.01)
    state = {"cancelled": False, "completed": False}

    async def handler(_request):
        try:
            await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise
        state["completed"] = True
        return httpx.Response(200, json={"id": "task-123"})

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=proxy(handler)), base_url="http://testserver") as client:
        response = await client.get("/api/agent/tasks/task-123", headers=AUTH)
    assert response.status_code == 504
    assert response.headers["cache-control"] == "no-store"
    assert state == {"cancelled": True, "completed": False}
