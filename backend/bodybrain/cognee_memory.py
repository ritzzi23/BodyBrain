"""Persistent Cognee adapter; importing BodyBrain never starts Cognee or an LLM.

The REST contract is Cognee's add -> cognify -> search API. Only reviewed data
belongs here. Retrieved source IDs are candidates: the caller must verify them
against its own approved documents before presenting evidence to a user.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import re
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx


class CogneeError(RuntimeError):
    """Safe-to-display integration failure; never includes provider bodies/keys."""

    def __init__(self, message: str, *, code: str = "integration_error", retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


_SOURCE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MARKER = re.compile(r"\[\[bodybrain-document:([A-Za-z0-9_-]{1,128})\]\]")
_FILENAME = re.compile(r"bodybrain_([A-Za-z0-9_-]{1,128})\.txt")
_COMPLETED = {"pipelineruncompleted", "pipelinerunalreadycompleted", "completed", "success", "succeeded", "already_completed"}
_FAILED = {"pipelinerunerrored", "error", "errored", "failed", "failure", "cancelled"}
_DATA_PAGE_SIZE = 1000
_DATA_MAX_OFFSET = 1_000_000


def _provider_items(value: Any, resource: str) -> list[dict[str, Any]]:
    """Validate a complete listing before deriving a destructive request from it."""
    if not isinstance(value, list):
        raise CogneeError(f"Cognee returned an invalid {resource} listing.", code="invalid_response")
    seen: set[str] = set()
    items = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
            raise CogneeError(f"Cognee returned an invalid {resource} item.", code="invalid_response")
        item_id = _provider_uuid(item.get("id"))
        if item_id in seen:
            raise CogneeError(f"Cognee returned an ambiguous {resource} listing.", code="ambiguous_response")
        seen.add(item_id)
        items.append({**item, "id": item_id})
    return items


def _provider_uuid(value: Any) -> str:
    # Provider IDs become URL path segments. Never interpolate unvalidated strings.
    try:
        if not isinstance(value, str):
            raise ValueError
        return str(UUID(value))
    except ValueError as exc:
        raise CogneeError("Cognee returned an invalid resource ID.", code="invalid_response") from exc


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Enum):
        return _jsonable(value.value)
    if isinstance(value, (UUID, Path)):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    if hasattr(value, "to_json"):
        return _jsonable(value.to_json())
    raise CogneeError("Cognee returned an unsupported result type.", code="invalid_response")


def _pipeline_summary(value: Any, operation: str) -> list[dict[str, Any]]:
    """Do not equate HTTP 200, an empty object, or a queued job with indexing."""
    result = _jsonable(value)
    runs: list[dict[str, Any]] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            if "status" in item:
                state = str(item["status"]).lower()
                if state in _FAILED or "error" in state or "fail" in state:
                    raise CogneeError(f"Cognee {operation} pipeline failed.", code="pipeline_failed", retryable=True)
                if state not in _COMPLETED:
                    raise CogneeError(f"Cognee {operation} has not completed.", code="pipeline_incomplete", retryable=True)
                runs.append({key: item[key] for key in ("status", "pipeline_run_id", "dataset_id", "dataset_name") if key in item})
                return
            if item.get("error"):
                raise CogneeError(f"Cognee {operation} pipeline failed.", code="pipeline_failed", retryable=True)
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(result)
    if not runs:
        raise CogneeError(f"Cognee {operation} returned no completion record.", code="invalid_response", retryable=True)
    return runs


def _source_document(document_id: str, text: str, metadata: dict[str, Any]) -> str:
    # Repeating a bounded marker makes provenance survive Cognee's chunking.
    # The stable ID and filename also make retries of identical data idempotent.
    marker = f"[[bodybrain-document:{document_id}]]"
    header = json.dumps({**metadata, "bodybrain_document_id": document_id}, ensure_ascii=False, sort_keys=True)
    sections = [f"{marker}\nReviewed BodyBrain document metadata: {header}"]
    for offset in range(0, len(text), 1000):
        sections.append(f"{marker}\n{text[offset:offset + 1000]}")
    return "\n\n".join(sections)


def _source_ids(value: Any) -> list[str]:
    found: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, str):
            found.update(_MARKER.findall(item))
            found.update(_FILENAME.findall(item))
        elif isinstance(item, dict):
            source = item.get("bodybrain_document_id")
            if isinstance(source, str) and _SOURCE_ID.fullmatch(source):
                found.add(source)
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return sorted(found)


def _normalize_results(value: Any, limit: int) -> list[dict[str, Any]]:
    value = _jsonable(value)
    if not isinstance(value, list):
        raise CogneeError("Cognee search returned an unexpected response.", code="invalid_response")
    results: list[dict[str, Any]] = []

    def visit(item: Any, dataset_name: str | None = None) -> None:
        if isinstance(item, list):
            for child in item:
                visit(child, dataset_name)
        elif isinstance(item, dict) and "search_result" in item:
            visit(item["search_result"], item.get("dataset_name", dataset_name))
        elif isinstance(item, (dict, str)):
            text = item if isinstance(item, str) else item.get("text", "")
            if not isinstance(text, str):
                text = ""
            result = {"text": text, "document_ids": _source_ids(item), "raw": item}
            if dataset_name is not None:
                result["dataset_name"] = dataset_name
            if isinstance(item, dict) and isinstance(item.get("score"), (int, float)):
                result["score"] = item["score"]  # Cognee CHUNKS: distance, lower is better.
            results.append(result)
        else:
            raise CogneeError("Cognee returned an unexpected search item.", code="invalid_response")

    visit(value)
    return results[:limit]


class CogneeMemory:
    def __init__(
        self,
        mode: str = "disabled",
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        bearer_token: str | None = None,
        dataset: str = "bodybrain",
        storage_path: str | Path | None = None,
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if mode not in {"disabled", "rest", "sdk"}:
            raise ValueError("Cognee mode must be disabled, rest, or sdk")
        if not dataset.strip():
            raise ValueError("Cognee dataset must not be empty")
        if api_key and bearer_token:
            raise ValueError("Use a Cognee Cloud API key or self-hosted bearer token, not both")
        self.mode = mode
        self.base_url = (base_url or "").rstrip("/")
        # Accept a full versioned API URL without accidentally duplicating the prefix.
        if self.base_url.endswith("/api/v1"):
            self.base_url = self.base_url[:-7]
        if self.base_url:
            parsed = urlsplit(self.base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("Cognee base URL must be an HTTP(S) URL without credentials/query/fragment")
        self.dataset = dataset.strip()
        self.storage_path = Path(storage_path).expanduser().resolve() if storage_path is not None else None
        self.timeout = timeout
        self._transport = transport
        self._headers = {"Accept": "application/json"}
        if api_key:
            self._headers["X-Api-Key"] = api_key
        if bearer_token:
            self._headers["Authorization"] = f"Bearer {bearer_token}"
        self._sdk: Any = None
        self._lock = asyncio.Lock()
        self._reachable: bool | None = None
        self._last_error: str | None = None

    @property
    def configured(self) -> bool:
        return (self.mode == "rest" and bool(self.base_url)) or (self.mode == "sdk" and self.storage_path is not None)

    @property
    def target_identity(self) -> dict[str, str | None]:
        """Credential-free destination used to guard cleanup after configuration changes."""
        identity: dict[str, str | None] = {"mode": self.mode, "dataset": self.dataset}
        if self.mode == "rest":
            identity["base_url"] = self.base_url
        elif self.mode == "sdk":
            identity["storage_path"] = str(self.storage_path) if self.storage_path is not None else None
        return identity

    def _require_configured(self) -> None:
        if not self.configured:
            raise CogneeError("Cognee is not configured. Set REST connection details or an SDK storage path.", code="not_configured")

    async def _request(self, method: str, route: str, *, empty_success: bool = False, **kwargs: Any) -> Any:
        try:
            async with httpx.AsyncClient(
                headers=self._headers, timeout=self.timeout, transport=self._transport,
                follow_redirects=False, trust_env=False,
            ) as client:
                response = await client.request(method, f"{self.base_url}{route}", **kwargs)
            self._reachable = True
            if not 200 <= response.status_code < 300:
                raise CogneeError(
                    f"Cognee returned HTTP {response.status_code} for {route}.",
                    code="http_error", retryable=response.status_code == 429 or response.status_code >= 500,
                )
            if empty_success and response.status_code not in {200, 204}:
                raise CogneeError("Cognee deletion has not completed.", code="deletion_incomplete", retryable=True)
            if empty_success and not response.content:
                self._last_error = None
                return None
            try:
                result = response.json()
            except ValueError as exc:
                raise CogneeError("Cognee returned invalid JSON.", code="invalid_response") from exc
            self._last_error = None
            return result
        except httpx.RequestError as exc:
            self._reachable = False
            self._last_error = "Cognee connection failed or timed out."
            raise CogneeError(self._last_error, code="connection_failed", retryable=True) from exc
        except CogneeError as exc:
            self._last_error = str(exc)
            raise

    def _get_sdk(self) -> Any:
        if self._sdk is None:
            try:
                sdk = importlib.import_module("cognee")
            except ImportError as exc:
                raise CogneeError("The optional Cognee SDK is not installed. Install cognee==1.6.1 or configure REST mode.", code="sdk_unavailable") from exc
            # SDK configuration is process-global: run one BodyBrain SDK instance
            # per process and one worker for embedded databases.
            assert self.storage_path is not None
            self.storage_path.mkdir(parents=True, exist_ok=True)
            sdk.config.system_root_directory(str(self.storage_path / "system"))
            sdk.config.data_root_directory(str(self.storage_path / "data"))
            self._sdk = sdk
        return self._sdk

    async def remember(self, document_id: str, text: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        self._require_configured()
        if not isinstance(document_id, str) or not _SOURCE_ID.fullmatch(document_id):
            raise ValueError("document_id must use 1–128 letters, digits, underscores or hyphens")
        if not text.strip():
            raise ValueError("Document text must not be empty")
        source = _source_document(document_id, text, _jsonable(metadata or {}))
        # Serialize foreground operations to avoid overlapping writes in a dataset.
        async with self._lock:
            try:
                if self.mode == "rest":
                    added = await self._request(
                        "POST", "/api/v1/add",
                        files={"data": (f"bodybrain_{document_id}.txt", source.encode("utf-8"), "text/plain")},
                        data={"datasetName": self.dataset, "run_in_background": "false", "node_set": f"bodybrain-document:{document_id}"},
                    )
                    add_runs = _pipeline_summary(added, "add")
                    processed = await self._request("POST", "/api/v1/cognify", json={"datasets": [self.dataset], "run_in_background": False})
                else:
                    sdk = self._get_sdk()
                    added = await sdk.add(source, dataset_name=self.dataset, node_set=[f"bodybrain-document:{document_id}"], run_in_background=False)
                    add_runs = _pipeline_summary(added, "add")
                    processed = await sdk.cognify(datasets=[self.dataset], run_in_background=False)
                cognify_runs = _pipeline_summary(processed, "cognify")
                self._reachable = True
                self._last_error = None
                return {"provider": "cognee", "document_id": document_id, "dataset": self.dataset, "status": "indexed", "add_runs": add_runs, "cognify_runs": cognify_runs}
            except CogneeError as exc:
                self._last_error = str(exc)
                raise
            except Exception as exc:
                self._last_error = "Cognee indexing failed; check the provider's private logs."
                raise CogneeError(self._last_error, code="sdk_error", retryable=True) from exc

    async def _document_data_id(self, dataset_id: str, document_id: str) -> str | None:
        """Resolve only the exact filename, across all pages, before any deletion.

        Cognee FileMetadata separates the filename stem and extension. Matching
        source markers, substrings, or raw storage paths could delete other files.
        """
        matches: list[str] = []
        seen: set[str] = set()
        for offset in range(0, _DATA_MAX_OFFSET + 1, _DATA_PAGE_SIZE):
            page = _provider_items(await self._request(
                "GET", f"/api/v1/datasets/{dataset_id}/data",
                params={"limit": _DATA_PAGE_SIZE, "offset": offset},
            ), "data")
            if len(page) > _DATA_PAGE_SIZE:
                raise CogneeError("Cognee returned an invalid data page.", code="invalid_response")
            for item in page:
                if item["id"] in seen:
                    raise CogneeError("Cognee returned overlapping data pages.", code="ambiguous_response", retryable=True)
                seen.add(item["id"])
                if not isinstance(item.get("extension"), str):
                    raise CogneeError("Cognee returned an invalid data filename.", code="invalid_response")
                # Wire DTOs use camelCase; older APIs may emit snake_case.
                for key in ("datasetId", "dataset_id"):
                    if key in item and _provider_uuid(item[key]) != dataset_id:
                        raise CogneeError("Cognee returned data outside the configured dataset.", code="invalid_response")
                if item["name"] == f"bodybrain_{document_id}" and item["extension"] == "txt":
                    matches.append(item["id"])
            if len(page) < _DATA_PAGE_SIZE:
                break
        else:
            raise CogneeError("Cognee data listing is too large to safely verify deletion.", code="invalid_response")
        if len(matches) > 1:
            raise CogneeError("Cognee returned multiple files for this document; deletion was not attempted.", code="ambiguous_response")
        return matches[0] if matches else None

    async def forget(self, document_id: str) -> dict[str, str]:
        """Delete one reviewed document, retaining the dataset and every other file."""
        self._require_configured()
        if not isinstance(document_id, str) or not _SOURCE_ID.fullmatch(document_id):
            raise ValueError("document_id must use 1–128 letters, digits, underscores or hyphens")
        async with self._lock:
            try:
                if self.mode != "rest":
                    # SDK remember() historically added bare text with a generated
                    # filename. Its document identity cannot safely be inferred.
                    raise CogneeError(
                        "Document-scoped cleanup of SDK memory is not supported; the stored data has not been deleted.",
                        code="deletion_unsupported",
                    )
                datasets = _provider_items(await self._request("GET", "/api/v1/datasets/"), "dataset")
                matches = [item for item in datasets if item["name"] == self.dataset]
                if len(matches) > 1:
                    raise CogneeError("Cognee returned multiple datasets with the configured name; deletion was not attempted.", code="ambiguous_response")
                data_id = await self._document_data_id(matches[0]["id"], document_id) if matches else None
                if data_id is not None:
                    result = await self._request(
                        "DELETE", f"/api/v1/datasets/{matches[0]['id']}/data/{data_id}",
                        empty_success=True,
                    )
                    # REST currently returns null; the underlying Cognee method
                    # returns this explicit completion record on other versions.
                    if result is not None and result != {"status": "success"}:
                        raise CogneeError("Cognee returned no deletion completion record.", code="invalid_response", retryable=True)
                self._reachable = True
                self._last_error = None
                return {"provider": "cognee", "document_id": document_id, "status": "deleted" if data_id is not None else "not_found"}
            except CogneeError as exc:
                self._last_error = str(exc)
                raise
            except Exception as exc:
                self._last_error = "Cognee deletion failed; check the provider's private logs."
                raise CogneeError(self._last_error, code="integration_error", retryable=True) from exc

    async def recall(self, query: str, limit: int = 5) -> dict[str, Any]:
        self._require_configured()
        if not query.strip():
            raise ValueError("Search query must not be empty")
        if not 1 <= limit <= 50:
            raise ValueError("Search limit must be between 1 and 50")
        async with self._lock:
            try:
                if self.mode == "rest":
                    raw = await self._request("POST", "/api/v1/search", json={"query": query, "search_type": "CHUNKS", "datasets": [self.dataset], "top_k": limit})
                else:
                    sdk = self._get_sdk()
                    raw = await sdk.search(query_text=query, query_type=sdk.SearchType.CHUNKS, datasets=[self.dataset], top_k=limit)
                results = _normalize_results(raw, limit)
                self._reachable = True
                self._last_error = None
                return {"provider": "cognee", "dataset": self.dataset, "search_type": "CHUNKS", "results": results, "document_ids": sorted({source for item in results for source in item["document_ids"]})}
            except CogneeError as exc:
                self._last_error = str(exc)
                raise
            except Exception as exc:
                self._last_error = "Cognee retrieval failed; check the provider's private logs."
                raise CogneeError(self._last_error, code="sdk_error", retryable=True) from exc

    async def status(self, probe: bool = False) -> dict[str, Any]:
        """Configuration is not connectivity; a health probe is not an auth test."""
        result: dict[str, Any] = {"provider": "cognee", "mode": self.mode, "dataset": self.dataset, "configured": self.configured, "reachable": self._reachable, "last_error": self._last_error}
        if self.mode == "sdk":
            try:
                installed = self._sdk is not None or importlib.util.find_spec("cognee") is not None
            except (ValueError, ImportError):
                installed = False
            result["sdk_installed"] = installed
            result["note"] = "SDK/LLM/database readiness is verified by a successful memory operation."
        elif probe and self.configured:
            try:
                health = await self._request("GET", "/health", timeout=min(self.timeout, 5.0))
                result["health"] = health
            except CogneeError:
                pass
            result.update(reachable=self._reachable, last_error=self._last_error)
            result["note"] = "Health only; dataset access and indexing are verified by memory operations."
        return result
