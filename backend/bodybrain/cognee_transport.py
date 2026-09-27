"""Small, synchronous Cognee file transport, also bundled with hosted workers.

This module deliberately uses only the Python standard library. It transports
immutable bytes through authenticated dataset routes; it never searches,
cognifies, follows storage locations, or implements a distributed queue lock.
"""

from __future__ import annotations

import ipaddress
import json
import math
import re
import secrets
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID


class CogneeTransportError(RuntimeError):
    """Provider-independent failure safe to expose without credentials or data."""

    def __init__(self, message: str, *, code: str = "transport_error", retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_COMPLETE = {"pipelineruncompleted", "pipelinerunalreadycompleted", "completed", "success", "succeeded", "already_completed"}
_PAGE_SIZE = 1000
_MAX_OFFSET = 1_000_000
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,194}\.txt\Z")


def _uuid(value: Any) -> str:
    try:
        if not isinstance(value, str):
            raise ValueError
        return str(UUID(value))
    except ValueError:
        raise CogneeTransportError("Cognee resource identifier is invalid.", code="invalid_id") from None


def _name(value: Any) -> str:
    if (not isinstance(value, str) or not value or len(value) > 255
            or value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or any(c in value for c in ("/", "\\"))):
        raise CogneeTransportError("Cognee resource name is invalid.", code="invalid_name")
    return value


def _origin(url: str) -> tuple[str, str | None, int]:
    parsed = urlsplit(url)
    return parsed.scheme.lower(), parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


class CogneeFiles:
    def __init__(self, base_url: str, api_key: str = "", bearer_token: str = "", timeout: float = 30, max_bytes: int = 2_097_152):
        try:
            if not isinstance(base_url, str) or base_url != base_url.strip() or any(ord(c) < 33 or ord(c) == 127 for c in base_url):
                raise ValueError
            parsed = urlsplit(base_url)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None
                    or parsed.password is not None or parsed.query or parsed.fragment or parsed.path.rstrip("/") not in {"", "/api/v1"}):
                raise ValueError
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                raise ValueError
            if parsed.scheme == "http":
                loopback = parsed.hostname == "localhost"
                try:
                    loopback = loopback or ipaddress.ip_address(parsed.hostname).is_loopback
                except ValueError:
                    pass
                if not loopback:
                    raise ValueError
        except (ValueError, TypeError):
            raise CogneeTransportError("Cognee needs an HTTPS URL, or HTTP on loopback, without credentials or extra URL components.", code="invalid_config") from None
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or not 0 < timeout <= 120
                or isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= 16_777_216):
            raise CogneeTransportError("Cognee timeout or response limit is invalid.", code="invalid_config")
        if (not isinstance(api_key, str) or not isinstance(bearer_token, str) or (api_key and bearer_token)
                or any(len(value) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in value) for value in (api_key, bearer_token))):
            raise CogneeTransportError("Use one valid Cognee authentication credential.", code="invalid_config")
        self.base_url = f"{parsed.scheme}://{parsed.netloc}"
        self.timeout = timeout
        self.max_bytes = max_bytes
        self._headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        if api_key:
            self._headers["X-Api-Key"] = api_key
        if bearer_token:
            self._headers["Authorization"] = f"Bearer {bearer_token}"
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def _read(self, response) -> bytes:
        length = response.headers.get("Content-Length")
        if length is not None:
            try:
                if int(length) < 0:
                    raise ValueError
                too_large = int(length) > self.max_bytes
            except (ValueError, TypeError):
                raise CogneeTransportError("Cognee returned an invalid response length.", code="invalid_response") from None
            if too_large:
                raise CogneeTransportError("Cognee response exceeds the configured size limit.", code="response_too_large")
        if response.headers.get("Content-Encoding", "identity").lower() not in {"", "identity"}:
            raise CogneeTransportError("Cognee returned an unsupported encoded response.", code="invalid_response")
        parts: list[bytes] = []
        size = 0
        while True:
            chunk = response.read(min(65_536, self.max_bytes + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > self.max_bytes:
                raise CogneeTransportError("Cognee response exceeds the configured size limit.", code="response_too_large")
            parts.append(chunk)
        return b"".join(parts)

    def _request(self, method: str, route: str, body: bytes | None = None, content_type: str | None = None, *, slash_redirect: bool = False) -> tuple[int, bytes]:
        url = self.base_url + route
        headers = dict(self._headers)
        if content_type:
            headers["Content-Type"] = content_type
        for attempt in range(2):
            try:
                request = Request(url, data=body, headers=headers, method=method)
                try:
                    response = self._opener.open(request, timeout=self.timeout)
                except HTTPError as exc:
                    response = exc
                with response:
                    status = response.code
                    if status in {301, 302, 303, 307, 308}:
                        target = urljoin(url, response.headers.get("Location", ""))
                        current, destination = urlsplit(url), urlsplit(target)
                        allowed = (slash_redirect and attempt == 0 and status in {307, 308}
                                   and _origin(target) == _origin(url) and destination.username is None
                                   and destination.password is None and not destination.query and not destination.fragment
                                   and current.path.rstrip("/") == "/api/v1/datasets"
                                   and destination.path in {"/api/v1/datasets", "/api/v1/datasets/"}
                                   and destination.path != current.path)
                        if not allowed:
                            raise CogneeTransportError("Cognee redirect was rejected.", code="redirect_rejected")
                        url = target
                        continue
                    if not 200 <= status < 300:
                        raise CogneeTransportError(f"Cognee returned HTTP {status}.", code="http_error", retryable=status == 429 or status >= 500)
                    return status, self._read(response)
            except CogneeTransportError:
                raise
            except (OSError, URLError, HTTPException, ValueError, UnicodeError):
                raise CogneeTransportError("Cognee request failed.", code="connection_error", retryable=True) from None
        raise CogneeTransportError("Cognee redirect was rejected.", code="redirect_rejected")

    def _json(self, method: str, route: str, body: bytes | None = None, content_type: str | None = None, *, slash_redirect: bool = False) -> Any:
        _, content = self._request(method, route, body, content_type, slash_redirect=slash_redirect)
        try:
            return json.loads(content)
        except (ValueError, UnicodeError, RecursionError):
            raise CogneeTransportError("Cognee returned invalid JSON.", code="invalid_response") from None

    def list_datasets(self) -> list[dict[str, str]]:
        value = self._json("GET", "/api/v1/datasets/", slash_redirect=True)
        if not isinstance(value, list):
            raise CogneeTransportError("Cognee dataset listing is invalid.", code="invalid_response")
        result: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, dict):
                raise CogneeTransportError("Cognee dataset listing is invalid.", code="invalid_response")
            identifier, name = _uuid(item.get("id")), _name(item.get("name"))
            if identifier in seen:
                raise CogneeTransportError("Cognee dataset listing is ambiguous.", code="ambiguous_response")
            seen.add(identifier)
            result.append({"id": identifier, "name": name})
        return result

    def dataset(self, name: str, create: bool = False) -> str | None:
        name = _name(name)
        matches = [item for item in self.list_datasets() if item["name"] == name]
        if len(matches) > 1:
            raise CogneeTransportError("Cognee dataset name is ambiguous.", code="ambiguous_response")
        if matches:
            return matches[0]["id"]
        if not create:
            return None
        result = self._json("POST", "/api/v1/datasets/", json.dumps({"name": name}).encode("utf-8"), "application/json", slash_redirect=True)
        if not isinstance(result, dict) or result.get("name") != name:
            raise CogneeTransportError("Cognee created an unexpected dataset.", code="invalid_response")
        identifier = _uuid(result.get("id"))
        # Reject concurrent same-name creation instead of silently choosing one.
        confirmed = self.dataset(name)
        if confirmed != identifier:
            raise CogneeTransportError("Cognee dataset creation could not be verified.", code="ambiguous_response", retryable=True)
        return identifier

    def list_files(self, dataset_id: str) -> list[dict[str, str]]:
        dataset_id = _uuid(dataset_id)
        result: list[dict[str, str]] = []
        seen: set[str] = set()
        for offset in range(0, _MAX_OFFSET + 1, _PAGE_SIZE):
            page = self._json("GET", f"/api/v1/datasets/{dataset_id}/data?limit={_PAGE_SIZE}&offset={offset}")
            if not isinstance(page, list) or len(page) > _PAGE_SIZE:
                raise CogneeTransportError("Cognee file listing is invalid.", code="invalid_response")
            for item in page:
                if not isinstance(item, dict):
                    raise CogneeTransportError("Cognee file listing is invalid.", code="invalid_response")
                identifier, name = _uuid(item.get("id")), _name(item.get("name"))
                extension = item.get("extension")
                if not isinstance(extension, str) or not re.fullmatch(r"\.?[A-Za-z0-9_-]{1,32}", extension):
                    raise CogneeTransportError("Cognee file extension is invalid.", code="invalid_response")
                for field in ("datasetId", "dataset_id"):
                    if field in item and _uuid(item[field]) != dataset_id:
                        raise CogneeTransportError("Cognee returned a file from another dataset.", code="invalid_response")
                if identifier in seen:
                    raise CogneeTransportError("Cognee file listing repeated a resource.", code="ambiguous_response", retryable=True)
                seen.add(identifier)
                result.append({"id": identifier, "name": name, "extension": extension.lstrip(".").lower()})
            if len(page) < _PAGE_SIZE:
                return result
        raise CogneeTransportError("Cognee file listing exceeded the pagination limit.", code="pagination_limit")

    def read_file(self, dataset_id: str, data_id: str) -> bytes:
        _, content = self._request("GET", f"/api/v1/datasets/{_uuid(dataset_id)}/data/{_uuid(data_id)}/raw")
        return content

    def _matching(self, dataset_id: str, filename: str) -> dict[str, str] | None:
        matches = [item for item in self.list_files(dataset_id)
                   if item["extension"] == "txt" and item["name"] in {filename, filename[:-4]}]
        if len(matches) > 1:
            raise CogneeTransportError("Cognee filename is ambiguous.", code="ambiguous_response")
        return matches[0] if matches else None

    def put_file(self, dataset_name: str, filename: str, content: bytes) -> dict[str, str]:
        dataset_name = _name(dataset_name)
        if not isinstance(filename, str) or not _FILENAME.fullmatch(filename):
            raise CogneeTransportError("Cognee transport requires a bounded .txt filename.", code="invalid_name")
        if not isinstance(content, bytes) or not content or len(content) > self.max_bytes:
            raise CogneeTransportError("Cognee upload bytes are empty, invalid or too large.", code="invalid_content")
        dataset_id = self.dataset(dataset_name, create=True)
        assert dataset_id is not None
        existing = self._matching(dataset_id, filename)
        if existing is not None:
            if self.read_file(dataset_id, existing["id"]) != content:
                raise CogneeTransportError("Cognee already contains different bytes for this filename.", code="content_conflict")
            return {"dataset_id": dataset_id, "data_id": existing["id"], "name": filename}
        boundary = "bodybrain_" + secrets.token_hex(24)
        while boundary.encode("ascii") in content:
            boundary = "bodybrain_" + secrets.token_hex(24)
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="datasetId"\r\n\r\n{dataset_id}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="run_in_background"\r\n\r\nfalse\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="data"; filename="{filename}"\r\n'
                'Content-Type: text/plain\r\n\r\n').encode("ascii") + content + f"\r\n--{boundary}--\r\n".encode("ascii")
        run = self._json("POST", "/api/v1/add", body, f"multipart/form-data; boundary={boundary}")
        if not isinstance(run, dict) or str(run.get("status", "")).lower() not in _COMPLETE:
            raise CogneeTransportError("Cognee upload did not return a completed add operation.", code="upload_incomplete", retryable=True)
        for field in ("dataset_id", "datasetId"):
            if run.get(field) is not None and _uuid(run[field]) != dataset_id:
                raise CogneeTransportError("Cognee completed an upload to an unexpected dataset.", code="invalid_response")
        uploaded = self._matching(dataset_id, filename)
        if uploaded is None:
            raise CogneeTransportError("Cognee uploaded file is not yet visible.", code="upload_unverified", retryable=True)
        if self.read_file(dataset_id, uploaded["id"]) != content:
            raise CogneeTransportError("Cognee uploaded file failed byte verification.", code="content_conflict")
        return {"dataset_id": dataset_id, "data_id": uploaded["id"], "name": filename}

    def delete_file(self, dataset_id: str, data_id: str) -> None:
        status, _ = self._request("DELETE", f"/api/v1/datasets/{_uuid(dataset_id)}/data/{_uuid(data_id)}")
        if status not in {200, 204}:
            raise CogneeTransportError("Cognee file deletion has not completed.", code="deletion_incomplete", retryable=True)
