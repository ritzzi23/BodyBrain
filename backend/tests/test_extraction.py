import json

import pytest

from bodybrain.anatomy import (
    Anatomy,
    FINDING_LIMIT_WARNING,
    LONG_PASSAGE_WARNING,
    MAX_FINDINGS,
    complete_source_quote,
    source_passages,
)
from bodybrain.evidence import verified_quote


@pytest.fixture
def anatomy(tmp_path):
    atlas = tmp_path / "atlas.json"
    atlas.write_text(json.dumps({"concepts": [
        {"id": "test-femur", "name": "right femur", "elements": []},
        {"id": "test-lumbar", "name": "lumbar vertebral column", "elements": []},
    ]}))
    return Anatomy(atlas)


@pytest.mark.parametrize("text", [
    "No 2.3 cm lesion in the right femur.",
    "No 2.3 cm. lesion in the right femur.",
    "No 2.\n3 cm lesion in the right femur.",
    "No\nfracture of the right femur.",
    "No evidence of\r\nfracture of the right\r\nfemur.",
    "No fracture, per Dr. Smith, of the right femur.",
    "No fx. of the right femur.",
    "No abnormality e.g. fracture in the right femur.",
    "No abnormality... of the right femur.",
    "No abnormality in the right femur",
])
def test_qualifiers_and_wrapping_remain_in_exact_source_quotes(anatomy, text):
    pages = [{"page": 2, "text": text}]
    findings = anatomy.extract(pages)

    assert len(findings) == 1
    assert findings[0]["quote"] == text
    assert findings[0]["concept"]["id"] == "test-femur"
    assert verified_quote({"pages": pages}, 2, findings[0]["quote"])


def test_wrapped_alias_matches_without_rewriting_source(anatomy):
    text = "No fracture of the lumbar\nspine."

    finding, = anatomy.extract([{"page": 1, "text": text}])

    assert finding["anatomy_query"] == "lumbar\nspine"
    assert finding["concept"]["id"] == "test-lumbar"
    assert finding["quote"] == text


def test_ordinary_sentences_split_without_losing_source_content():
    text = '  First observation.\n"Second observation!"\nThird observation? Final note  '

    passages = source_passages(text)

    assert passages == [
        "First observation.", '"Second observation!"', "Third observation?", "Final note",
    ]
    assert all(passage in text for passage in passages)
    assert "".join("".join(passages).split()) == "".join(text.split())


@pytest.mark.parametrize("text", ["Brief note.", "OK", "Follow\nup", ".", "!"])
def test_short_source_passages_are_available_for_review(text):
    assert source_passages(text) == [text]


def test_whitespace_only_source_has_no_passages():
    assert source_passages(" \n\t ") == []


def test_long_qualifier_is_not_dropped_or_detached_from_anatomy(anatomy):
    text = "No " + "new or previously identified " * 100 + "lesion in the right femur."
    warnings = []

    finding, = anatomy.extract([{"page": 1, "text": text}], warnings=warnings)

    assert finding["quote"] == text
    assert warnings == [LONG_PASSAGE_WARNING]


def test_long_nonanatomical_passage_retains_context_and_warns_once():
    text = "No " + "medication changes " * 200
    warnings = []

    for _ in range(2):
        assert source_passages(text, warnings=warnings) == [text.strip()]
    assert warnings == [LONG_PASSAGE_WARNING]


def test_finding_limit_reports_omitted_anatomical_evidence(anatomy):
    text = "No fracture of the right femur. " * (MAX_FINDINGS + 1)
    warnings = []

    findings = anatomy.extract([{"page": 1, "text": text}], warnings=warnings)

    assert len(findings) == MAX_FINDINGS
    assert warnings == [FINDING_LIMIT_WARNING]
    assert all(finding["quote"] == "No fracture of the right femur." for finding in findings)


def test_exact_finding_limit_does_not_claim_evidence_was_omitted(anatomy):
    text = "No fracture of the right femur. " * MAX_FINDINGS + "Follow up."
    warnings = []

    findings = anatomy.extract([{"page": 1, "text": text}], warnings=warnings)

    assert len(findings) == MAX_FINDINGS
    assert warnings == []


def test_passages_never_cross_source_pages(anatomy):
    pages = [
        {"page": 1, "text": "No fracture of the right femur."},
        {"page": 2, "text": "Lumbar spine appears normal."},
    ]

    findings = anatomy.extract(pages)

    assert [finding["page"] for finding in findings] == [1, 2]
    assert all(verified_quote({"pages": pages}, finding["page"], finding["quote"]) for finding in findings)


@pytest.mark.parametrize("text,quote", [
    ("No 2.3 cm lesion in the right femur.", "No 2.3 cm lesion in the right femur."),
    ("No\nfracture of the right femur.", "No\nfracture of the right femur."),
    ("First note.\nNo fracture. Last note.", "No fracture."),
    ("First note.\nNo fracture. Last note.", "First note.\nNo fracture."),
    (" First note.\nNo fracture. Last note. ", " First note.\nNo fracture. Last note. "),
    ("No fracture. fracture.", "fracture."),
])
def test_complete_quotes_accept_full_single_and_contiguous_passages(text, quote):
    assert complete_source_quote(text, quote)


@pytest.mark.parametrize("text,quote", [
    ("No 2.3 cm lesion in the right femur.", "3 cm lesion in the right femur."),
    ("No fracture of the right femur.", "fracture of the right femur."),
    ("No\nfracture of the right femur.", "fracture of the right femur."),
    ("No fracture of the right femur.", "No fracture"),
    ("First note.\nNo fracture. Last note.", "First note. No fracture."),
    ("Report date: 2026-03-15\nNo fracture.", "No fracture."),
    ("No fracture.", ""),
    ("No fracture.\n", "\n"),
    ("No fracture.", "Invented diagnosis."),
])
def test_complete_quotes_reject_fragments_and_rewritten_source(text, quote):
    assert not complete_source_quote(text, quote)
