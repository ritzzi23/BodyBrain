from dataclasses import replace
from io import BytesIO

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
import pytest

from bodybrain.config import Settings
from bodybrain.main import create_app


TEXT = "Report date: 2026-03-15\nLumbar spine MRI. At L5-S1, a right disc protrusion contacts the right S1 nerve root.\nNo fracture of the right femur."


@pytest.fixture
def settings(tmp_path):
    return replace(Settings(), data_dir=tmp_path, cognee_mode="disabled", cognee_url="", cognee_api_key="", cognee_token="", clawmax_url="", clawmax_token="", api_token="", agent_token="test-agent-secret")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def add(client, text=TEXT, **fields):
    response = client.post("/api/records/text", json={"title": "Test report", "text": text, **fields})
    assert response.status_code == 201, response.text
    return response.json()


def test_ingest_review_recall_and_restart(client, settings):
    record = add(client)
    assert record["status"] == "pending_review"
    assert record["event_date"] == "2026-03-15"
    assert any(f["anatomy_query"].lower() == "l5-s1" and f["concept"] for f in record["findings"])
    assert any(f["anatomy_query"].lower() == "right s1 nerve root" and f["concept"] is None for f in record["findings"])
    assert not client.post("/api/chat", json={"question": "What did the MRI say?"}).json()["citations"]
    response = client.post(f"/api/records/{record['id']}/approve", json={})
    assert response.status_code == 200
    assert response.json()["memory_status"] == "unconfigured"
    answer = client.post("/api/chat", json={"question": "Which nerve did the MRI mention?"}).json()
    assert answer["citations"] and answer["retrieval_mode"] == "local_evidence"
    assert any("right S1 nerve root" in c["quote"] for c in answer["citations"])
    assert client.get(f"/api/records/{record['id']}/source").content.decode() == TEXT
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get("/api/health").json()["counts"]["approved"] == 1
        assert restarted.get("/api/timeline").json()["events"][0]["id"] == record["id"]
        assert restarted.get("/api/summary").json()["citations"]


def test_rejected_findings_do_not_enter_recall(client):
    record = add(client)
    femur = next(f for f in record["findings"] if "femur" in f["quote"])
    approved = client.post(f"/api/records/{record['id']}/approve", json={"finding_ids": [femur["id"]]})
    assert approved.status_code == 200
    answer = client.post("/api/chat", json={"question": "right femur"}).json()
    assert len(answer["citations"]) == 1
    assert answer["citations"][0]["quote"] == "No fracture of the right femur."
    missing = client.post("/api/chat", json={"question": "S1 nerve"}).json()
    assert missing["citations"] == []


def test_unknown_question_does_not_invent_answer(client):
    record = add(client)
    client.post(f"/api/records/{record['id']}/approve", json={})
    answer = client.post("/api/chat", json={"question": "What medication dosage was prescribed?"}).json()
    assert not answer["citations"]
    assert "couldn’t find" in answer["answer"]


def test_duplicate_idempotent_and_distinct_explicit_dates(client):
    first = add(client)
    assert add(client)["id"] == first["id"]
    other = add(client, event_date="2026-04-01")
    assert other["id"] != first["id"]
    assert len(client.get("/api/records").json()["records"]) == 2


def test_dates_are_not_guessed_from_birthdays(client):
    record = add(client, "DOB: 1988-01-01\nLumbar spine findings discussed.")
    assert record["event_date"] is None


def test_invalid_files_and_review_states(client):
    assert client.post("/api/records", files={"file": ("fake.pdf", b"not a PDF")}).status_code == 422
    assert client.post("/api/records", files={"file": ("file.html", b"<script>alert(1)</script>")}).status_code == 422
    assert client.post("/api/records/text", json={"title": "Empty", "text": "   "}).status_code == 422
    record = add(client)
    assert client.post(f"/api/records/{record['id']}/index").status_code == 409
    assert client.post(f"/api/records/{record['id']}/approve", json={"finding_ids": []}).status_code == 422
    assert client.post(f"/api/records/{record['id']}/approve", json={"finding_ids": ["made-up"]}).status_code == 422
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    stream = BytesIO()
    writer.write(stream)
    response = client.post("/api/records", files={"file": ("scan.pdf", stream.getvalue())})
    assert response.status_code == 422 and "OCR" in response.json()["detail"]


def test_mapping_validates_atlas_and_human_checkpoint(client):
    record = add(client)
    finding = record["findings"][0]
    route = f"/api/records/{record['id']}/mapping"
    assert client.patch(route, json={"finding_id": finding["id"], "concept_id": "FMA-notreal"}).status_code == 422
    assert client.patch(route, json={"finding_id": finding["id"], "concept_id": None}).status_code == 200
    client.post(f"/api/records/{record['id']}/approve", json={})
    assert client.patch(route, json={"finding_id": finding["id"], "concept_id": None}).status_code == 409


def test_local_origin_and_agent_auth(client):
    assert client.get("/api/health", headers={"Origin": "https://untrusted.invalid"}).status_code == 403
    assert client.get("/api/agent/anatomy?q=heart").status_code == 401
    response = client.get("/api/agent/anatomy?q=heart", headers={"Authorization": "Bearer test-agent-secret"})
    assert response.status_code == 200 and response.json()["concepts"]


def test_agent_cannot_fabricate_source_or_overwrite_review(client):
    record = add(client)
    store = client.app.state.service.store
    task = {"id": "test-task", "kind": "ingestion", "status": "pending", "record_id": record["id"]}
    store.save_task(task)
    headers = {"Authorization": "Bearer test-agent-secret"}
    body = {"findings": [{"quote": "Invented diagnosis", "page": 1, "anatomy_query": "heart", "concept_id": "FMA7088"}]}
    assert client.post("/api/agent/tasks/test-task/result", json=body, headers=headers).status_code == 422
    source = record["findings"][0]
    body["findings"][0].update(quote=source["quote"], anatomy_query=source["anatomy_query"], concept_id=source["concept"]["id"])
    client.post(f"/api/records/{record['id']}/approve", json={})
    assert client.post("/api/agent/tasks/test-task/result", json=body, headers=headers).status_code == 409


def test_demo_is_explicit_and_idempotent(client):
    assert not client.get("/api/records").json()["records"]
    demo = client.post("/api/demo").json()["records"]
    assert len(demo) == 3
    assert all("SYNTHETIC" in r["text"] and r["status"] == "pending_review" for r in demo)
    client.post("/api/demo")
    assert len(client.get("/api/records").json()["records"]) == 3


def test_pdf_pages_and_negation_preserve_source(client):
    writer = PdfWriter()
    for sentence in ["Report date: 2026-03-15", "No fracture of the right femur."]:
        page = writer.add_blank_page(width=600, height=800)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 50 700 Td ({sentence}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    content = BytesIO()
    writer.write(content)
    response = client.post("/api/records", files={"file": ("report.pdf", content.getvalue(), "application/pdf")})
    assert response.status_code == 201, response.text
    record = response.json()
    assert len(record["pages"]) == 2
    assert record["findings"][0]["quote"] == "No fracture of the right femur."
    assert record["findings"][0]["page"] == 2
    assert client.get(f"/api/records/{record['id']}/source").content == content.getvalue()


def test_public_host_requires_distinct_credentials(settings):
    with pytest.raises(ValueError, match="API_TOKEN"):
        create_app(replace(settings, allowed_hosts=("bodybrain.example.com",)))
    with pytest.raises(ValueError, match="distinct"):
        create_app(replace(settings, api_token="same", agent_token="same"))
