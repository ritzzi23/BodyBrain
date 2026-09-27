"""Raw Cognee relay tests: fake provider data only; no external requests."""

import io
import json
import threading
import unittest
from email.message import Message
from http.client import IncompleteRead
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from uuid import UUID

from bodybrain.cognee_transport import CogneeFiles, CogneeTransportError


DATASET = "11111111-1111-4111-8111-111111111111"
OTHER_DATASET = "22222222-2222-4222-8222-222222222222"
DATA = "33333333-3333-4333-8333-333333333333"
OTHER_DATA = "44444444-4444-4444-8444-444444444444"
SECRET = "private-api-key"
PAYLOAD = b'{"task_id":"synthetic-task","message":"synthetic only"}'


class Response(io.BytesIO):
    def __init__(self, body=b"", status=200, headers=None):
        super().__init__(body)
        self.code = status
        self.headers = Message()
        for key, value in (headers or {}).items():
            self.headers[key] = str(value)


def json_response(value, **kwargs):
    return Response(json.dumps(value).encode(), **kwargs)


def file_item(**extra):
    return {"id": DATA, "name": "bb_task_1", "extension": "txt", "datasetId": DATASET, **extra}


class CogneeFilesTests(unittest.TestCase):
    def client(self, handler=None, **kwargs):
        client = CogneeFiles("https://tenant.example/api/v1/", api_key=SECRET, **kwargs)
        client._opener.open = Mock(side_effect=handler)
        return client

    def assert_error(self, code, function, *args):
        with self.assertRaises(CogneeTransportError) as raised:
            function(*args)
        self.assertEqual(raised.exception.code, code)
        self.assertNotIn(SECRET, str(raised.exception))
        self.assertNotIn("private-provider-data", str(raised.exception))
        return raised.exception

    def test_config_rejects_remote_plaintext_credentials_and_bad_components(self):
        for url in ["http://tenant.example", "https://user:secret@tenant.example", "https://tenant.example?token=x", "https://tenant.example/#token", "https://tenant.example/other", "file:///tmp/a", "https://tenant.example:0", "https://tenant.example:bad", "https://tenant.example\n", None]:
            with self.subTest(url=url):
                self.assert_error("invalid_config", CogneeFiles, url)
        for url in ["http://127.0.0.1:8080", "http://[::1]:8080", "http://localhost", "https://tenant.example/api/v1/"]:
            CogneeFiles(url)

    def test_config_rejects_bad_auth_limits_and_timeouts(self):
        for kwargs in [{"api_key": "a", "bearer_token": "b"}, {"api_key": "abc\r\nHeader: value"}, {"api_key": None}, {"timeout": 0}, {"timeout": float("inf")}, {"timeout": 121}, {"timeout": True}, {"max_bytes": 0}, {"max_bytes": 16_777_217}, {"max_bytes": True}]:
            with self.subTest(kwargs=kwargs):
                self.assert_error("invalid_config", lambda: CogneeFiles("https://tenant.example", **kwargs))

    def test_dataset_listing_redacts_metadata_and_uses_cloud_auth(self):
        def handle(request, timeout):
            self.assertEqual(request.full_url, "https://tenant.example/api/v1/datasets/")
            self.assertEqual(request.get_header("X-api-key"), SECRET)
            self.assertIsNone(request.get_header("Authorization"))
            self.assertEqual(timeout, 30)
            return json_response([{"id": DATASET, "name": "jobs", "rawDataLocation": "private-provider-data"}])
        self.assertEqual(self.client(handle).list_datasets(), [{"id": DATASET, "name": "jobs"}])

    def test_self_hosted_bearer_auth(self):
        client = CogneeFiles("http://127.0.0.1", bearer_token=SECRET)
        def handle(request, timeout):
            self.assertEqual(request.get_header("Authorization"), f"Bearer {SECRET}")
            self.assertIsNone(request.get_header("X-api-key"))
            return json_response([])
        client._opener.open = Mock(side_effect=handle)
        self.assertEqual(client.list_datasets(), [])

    def test_dataset_lookup_rejects_ambiguous_exact_name(self):
        client = self.client(lambda *args, **kwargs: json_response([{"id": DATASET, "name": "jobs"}, {"id": OTHER_DATASET, "name": "jobs"}]))
        self.assert_error("ambiguous_response", client.dataset, "jobs")

    def test_dataset_listing_rejects_duplicate_ids_invalid_ids_names_and_shapes(self):
        for value, code in [({}, "invalid_response"), ([None], "invalid_response"), ([{"id": "../../raw", "name": "jobs"}], "invalid_id"), ([{"id": DATASET, "name": "bad\nname"}], "invalid_name"), ([{"id": DATASET, "name": "jobs"}] * 2, "ambiguous_response")]:
            with self.subTest(value=value):
                self.assert_error(code, self.client(lambda *args, **kwargs: json_response(value)).list_datasets)

    def test_dataset_create_and_confirm(self):
        calls = []
        def handle(request, timeout):
            calls.append(request)
            if request.method == "POST":
                self.assertEqual(json.loads(request.data), {"name": "jobs"})
                return json_response({"id": DATASET, "name": "jobs"})
            return json_response([] if len(calls) == 1 else [{"id": DATASET, "name": "jobs"}])
        self.assertEqual(self.client(handle).dataset("jobs", create=True), DATASET)
        self.assertEqual([call.method for call in calls], ["GET", "POST", "GET"])

    def test_missing_dataset_does_not_create_by_default(self):
        client = self.client(lambda *args, **kwargs: json_response([]))
        self.assertIsNone(client.dataset("jobs"))
        self.assertEqual(client._opener.open.call_count, 1)

    def test_dataset_create_rejects_wrong_name_or_unverifiable_identity(self):
        for created in [{"id": DATASET, "name": "other"}, {"id": DATASET, "name": "jobs"}]:
            responses = [json_response([]), json_response(created), json_response([])]
            client = self.client(lambda *args, **kwargs: responses.pop(0))
            self.assert_error("invalid_response" if created["name"] == "other" else "ambiguous_response", lambda: client.dataset("jobs", create=True))

    def test_http_error_body_and_connection_details_are_never_exposed_or_retried(self):
        for status in [401, 403, 429, 500]:
            client = self.client(lambda *args, **kwargs: Response((SECRET + "private-provider-data").encode(), status=status))
            error = self.assert_error("http_error", client.list_datasets)
            self.assertEqual(error.retryable, status in {429, 500})
            self.assertEqual(client._opener.open.call_count, 1)
        for error in [URLError(SECRET), OSError(SECRET), IncompleteRead(b"private-provider-data", 100)]:
            self.assert_error("connection_error", self.client(Mock(side_effect=error)).list_datasets)

    def test_real_urllib_http_error_is_sanitized(self):
        error = HTTPError("https://tenant.example", 401, SECRET, Message(), io.BytesIO(b"private-provider-data"))
        self.assert_error("http_error", self.client(Mock(side_effect=error)).list_datasets)

    def test_only_one_same_origin_dataset_slash_redirect_is_accepted(self):
        calls = []
        def handle(request, timeout):
            calls.append(request)
            if len(calls) == 1:
                return Response(status=307, headers={"Location": "/api/v1/datasets"})
            self.assertEqual(request.full_url, "https://tenant.example/api/v1/datasets")
            return json_response([])
        self.assertEqual(self.client(handle).list_datasets(), [])
        self.assertEqual(len(calls), 2)
        repeat = self.client(lambda *args, **kwargs: Response(status=307, headers={"Location": "/api/v1/datasets"}))
        self.assert_error("redirect_rejected", repeat.list_datasets)
        self.assertEqual(repeat._opener.open.call_count, 2)

    def test_other_redirects_never_receive_an_authenticated_followup(self):
        for status, location in [(302, "/api/v1/datasets"), (307, "https://other.example/api/v1/datasets"), (307, "http://tenant.example/api/v1/datasets"), (307, "/api/v1/datasets?key=secret"), (307, "https://user@tenant.example/api/v1/datasets"), (307, "/unrelated"), (308, "/api/v1/datasets#fragment")]:
            with self.subTest(status=status, location=location):
                client = self.client(lambda *args, **kwargs: Response(status=status, headers={"Location": location}))
                self.assert_error("redirect_rejected", client.list_datasets)
                self.assertEqual(client._opener.open.call_count, 1)

    def test_raw_download_rejects_redirects_even_same_origin(self):
        client = self.client(lambda *args, **kwargs: Response(status=307, headers={"Location": f"/api/v1/datasets/{DATASET}/data/{DATA}/raw/"}))
        self.assert_error("redirect_rejected", client.read_file, DATASET, DATA)
        self.assertEqual(client._opener.open.call_count, 1)

    def test_body_caps_declared_and_streaming_and_encoding(self):
        for body, headers, code in [(b"", {"Content-Length": "101"}, "response_too_large"), (b"x" * 101, {}, "response_too_large"), (b"", {"Content-Length": "invalid"}, "invalid_response"), (b"", {"Content-Length": "-1"}, "invalid_response"), (b"x", {"Content-Encoding": "gzip"}, "invalid_response")]:
            client = self.client(lambda *args, **kwargs: Response(body, headers=headers), max_bytes=100)
            self.assert_error(code, client.read_file, DATASET, DATA)
        client = self.client(lambda *args, **kwargs: Response(b"x" * 100), max_bytes=100)
        self.assertEqual(client.read_file(DATASET, DATA), b"x" * 100)

    def test_invalid_json_redacts_provider_content(self):
        client = self.client(lambda *args, **kwargs: Response(b"private-provider-data"))
        self.assert_error("invalid_response", client.list_datasets)

    def test_file_listing_pages_and_normalizes_without_storage_paths(self):
        pages = [[file_item(), file_item(id=OTHER_DATA, name="bb_task_2.txt", extension=".TXT")], [file_item(id=str(UUID(int=5)), name="bb_task_3")]]
        calls = []
        def handle(request, timeout):
            calls.append(request.full_url)
            return json_response(pages.pop(0))
        with patch("bodybrain.cognee_transport._PAGE_SIZE", 2):
            result = self.client(handle).list_files(DATASET)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[1], {"id": OTHER_DATA, "name": "bb_task_2.txt", "extension": "txt"})
        self.assertTrue(calls[0].endswith("limit=2&offset=0"))
        self.assertTrue(calls[1].endswith("limit=2&offset=2"))

    def test_file_listing_repeated_page_fails(self):
        client = self.client(lambda *args, **kwargs: json_response([file_item()]))
        with patch("bodybrain.cognee_transport._PAGE_SIZE", 1):
            self.assert_error("ambiguous_response", client.list_files, DATASET)
        self.assertEqual(client._opener.open.call_count, 2)

    def test_file_listing_bounded_offset(self):
        counter = 0
        def handle(*args, **kwargs):
            nonlocal counter
            counter += 1
            return json_response([file_item(id=str(UUID(int=counter)))])
        client = self.client(handle)
        with patch("bodybrain.cognee_transport._PAGE_SIZE", 1), patch("bodybrain.cognee_transport._MAX_OFFSET", 1):
            self.assert_error("pagination_limit", client.list_files, DATASET)
        self.assertEqual(client._opener.open.call_count, 2)

    def test_file_listing_rejects_wrong_dataset_extension_and_oversized_page(self):
        for page in [[file_item(datasetId=OTHER_DATASET)], [file_item(extension="../txt")], [None], {}]:
            self.assert_error("invalid_response", self.client(lambda *args, **kwargs: json_response(page)).list_files, DATASET)
        with patch("bodybrain.cognee_transport._PAGE_SIZE", 1):
            self.assert_error("invalid_response", self.client(lambda *args, **kwargs: json_response([file_item(), file_item(id=OTHER_DATA)])).list_files, DATASET)

    def upload_client(self, *, existing=False, stored=PAYLOAD, status="PipelineRunCompleted", ambiguous=False):
        uploaded = existing
        requests = []
        def handle(request, timeout):
            nonlocal uploaded
            requests.append(request)
            route = request.full_url.split("tenant.example", 1)[1]
            if route == "/api/v1/datasets/":
                return json_response([{"id": DATASET, "name": "jobs"}])
            if route.startswith(f"/api/v1/datasets/{DATASET}/data?"):
                return json_response(([file_item(), file_item(id=OTHER_DATA, name="bb_task_1.txt")] if ambiguous else [file_item()]) if uploaded else [])
            if route.endswith("/raw"):
                return Response(stored)
            if route == "/api/v1/add":
                uploaded = True
                return json_response({"status": status, "dataset_id": DATASET})
            self.fail(f"Unexpected request: {request.method}")
        return self.client(handle), requests

    def test_upload_requires_completed_add_and_exact_raw_bytes(self):
        client, requests = self.upload_client()
        self.assertEqual(client.put_file("jobs", "bb_task_1.txt", PAYLOAD), {"dataset_id": DATASET, "data_id": DATA, "name": "bb_task_1.txt"})
        posts = [request for request in requests if request.method == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertIn('multipart/form-data; boundary=', posts[0].get_header("Content-type"))
        self.assertIn(b'name="datasetId"', posts[0].data)
        self.assertIn(DATASET.encode(), posts[0].data)
        self.assertIn(b'name="run_in_background"\r\n\r\nfalse', posts[0].data)
        self.assertIn(b'filename="bb_task_1.txt"\r\nContent-Type: text/plain', posts[0].data)
        self.assertIn(PAYLOAD, posts[0].data)
        self.assertFalse(any("cognify" in request.full_url or "search" in request.full_url for request in requests))

    def test_upload_existing_identical_bytes_is_idempotent_without_post(self):
        client, requests = self.upload_client(existing=True)
        self.assertEqual(client.put_file("jobs", "bb_task_1.txt", PAYLOAD)["data_id"], DATA)
        self.assertTrue(all(request.method == "GET" for request in requests))

    def test_upload_conflict_and_ambiguous_names_are_never_overwritten(self):
        client, requests = self.upload_client(existing=True, stored=b"different")
        self.assert_error("content_conflict", client.put_file, "jobs", "bb_task_1.txt", PAYLOAD)
        self.assertTrue(all(request.method == "GET" for request in requests))
        client, requests = self.upload_client(existing=True, ambiguous=True)
        self.assert_error("ambiguous_response", client.put_file, "jobs", "bb_task_1.txt", PAYLOAD)
        self.assertTrue(all(request.method == "GET" for request in requests))

    def test_upload_failed_pending_empty_status_never_accepted(self):
        for status in ["PipelineRunStarted", "PipelineRunErrored", "", None]:
            client, requests = self.upload_client(status=status)
            self.assert_error("upload_incomplete", client.put_file, "jobs", "bb_task_1.txt", PAYLOAD)
            self.assertEqual(sum(request.method == "POST" for request in requests), 1)
            self.assertFalse(any(request.full_url.endswith("/raw") for request in requests))

    def test_upload_raw_integrity_failure(self):
        client, _ = self.upload_client(stored=b"provider modified original")
        self.assert_error("content_conflict", client.put_file, "jobs", "bb_task_1.txt", PAYLOAD)

    def test_upload_validation_before_network(self):
        client = self.client()
        for name, content in [("../bb.txt", PAYLOAD), ('bad".txt', PAYLOAD), ("bb.json", PAYLOAD), ("bb.txt", b""), ("bb.txt", "not bytes"), ("bb.txt", b"a" * (2_097_152 + 1))]:
            self.assert_error("invalid_name" if name != "bb.txt" else "invalid_content", client.put_file, "jobs", name, content)
        client._opener.open.assert_not_called()

    def test_delete_only_exact_uuid_route_and_completed_status(self):
        requests = []
        def handle(request, timeout):
            requests.append(request)
            return Response(status=204)
        client = self.client(handle)
        client.delete_file(DATASET, DATA)
        self.assertEqual(requests[0].method, "DELETE")
        self.assertEqual(requests[0].full_url, f"https://tenant.example/api/v1/datasets/{DATASET}/data/{DATA}")
        self.assert_error("invalid_id", client.delete_file, DATASET, "../")
        self.assertEqual(len(requests), 1)
        self.assert_error("deletion_incomplete", self.client(lambda *args, **kwargs: Response(status=202)).delete_file, DATASET, DATA)

    def test_real_opener_blocks_raw_redirect_before_followup(self):
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.path)
                self.send_response(307)
                self.send_header("Location", "/should-not-receive-token")
                self.send_header("Content-Length", "0")
                self.end_headers()
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = CogneeFiles(f"http://127.0.0.1:{server.server_port}", api_key=SECRET)
            self.assert_error("redirect_rejected", client.read_file, DATASET, DATA)
            self.assertEqual(seen, [f"/api/v1/datasets/{DATASET}/data/{DATA}/raw"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
