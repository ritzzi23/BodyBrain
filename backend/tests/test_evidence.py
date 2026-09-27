"""Evidence boundaries: review, source ownership, relevance, and empty results."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock

from bodybrain.evidence import citations_for, render_answer, verified_quote


def finding(quote="No fracture of the left femur.", *, approved=True, page=1, concept_id="left-femur", anatomy_query="left femur"):
    return {
        "id": f"finding-{concept_id or 'unmapped'}-{page}",
        "quote": quote,
        "page": page,
        "approved": approved,
        "anatomy_query": anatomy_query,
        "concept": {"id": concept_id, "label": anatomy_query} if concept_id else None,
    }


def record(record_id="report-1", *, findings=None, status="approved", title="Medical record", event_date="2026-03-01", pages=None):
    findings = findings if findings is not None else [finding()]
    return {
        "id": record_id,
        "status": status,
        "title": title,
        "event_date": event_date,
        "findings": findings,
        "pages": pages if pages is not None else [{"page": 1, "text": "\n".join(item["quote"] for item in findings)}],
    }


class EvidenceTests(unittest.TestCase):
    def test_pending_and_rejected_findings_are_excluded_even_when_provider_matches(self):
        pending = record("pending", status="pending_review")
        rejected = record("rejected", findings=[finding(approved=False)])
        citations, concepts = citations_for([pending, rejected], "femur", provider_ids={"pending", "rejected"})
        self.assertEqual(citations, [])
        self.assertEqual(concepts, [])

    def test_rejected_passage_in_same_approved_record_never_leaks(self):
        source = record(findings=[finding(), finding("The liver contains a cyst.", approved=False, concept_id="liver", anatomy_query="liver")])
        citations, concepts = citations_for([source], "history")
        self.assertEqual([item["quote"] for item in citations], ["No fracture of the left femur."])
        self.assertEqual([item["id"] for item in concepts], ["left-femur"])

    def test_quote_must_occur_on_its_claimed_page(self):
        source = record(pages=[{"page": 1, "text": "Different content"}, {"page": 2, "text": "No fracture of the left femur."}])
        self.assertFalse(verified_quote(source, 1, source["findings"][0]["quote"]))
        self.assertTrue(verified_quote(source, 2, source["findings"][0]["quote"]))
        self.assertEqual(citations_for([source], "femur")[0], [])

    def test_quote_in_another_record_does_not_verify_wrong_source(self):
        wrong = record("wrong", pages=[{"page": 1, "text": "Heart rate was recorded."}])
        correct_but_pending = record("right", status="pending_review")
        citations, _ = citations_for([wrong, correct_but_pending], "femur", provider_ids={"wrong"})
        self.assertEqual(citations, [])

    def test_blank_or_fabricated_quotes_do_not_verify(self):
        source = record()
        self.assertFalse(verified_quote(source, 1, "  "))
        self.assertFalse(verified_quote(source, 1, "A femur fracture is present."))
        self.assertFalse(verified_quote(source, 4, source["findings"][0]["quote"]))

    def test_negation_is_preserved_in_rendered_local_answer(self):
        citations, _ = citations_for([record()], "femur fracture")
        answer = render_answer(citations)
        self.assertIn("No fracture of the left femur.", answer)
        self.assertEqual(citations[0]["quote"], "No fracture of the left femur.")

    def test_empty_or_unrelated_data_has_an_explicit_no_evidence_answer(self):
        for sources in ([], [record()]):
            citations, concepts = citations_for(sources, "Which medication dosage was prescribed?")
            self.assertEqual(citations, [])
            self.assertEqual(concepts, [])
            self.assertIn("couldn’t find supporting evidence", render_answer(citations))

    def test_history_question_still_respects_its_anatomical_subject(self):
        femur = record("femur")
        kidney = record("kidney", findings=[finding("The left kidney is normal.", concept_id="kidney", anatomy_query="left kidney")])
        citations, concepts = citations_for([femur, kidney], "What is the history of my kidney?")
        self.assertEqual([item["record_id"] for item in citations], ["kidney"])
        self.assertEqual([item["id"] for item in concepts], ["kidney"])

    def test_generic_history_can_include_all_reviewed_sources(self):
        sources = [record("first"), record("second", findings=[finding("The left kidney is normal.", concept_id="kidney", anatomy_query="left kidney")])]
        citations, _ = citations_for(sources, "Show my complete history please")
        self.assertEqual({item["record_id"] for item in citations}, {"first", "second"})

    def test_shared_document_title_does_not_make_unrelated_findings_relevant(self):
        source = record(title="Left femur follow-up", findings=[finding(), finding("The liver contains a cyst.", concept_id="liver", anatomy_query="liver")])
        citations, concepts = citations_for([source], "left femur")
        self.assertEqual([item["quote"] for item in citations], ["No fracture of the left femur."])
        self.assertEqual([item["id"] for item in concepts], ["left-femur"])

    def test_provider_document_id_alone_does_not_support_every_finding(self):
        source = record(findings=[finding(), finding("The liver contains a cyst.", concept_id="liver", anatomy_query="liver")])
        citations, concepts = citations_for([source], "femur", provider_ids={source["id"]})
        self.assertEqual([item["quote"] for item in citations], ["No fracture of the left femur."])
        self.assertEqual([item["id"] for item in concepts], ["left-femur"])

    def test_unrecognized_provider_source_ids_do_not_create_citations(self):
        citations, concepts = citations_for([record()], "kidney", provider_ids={"not-a-local-document"})
        self.assertEqual(citations, [])
        self.assertEqual(concepts, [])

    def test_semantic_provider_passage_must_contain_complete_reviewed_quote(self):
        source = record()
        citations, _ = citations_for([source], "thigh bone scan", provider_ids={source["id"]}, provider_passages={source["id"]: ["[[bodybrain-document:report-1]]\nNo fracture of the left femur."]})
        self.assertEqual([item["quote"] for item in citations], [source["findings"][0]["quote"]])
        truncated, _ = citations_for([source], "thigh bone scan", provider_ids={source["id"]}, provider_passages={source["id"]: ["fracture of the left femur"]})
        self.assertEqual(truncated, [])

    def test_provider_passage_cannot_borrow_quote_from_another_source(self):
        first = record("first")
        second = record("second", findings=[finding("The kidney is normal.", concept_id="kidney", anatomy_query="kidney")])
        citations, _ = citations_for([first, second], "thigh bone scan", provider_ids={"second"}, provider_passages={"second": [first["findings"][0]["quote"]]})
        self.assertEqual(citations, [])

    def test_concept_filter_cannot_pull_other_structures_or_rejected_findings(self):
        source = record(findings=[finding(), finding("The liver contains a cyst.", concept_id="liver", anatomy_query="liver")])
        citations, concepts = citations_for([source], concept_id="left-femur")
        self.assertEqual([item["quote"] for item in citations], ["No fracture of the left femur."])
        self.assertEqual([item["id"] for item in concepts], ["left-femur"])

    def test_selected_body_part_does_not_invent_support_for_unrelated_question(self):
        citations, concepts = citations_for([record()], "What medication dosage was prescribed?", concept_id="left-femur")
        self.assertEqual(citations, [])
        self.assertEqual(concepts, [])

    def test_one_quote_supporting_multiple_anatomy_mappings_keeps_both(self):
        quote = "The right femur and right tibia appear normal."
        source = record(findings=[finding(quote, concept_id="right-femur", anatomy_query="right femur"), finding(quote, concept_id="right-tibia", anatomy_query="right tibia")])
        citations, concepts = citations_for([source], "history")
        self.assertEqual(len(citations), 1)
        self.assertEqual({item["id"] for item in concepts}, {"right-femur", "right-tibia"})

    def test_matching_quotes_from_different_sources_keep_distinct_provenance(self):
        citations, _ = citations_for([record("first"), record("second")], "femur")
        self.assertEqual({item["record_id"] for item in citations}, {"first", "second"})

    def test_limited_out_findings_do_not_add_highlights(self):
        sources = [record("femur", event_date="2026-03-01"), record("kidney", event_date="2026-01-01", findings=[finding("The kidney appears normal.", concept_id="kidney", anatomy_query="kidney")])]
        citations, concepts = citations_for(sources, "history", limit=1)
        self.assertEqual(len(citations), 1)
        self.assertEqual([item["id"] for item in concepts], ["left-femur"])

    def test_dated_history_orders_events_and_places_unknown_date_last(self):
        citations, _ = citations_for([record("unknown", event_date=None), record("later", event_date="2026-09-01"), record("earlier", event_date="2026-01-01")], "history")
        self.assertEqual([item["record_id"] for item in citations], ["earlier", "later", "unknown"])

    def test_retrieval_does_not_mutate_reviewed_source(self):
        source = record()
        original = deepcopy(source)
        citations_for([source], "femur", provider_ids={source["id"]})
        self.assertEqual(source, original)


class AgentEvidenceScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_only_snapshots_selected_quotes_and_excludes_pending_records(self):
        from bodybrain.db import Store
        from bodybrain.service import Service

        selected_quote = "No fracture of the left femur."
        rejected_quote = "UNSELECTED_PRIVATE_CONTENT about the liver."
        approved = record(findings=[finding(selected_quote), finding(rejected_quote, approved=False, concept_id="liver", anatomy_query="liver")])
        pending = record("pending-record", status="pending_review", findings=[finding("PENDING_PRIVATE_CONTENT about the kidney.", approved=False, concept_id="kidney", anatomy_query="kidney")])
        with tempfile.TemporaryDirectory() as directory:
            service = Service.__new__(Service)
            service.settings = SimpleNamespace(agent_token="test-only")
            service.store = Store(Path(directory) / "evidence.sqlite3")
            client = SimpleNamespace(configured=True, trigger_task=AsyncMock(return_value={"status": "submitted"}))
            service.clawmax_ingest = client
            service.clawmax_evidence = client
            for source in (approved, pending):
                source.update(digest=source["id"], memory_status="not_indexed", record_type="report", created_at="2026-09-27T00:00:00Z", text="\n".join(page["text"] for page in source["pages"]))
                service.store.insert(source)
            task = await service.dispatch("evidence", question="What is recorded about my femur?")
            self.assertEqual(task["allowed_record_ids"], [approved["id"]])
            self.assertEqual(len(task["records"]), 1)
            snapshot = task["records"][0]
            self.assertEqual([item["quote"] for item in snapshot["findings"]], [selected_quote])
            self.assertNotIn("UNSELECTED_PRIVATE_CONTENT", str(snapshot))
            self.assertNotIn("PENDING_PRIVATE_CONTENT", str(task))
            self.assertNotIn("text", snapshot)
            self.assertTrue(verified_quote(snapshot, 1, selected_quote))
            self.assertFalse(verified_quote(snapshot, 1, rejected_quote))
            client.trigger_task.assert_awaited_once_with(task["id"])


if __name__ == "__main__":
    unittest.main()
