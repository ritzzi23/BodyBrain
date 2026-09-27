"""Answers only expose excerpts from approved, source-verified records."""
import re

STOP_WORDS = set("a an the and or in of to my me what which when did does is was were has had have it its for with from show tell about say said report reports doctor complete history summary everything timeline please problem happened why how this that you your mention mentioned document documented record records".split())


def tokens(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) > 1 and word not in STOP_WORDS}


def verified_quote(record: dict, page: int, quote: str) -> bool:
    return bool(quote.strip()) and any(p["page"] == page and quote in p["text"] for p in record["pages"])


def citations_for(records: list[dict], question: str = "", concept_id: str | None = None, provider_ids: set[str] | None = None, limit: int = 8, provider_passages: dict[str, list[str]] | None = None) -> tuple[list[dict], list[dict]]:
    terms = tokens(question)
    candidates = []
    concepts = {}
    broad = not terms
    for record in records:
        if record["status"] != "approved":
            continue
        for finding in record["findings"]:
            if not finding.get("approved") or not verified_quote(record, finding["page"], finding["quote"]):
                continue
            concept = finding.get("concept")
            if concept_id and (not concept or concept["id"] != concept_id):
                continue
            overlap = len(terms & tokens(finding["quote"] + " " + finding["anatomy_query"]))
            # Provider document matches affect ranking, never authorize unrelated
            # passages elsewhere in the same file.
            provider_match = provider_ids is not None and record["id"] in provider_ids
            passage_match = any(finding["quote"] in passage for passage in (provider_passages or {}).get(record["id"], []))
            if terms and not broad and not overlap and not passage_match:
                continue
            score = overlap + (4 if provider_match else 0)
            candidates.append((score, record.get("event_date") or "", record, finding))
    seen = set()
    citations = []
    for _, _, record, finding in sorted(candidates, key=lambda row: (row[0], row[1]), reverse=True):
        key = (record["id"], finding["page"], finding["quote"])
        if key in seen:
            # Retain every mapped structure supported by a selected quotation.
            if finding.get("concept"):
                concepts[finding["concept"]["id"]] = finding["concept"]
            continue
        if len(citations) >= limit:
            continue
        seen.add(key)
        citations.append({"record_id": record["id"], "title": record["title"], "page": finding["page"], "quote": finding["quote"], "event_date": record.get("event_date")})
        if finding.get("concept"):
            concepts[finding["concept"]["id"]] = finding["concept"]
    citations.sort(key=lambda c: c["event_date"] or "9999")
    return citations, list(concepts.values())


def render_answer(citations: list[dict], *, summary: bool = False) -> str:
    if not citations:
        return "I couldn’t find supporting evidence in your reviewed records. Add a relevant record or review a pending import. I won’t infer a finding that is missing from your sources."
    intro = "History from reviewed records" if summary else "Here is what your reviewed records document"
    lines = [intro + ":"]
    for i, citation in enumerate(citations, 1):
        lines.append(f"\n[{i}] {citation.get('event_date') or 'Date not recorded'} — {citation['title']} (page {citation['page']}):\n“{citation['quote']}”")
    return "\n".join(lines)
