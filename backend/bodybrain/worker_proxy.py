"""Optional tunnel target exposing only BodyBrain's authenticated worker API.

Run the factory on 127.0.0.1:8081 and point a tunnel at that port, never at the
ordinary backend. The backend remains on 127.0.0.1:8080. This module deliberately
does not import the main application, initialize storage, or read configuration
files; the launcher supplies BODYBRAIN_AGENT_TOKEN in its environment.
"""

import asyncio
import hmac
import json
import os
import re

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect
from starlette.types import ASGIApp, Receive, Scope, Send


UPSTREAM_ORIGIN = "http://127.0.0.1:8080"
MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 30
UPSTREAM_TIMEOUT_SECONDS = 15
TASK_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


class WorkerBoundary:
    """Authenticate before reading a body; cancel the actual request on timeout."""

    def __init__(self, app: ASGIApp, expected_authorization: bytes):
        self.app = app
        self.expected_authorization = expected_authorization

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        response_started = False

        async def protected_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                message = {**message, "headers": [
                    (key, value) for key, value in message.get("headers", [])
                    if key.lower() not in {b"cache-control", b"x-content-type-options"}
                ] + [(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")]}
            await send(message)

        authorizations = request.headers.getlist("authorization")
        if len(authorizations) != 1 or not hmac.compare_digest(authorizations[0].encode("utf-8"), self.expected_authorization):
            response = JSONResponse({"detail": "Agent token required"}, status_code=401)
        elif request.headers.get("origin"):
            response = JSONResponse({"detail": "Worker callbacks do not accept browser origins"}, status_code=403)
        else:
            try:
                async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                    await self.app(scope, receive, protected_send)
                return
            except TimeoutError:
                if response_started:
                    # A slow/disconnected downstream must not receive a second
                    # response after headers have already been sent.
                    raise
                response = JSONResponse({"detail": "Worker request timed out"}, status_code=504)
        await response(scope, receive, protected_send)


def create_proxy(*, agent_token: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    """Create the isolated proxy; ``transport`` is injectable for offline tests."""
    token = os.environ.get("BODYBRAIN_AGENT_TOKEN", "") if agent_token is None else agent_token
    if not token or token != token.strip() or not token.isascii() or any(ord(char) < 33 or ord(char) > 126 for char in token):
        raise ValueError("Set a nonempty BODYBRAIN_AGENT_TOKEN without whitespace before starting the worker proxy")
    expected_authorization = f"Bearer {token}".encode("ascii")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)
    app.add_middleware(WorkerBoundary, expected_authorization=expected_authorization)

    def task_path(task_id: str) -> str:
        if not TASK_ID.fullmatch(task_id):
            raise HTTPException(404, "Worker route not found")
        return "/api/agent/tasks/" + task_id

    def no_query(request: Request):
        if request.scope.get("query_string"):
            raise HTTPException(400, "This worker route does not accept query parameters")

    async def forward(method: str, path: str, *, params=None, body: bytes | None = None):
        # All callers construct literal paths, validated IDs, and query values.
        # Never copy the external host, forwarding headers, cookies, or URL.
        try:
            async with httpx.AsyncClient(
                transport=transport,
                timeout=UPSTREAM_TIMEOUT_SECONDS,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                async with client.stream(
                    method, UPSTREAM_ORIGIN + path,
                    params=params, content=body,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json"},
                ) as upstream:
                    if upstream.status_code != 200:
                        status = upstream.status_code if 400 <= upstream.status_code < 500 else 502
                        raise HTTPException(status, f"BodyBrain rejected the worker request (HTTP {upstream.status_code})")
                    content = bytearray()
                    async for chunk in upstream.aiter_bytes():
                        if len(content) + len(chunk) > MAX_RESPONSE_BYTES:
                            raise HTTPException(502, "BodyBrain worker response exceeded the size limit")
                        content.extend(chunk)
        except httpx.TimeoutException:
            raise HTTPException(504, "BodyBrain worker request timed out") from None
        except httpx.RequestError:
            raise HTTPException(502, "BodyBrain backend could not be reached") from None
        try:
            data = json.loads(content)
        except (ValueError, UnicodeError, RecursionError):
            raise HTTPException(502, "BodyBrain returned an invalid worker response") from None
        if not isinstance(data, dict):
            raise HTTPException(502, "BodyBrain returned an invalid worker response")
        try:
            return JSONResponse(data)
        except (ValueError, RecursionError):
            raise HTTPException(502, "BodyBrain returned an invalid worker response") from None

    @app.get("/api/agent/anatomy")
    async def anatomy(request: Request):
        items = list(request.query_params.multi_items())
        if any(key != "q" for key, _ in items) or len(items) > 1:
            raise HTTPException(400, "Only one anatomy query is accepted")
        query = request.query_params.get("q", "")
        if len(query) > 200:
            raise HTTPException(400, "Anatomy query exceeds 200 characters")
        return await forward("GET", "/api/agent/anatomy", params={"q": query})

    @app.get("/api/agent/tasks/{task_id}")
    async def task(task_id: str, request: Request):
        no_query(request)
        return await forward("GET", task_path(task_id))

    @app.post("/api/agent/tasks/{task_id}/result")
    async def result(task_id: str, request: Request):
        path = task_path(task_id) + "/result"
        no_query(request)
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise HTTPException(415, "Worker results must use application/json")
        if request.headers.get("content-encoding", "identity").lower() != "identity":
            raise HTTPException(415, "Encoded worker request bodies are not supported")
        lengths = request.headers.getlist("content-length")
        if lengths:
            if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,10}", lengths[0]):
                raise HTTPException(400, "Invalid request length")
            if int(lengths[0]) > MAX_REQUEST_BYTES:
                raise HTTPException(413, "Worker result exceeds the size limit")
        body = bytearray()
        try:
            async for chunk in request.stream():
                if len(body) + len(chunk) > MAX_REQUEST_BYTES:
                    raise HTTPException(413, "Worker result exceeds the size limit")
                body.extend(chunk)
        except ClientDisconnect:
            raise HTTPException(400, "Worker request was interrupted") from None
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError, RecursionError):
            raise HTTPException(400, "Worker result must be a JSON object") from None
        if not isinstance(payload, dict):
            raise HTTPException(400, "Worker result must be a JSON object")
        return await forward("POST", path, body=bytes(body))

    return app
