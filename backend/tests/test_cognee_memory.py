"""Cognee contracts are mocked: these tests never send documents externally."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

import httpx

from bodybrain.cognee_memory import CogneeError, CogneeMemory


def completed(**extra):
    return {"status": "PipelineRunCompleted", "pipeline_run_id": "run-1", "dataset_id": "dataset-1", "dataset_name": "bodybrain", **extra}


DATASET_ID = "11111111-1111-4111-8111-111111111111"
OTHER_DATASET_ID = "22222222-2222-4222-8222-222222222222"
DATA_ID = "33333333-3333-4333-8333-333333333333"
OTHER_DATA_ID = "44444444-4444-4444-8444-444444444444"


def data_item(**extra):
    # Cognee's FileMetadata separates the original filename stem and extension.
    return {"id": DATA_ID, "name": "bodybrain_doc-1", "extension": "txt", "datasetId": DATASET_ID, **extra}


class CogneeMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_does_not_call_provider_or_import_sdk(self):
        memory = CogneeMemory()
        with patch("bodybrain.cognee_memory.importlib.import_module") as load:
            self.assertEqual((await memory.status())["reachable"], None)
            self.assertFalse((await memory.status())["configured"])
            with self.assertRaises(CogneeError) as raised:
                await memory.remember("report-1", "Left knee report")
            self.assertEqual(raised.exception.code, "not_configured")
            load.assert_not_called()

    async def test_rest_uploads_multipart_then_foreground_cognify(self):
        requests = []

        def handle(request):
            requests.append(request)
            self.assertEqual(request.headers["X-Api-Key"], "test-secret")
            self.assertNotIn("Authorization", request.headers)
            if request.url.path == "/api/v1/add":
                body = request.content.decode()
                self.assertIn('name="data"; filename="bodybrain_doc-123.txt"', body)
                self.assertIn('name="datasetName"', body)
                self.assertIn("bodybrain-document:doc-123", body)
                self.assertIn('"bodybrain_document_id": "doc-123"', body)
                self.assertIn("Left knee finding", body)
                return httpx.Response(200, json=completed())
            self.assertEqual(request.url.path, "/api/v1/cognify")
            self.assertEqual(json.loads(request.content), {"datasets": ["bodybrain"], "run_in_background": False})
            return httpx.Response(200, json={"dataset-1": completed()})

        memory = CogneeMemory("rest", base_url="https://example.test/api/v1/", api_key="test-secret", transport=httpx.MockTransport(handle))
        result = await memory.remember("doc-123", "Left knee finding", {"date": "2026-09-20"})
        self.assertEqual(result["status"], "indexed")
        self.assertEqual(result["document_id"], "doc-123")
        self.assertEqual(len(requests), 2)
        self.assertTrue((await memory.status())["reachable"])

    async def test_pipeline_failed_or_queued_never_reports_indexed(self):
        for state, expected in [("PipelineRunErrored", "pipeline_failed"), ("PipelineRunStarted", "pipeline_incomplete")]:
            with self.subTest(state=state):
                requests = []

                def handle(request):
                    requests.append(request)
                    return httpx.Response(200, json={"status": state, "payload": "private provider details"})

                memory = CogneeMemory("rest", base_url="https://example.test", transport=httpx.MockTransport(handle))
                with self.assertRaises(CogneeError) as raised:
                    await memory.remember("doc-1", "Evidence")
                self.assertEqual(raised.exception.code, expected)
                self.assertNotIn("private provider details", str(raised.exception))
                self.assertEqual(len(requests), 1)

    async def test_cognify_failure_propagates_even_after_successful_add(self):
        def handle(request):
            if request.url.path.endswith("/add"):
                return httpx.Response(200, json=completed())
            return httpx.Response(200, json={"dataset-1": {"status": "PipelineRunErrored"}})

        memory = CogneeMemory("rest", base_url="https://example.test", transport=httpx.MockTransport(handle))
        with self.assertRaises(CogneeError) as raised:
            await memory.remember("doc-1", "Evidence")
        self.assertEqual(raised.exception.code, "pipeline_failed")

    async def test_search_scoped_to_dataset_and_provenance_normalized(self):
        def handle(request):
            self.assertEqual(request.headers["Authorization"], "Bearer local-token")
            self.assertEqual(request.url.path, "/api/v1/search")
            self.assertEqual(json.loads(request.content), {"query": "Which knee?", "search_type": "CHUNKS", "datasets": ["patient-one"], "top_k": 2})
            return httpx.Response(200, json=[{"dataset_name": "patient-one", "dataset_id": "d", "search_result": [
                {"text": "[[bodybrain-document:doc-123]]\nLeft knee", "score": 0.14},
                {"text": "A generic chunk with no source marker", "id": "cognee-chunk-id"},
                {"text": "This third chunk exceeds requested limit"},
            ]}])

        memory = CogneeMemory("rest", base_url="https://example.test", bearer_token="local-token", dataset="patient-one", transport=httpx.MockTransport(handle))
        result = await memory.recall("Which knee?", limit=2)
        self.assertEqual(result["document_ids"], ["doc-123"])
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(result["results"][1]["document_ids"], [])
        self.assertEqual(result["results"][0]["score"], 0.14)

    async def test_http_errors_do_not_expose_secret_or_fall_back(self):
        def handle(request):
            return httpx.Response(401, json={"error": "secret-token and patient contents"})

        memory = CogneeMemory("rest", base_url="https://example.test", api_key="secret-token", transport=httpx.MockTransport(handle))
        with self.assertRaises(CogneeError) as raised:
            await memory.recall("knee")
        self.assertEqual(raised.exception.code, "http_error")
        self.assertNotIn("secret-token", str(raised.exception))
        # A 401 proves the server is reachable, but never proves authenticated.
        status = await memory.status()
        self.assertTrue(status["reachable"])
        self.assertIn("401", status["last_error"])

    async def test_probe_distinguishes_configured_from_unreachable(self):
        def handle(request):
            raise httpx.ConnectError("private proxy information", request=request)

        memory = CogneeMemory("rest", base_url="https://example.test", transport=httpx.MockTransport(handle))
        initial = await memory.status()
        self.assertTrue(initial["configured"])
        self.assertIsNone(initial["reachable"])
        checked = await memory.status(probe=True)
        self.assertFalse(checked["reachable"])
        self.assertNotIn("private proxy", checked["last_error"])

    async def test_unrecognized_completion_payload_rejected(self):
        memory = CogneeMemory("rest", base_url="https://example.test", transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))
        with self.assertRaises(CogneeError) as raised:
            await memory.remember("doc-1", "Evidence")
        self.assertEqual(raised.exception.code, "invalid_response")

    async def test_sdk_lazy_import_persistent_paths_and_exact_kwargs(self):
        sdk = SimpleNamespace(
            config=SimpleNamespace(system_root_directory=Mock(), data_root_directory=Mock()),
            add=AsyncMock(return_value=completed()),
            cognify=AsyncMock(return_value={"dataset-1": completed()}),
            search=AsyncMock(return_value=[{"text": "[[bodybrain-document:doc-1]]\nEvidence"}]),
            SearchType=SimpleNamespace(CHUNKS="CHUNKS"),
        )
        with tempfile.TemporaryDirectory() as directory, patch("bodybrain.cognee_memory.importlib.import_module", return_value=sdk) as load:
            memory = CogneeMemory("sdk", storage_path=directory)
            load.assert_not_called()
            result = await memory.remember("doc-1", "Evidence")
            self.assertEqual(result["status"], "indexed")
            sdk.config.system_root_directory.assert_called_once_with(str(Path(directory).resolve() / "system"))
            sdk.config.data_root_directory.assert_called_once_with(str(Path(directory).resolve() / "data"))
            self.assertEqual(sdk.add.call_args.kwargs, {"dataset_name": "bodybrain", "node_set": ["bodybrain-document:doc-1"], "run_in_background": False})
            sdk.cognify.assert_awaited_once_with(datasets=["bodybrain"], run_in_background=False)
            self.assertEqual((await memory.recall("Evidence"))["document_ids"], ["doc-1"])
            sdk.search.assert_awaited_once_with(query_text="Evidence", query_type="CHUNKS", datasets=["bodybrain"], top_k=5)
            load.assert_called_once_with("cognee")

    async def test_missing_sdk_is_actionable_and_does_not_boot_crash(self):
        with tempfile.TemporaryDirectory() as directory, patch("bodybrain.cognee_memory.importlib.import_module", side_effect=ImportError):
            memory = CogneeMemory("sdk", storage_path=directory)
            with self.assertRaises(CogneeError) as raised:
                await memory.recall("Evidence")
            self.assertEqual(raised.exception.code, "sdk_unavailable")

    async def test_invalid_response_and_input_rejected(self):
        memory = CogneeMemory("rest", base_url="https://example.test", transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"unexpected": "payload"})))
        with self.assertRaises(CogneeError):
            await memory.recall("question")
        with self.assertRaises(ValueError):
            await memory.remember("../path", "Evidence")
        with self.assertRaises(ValueError):
            await memory.recall("question", limit=0)
        with self.assertRaises(ValueError):
            CogneeMemory("rest", base_url="https://key:secret@example.test")


class CogneeDeletionTests(unittest.IsolatedAsyncioTestCase):
    async def test_forget_deletes_only_exact_file_in_configured_dataset(self):
        requests = []

        def handle(request):
            requests.append((request.method, request.url.path))
            self.assertEqual(request.headers["X-Api-Key"], "test-secret")
            if request.url.path == "/api/v1/datasets/":
                return httpx.Response(200, json=[
                    {"id": OTHER_DATASET_ID, "name": "another-patient"},
                    {"id": DATASET_ID, "name": "patient-one"},
                ])
            if request.method == "GET":
                self.assertEqual(dict(request.url.params), {"limit": "1000", "offset": "0"})
                return httpx.Response(200, json=[data_item(), data_item(id=OTHER_DATA_ID, name="bodybrain_doc-10")])
            self.assertEqual(request.content, b"")
            return httpx.Response(200, content=b"null")

        memory = CogneeMemory("rest", base_url="https://tenant.example.test/api/v1/", dataset="patient-one", api_key="test-secret", transport=httpx.MockTransport(handle))
        self.assertEqual(await memory.forget("doc-1"), {"provider": "cognee", "document_id": "doc-1", "status": "deleted"})
        self.assertEqual(requests, [
            ("GET", "/api/v1/datasets/"),
            ("GET", f"/api/v1/datasets/{DATASET_ID}/data"),
            ("DELETE", f"/api/v1/datasets/{DATASET_ID}/data/{DATA_ID}"),
        ])
        self.assertTrue((await memory.status())["reachable"])

    async def test_forget_is_idempotent_for_missing_dataset_or_file(self):
        for datasets, items in [([], []), ([{"id": OTHER_DATASET_ID, "name": "other"}], []), ([{"id": DATASET_ID, "name": "bodybrain"}], [])]:
            with self.subTest(datasets=datasets):
                requests = []

                def handle(request):
                    requests.append(request)
                    self.assertEqual(request.method, "GET")
                    return httpx.Response(200, json=datasets if request.url.path == "/api/v1/datasets/" else items)

                memory = CogneeMemory("rest", base_url="https://example.test", transport=httpx.MockTransport(handle))
                self.assertEqual((await memory.forget("doc-1"))["status"], "not_found")
                self.assertEqual((await memory.forget("doc-1"))["status"], "not_found")
                self.assertEqual(len(requests), 4 if datasets and datasets[0]["name"] == "bodybrain" else 2)

    async def test_forget_does_not_match_prefix_suffix_path_or_metadata(self):
        names = ["bodybrain_doc-10", "bodybrain_doc-1_extra", "prefix_bodybrain_doc-1", "bodybrain_doc-1.txt", "/uploads/bodybrain_doc-1", "unrelated"]
        items = [data_item(id=str(UUID(int=index + 1)), name=name, rawDataLocation="/private/bodybrain_doc-1.txt", bodybrain_document_id="doc-1") for index, name in enumerate(names)]
        items.append(data_item(id=OTHER_DATA_ID, extension="pdf"))

        def handle(request):
            self.assertEqual(request.method, "GET")
            return httpx.Response(200, json=[{"id": DATASET_ID, "name": "bodybrain"}] if request.url.path == "/api/v1/datasets/" else items)

        memory = CogneeMemory("rest", base_url="https://example.test", transport=httpx.MockTransport(handle))
        self.assertEqual((await memory.forget("doc-1"))["status"], "not_found")

    async def test_forget_rejects_malformed_or_ambiguous_dataset_list_before_deletion(self):
        dataset = {"id": DATASET_ID, "name": "bodybrain"}
        for payload in [{"datasets": [dataset]}, None, [None], [dataset, {"id": OTHER_DATASET_ID}], [{**dataset, "id": "../other"}], [dataset, dataset], [dataset, {"id": OTHER_DATASET_ID, "name": "bodybrain"}]]:
            with self.subTest(payload=payload):
                requests = []

                def handle(request):
                    requests.append(request)
                    return httpx.Response(200, content=json.dumps(payload))

                memory = CogneeMemory("rest", base_url="https://example.test", transport=httpx.MockTransport(handle))
                with self.assertRaises(CogneeError):
                    await memory.forget("doc-1")
                self.assertEqual(len(requests), 1)
                self.assertEqual(requests[0].method, "GET")

    async def test_forget_validates_every_data_item_before_deletion(self):
        for payload in [
            {"data": [data_item()]}, None, [None],
            [data_item(), {"id": OTHER_DATA_ID, "name": "malformed"}],
            [data_item(id="../other")], [data_item(name=None)], [data_item(extension=None)],
            [data_item(datasetId=OTHER_DATASET_ID)], [data_item(dataset_id=OTHER_DATASET_ID)],
            [data_item(datasetId="invalid")],
            [data_item(), data_item()], [data_item(), data_item(id=OTHER_DATA_ID)],
        ]:
            with self.subTest(payload=payload):
                requests = []

                def handle(request):
                    requests.append(request)
                    body = [{"id": DATASET_ID, "name": "bodybrain"}] if request.url.path == "/api/v1/datasets/" else payload
                    return httpx.Response(200, content=json.dumps(body))

                memory = CogneeMemory("rest", base_url="https://example.test", transport=httpx.MockTransport(handle))
                with self.assertRaises(CogneeError):
                    await memory.forget("doc-1")
                self.assertEqual([request.method for request in requests], ["GET", "GET"])

    async def test_forget_traverses_pages_before_deleting(self):
        requests = []
        first_page = [data_item(id=str(UUID(int=index + 1)), name=f"other-{index}") for index in range(1000)]

        def handle(request):
            requests.append(request)
            if request.url.path == "/api/v1/datasets/":
                return httpx.Response(200, json=[{"id": DATASET_ID, "name": "bodybrain"}])
            if request.method == "GET":
                return httpx.Response(200, json=first_page if request.url.params["offset"] == "0" else [data_item()])
            return httpx.Response(204)

        memory = CogneeMemory("rest", base_url="https://example.test", transport=httpx.MockTransport(handle))
        self.assertEqual((await memory.forget("doc-1"))["status"], "deleted")
        self.assertEqual([request.method for request in requests], ["GET", "GET", "GET", "DELETE"])
        self.assertEqual([request.url.params["offset"] for request in requests[1:3]], ["0", "1000"])

    async def test_forget_rejects_later_page_ambiguity_before_deletion(self):
        first_page = [data_item()] + [data_item(id=str(UUID(int=index + 1)), name=f"other-{index}") for index in range(999)]
        for later_page in [[data_item(id=OTHER_DATA_ID)], first_page, [None]]:
            with self.subTest(later_page=type(later_page[0])):
                requests = []

                def handle(request):
                    requests.append(request)
                    if request.url.path == "/api/v1/datasets/":
                        return httpx.Response(200, json=[{"id": DATASET_ID, "name": "bodybrain"}])
                    return httpx.Response(200, json=first_page if request.url.params["offset"] == "0" else later_page)

                memory = CogneeMemory("rest", base_url="https://example.test", transport=httpx.MockTransport(handle))
                with self.assertRaises(CogneeError):
                    await memory.forget("doc-1")
                self.assertEqual([request.method for request in requests], ["GET", "GET", "GET"])

    async def test_forget_accepts_only_foreground_deletion_completion(self):
        for response, success in [
            (httpx.Response(200), True), (httpx.Response(204), True),
            (httpx.Response(200, content=b"null"), True),
            (httpx.Response(200, json={"status": "success"}), True),
            (httpx.Response(200, json={}), False),
            (httpx.Response(200, json={"status": "failed", "error": "private-patient-content"}), False),
            (httpx.Response(202, content=b"null"), False),
            (httpx.Response(200, content=b"invalid-json"), False),
        ]:
            with self.subTest(status=response.status_code, body=response.content):
                def handle(request):
                    if request.url.path == "/api/v1/datasets/":
                        return httpx.Response(200, json=[{"id": DATASET_ID, "name": "bodybrain"}])
                    return httpx.Response(200, json=[data_item()]) if request.method == "GET" else response

                memory = CogneeMemory("rest", base_url="https://example.test", transport=httpx.MockTransport(handle))
                if success:
                    self.assertEqual((await memory.forget("doc-1"))["status"], "deleted")
                else:
                    with self.assertRaises(CogneeError) as raised:
                        await memory.forget("doc-1")
                    self.assertNotIn("private-patient-content", str(raised.exception))
                    self.assertIsNotNone((await memory.status())["last_error"])

    async def test_forget_http_and_connection_failures_are_not_absence(self):
        for fail_at in range(3):
            for status in [307, 401, 403, 404, 429, 500, None]:
                with self.subTest(fail_at=fail_at, status=status):
                    requests = []

                    def handle(request):
                        index = len(requests)
                        requests.append(request)
                        if index == fail_at:
                            if status is None:
                                raise httpx.ConnectError("private-secret", request=request)
                            return httpx.Response(status, json={"error": "private-secret"})
                        return httpx.Response(200, json=[{"id": DATASET_ID, "name": "bodybrain"}] if index == 0 else [data_item()])

                    memory = CogneeMemory("rest", base_url="https://example.test", transport=httpx.MockTransport(handle))
                    with self.assertRaises(CogneeError) as raised:
                        await memory.forget("doc-1")
                    self.assertEqual(raised.exception.code, "connection_failed" if status is None else "http_error")
                    self.assertNotIn("private-secret", str(raised.exception))
                    self.assertEqual(len(requests), fail_at + 1)

    async def test_forget_retries_after_success_are_not_found(self):
        present = True
        deletes = []

        def handle(request):
            nonlocal present
            if request.url.path == "/api/v1/datasets/":
                return httpx.Response(200, json=[{"id": DATASET_ID, "name": "bodybrain"}])
            if request.method == "GET":
                return httpx.Response(200, json=[data_item()] if present else [])
            deletes.append(request)
            present = False
            return httpx.Response(204)

        memory = CogneeMemory("rest", base_url="https://example.test", transport=httpx.MockTransport(handle))
        self.assertEqual((await memory.forget("doc-1"))["status"], "deleted")
        self.assertEqual((await memory.forget("doc-1"))["status"], "not_found")
        self.assertEqual(len(deletes), 1)

    async def test_forget_unsupported_modes_and_invalid_ids_never_contact_provider(self):
        transport = httpx.MockTransport(Mock(side_effect=AssertionError("Provider must not be called")))
        memory = CogneeMemory("rest", base_url="https://example.test", transport=transport)
        for document_id in ["", "../other", "doc/1", "doc.txt", "a" * 129, None, 5]:
            with self.subTest(document_id=document_id), self.assertRaises(ValueError):
                await memory.forget(document_id)
        with patch("bodybrain.cognee_memory.importlib.import_module") as load:
            for mode, expected in [("disabled", "not_configured"), ("sdk", "deletion_unsupported")]:
                configured = CogneeMemory(mode, storage_path="/tmp/bodybrain-sdk-test", transport=transport)
                with self.assertRaises(CogneeError) as raised:
                    await configured.forget("doc-1")
                self.assertEqual(raised.exception.code, expected)
            load.assert_not_called()

    async def test_forget_serializes_with_remember(self):
        add_started = asyncio.Event()
        allow_add = asyncio.Event()
        requests = []

        async def handle(request):
            requests.append((request.method, request.url.path))
            if request.url.path == "/api/v1/add":
                add_started.set()
                await allow_add.wait()
                return httpx.Response(200, json=completed())
            if request.url.path == "/api/v1/cognify":
                return httpx.Response(200, json={"dataset-1": completed()})
            if request.url.path == "/api/v1/datasets/":
                return httpx.Response(200, json=[{"id": DATASET_ID, "name": "bodybrain"}])
            if request.method == "GET":
                return httpx.Response(200, json=[data_item()])
            return httpx.Response(204)

        memory = CogneeMemory("rest", base_url="https://example.test", transport=httpx.MockTransport(handle))
        remember = asyncio.create_task(memory.remember("doc-1", "Evidence"))
        await asyncio.wait_for(add_started.wait(), 1)
        forget = asyncio.create_task(memory.forget("doc-1"))
        await asyncio.sleep(0)
        self.assertEqual(requests, [("POST", "/api/v1/add")])
        allow_add.set()
        await asyncio.wait_for(asyncio.gather(remember, forget), 1)
        self.assertEqual(requests, [
            ("POST", "/api/v1/add"), ("POST", "/api/v1/cognify"),
            ("GET", "/api/v1/datasets/"), ("GET", f"/api/v1/datasets/{DATASET_ID}/data"),
            ("DELETE", f"/api/v1/datasets/{DATASET_ID}/data/{DATA_ID}"),
        ])

    async def test_target_identity_is_normalized_credential_free_and_detached(self):
        memory = CogneeMemory("rest", base_url="https://tenant.example.test/api/v1/", dataset=" patient-one ", api_key="private-secret")
        self.assertEqual(memory.target_identity, {"mode": "rest", "dataset": "patient-one", "base_url": "https://tenant.example.test"})
        memory.target_identity["dataset"] = "changed"
        self.assertEqual(memory.target_identity["dataset"], "patient-one")
        sdk = CogneeMemory("sdk", storage_path="/tmp/bodybrain-sdk-test")
        self.assertEqual(sdk.target_identity, {"mode": "sdk", "dataset": "bodybrain", "storage_path": str(Path("/tmp/bodybrain-sdk-test").resolve())})


if __name__ == "__main__":
    unittest.main()
