"""Conservative mapping to the actual atlas. No inferred diagnostic specificity."""
from pathlib import Path
import json
import re
import uuid

MAX_FINDINGS = 150
LONG_PASSAGE_CHARS = 2000
LONG_PASSAGE_WARNING = (
    "A source passage exceeds 2,000 characters and was kept whole to preserve its "
    "context. Review the complete passage before approval."
)
FINDING_LIMIT_WARNING = (
    "Only the first 150 source findings are available for review. Additional "
    "passages remain in the original source and will not enter memory; split "
    "the document into smaller imports to review them."
)

# Ambiguous punctuation stays within a passage. A longer exact quote is safer
# than detaching an anatomy mention from its qualifying or negating context.
_ABBREVIATIONS = {
    "approx", "bilat", "cc", "cm", "dept", "dr", "dx", "eg", "etc", "excl",
    "fig", "fx", "hr", "hrs", "hx", "ie", "incl", "jr", "kg", "lt", "max",
    "mcg", "mg", "min", "ml", "mm", "mr", "mrs", "ms", "no", "pt", "ref",
    "rt", "rx", "sr", "st", "tx", "vs",
}
_SENTENCE_END = re.compile(r"[.!?]+[\"'\u201d\u2019)\]]*(?=\s|$)")


def _warn(warnings: list[str] | None, message: str) -> None:
    if warnings is not None and message not in warnings:
        warnings.append(message)


def source_passages(text: str, *, warnings: list[str] | None = None) -> list[str]:
    """Return complete, verbatim passages without treating wrapping as syntax.

    Line breaks alone are not sentence boundaries. Periods inside decimals and
    common abbreviations are preserved, as are ambiguous initials/ellipses. No
    length-based slicing is allowed: even an unusually long unpunctuated passage
    may contain a qualifier at its beginning and an anatomy mention at its end.
    The input document's existing size limit bounds such passages.
    """
    passages = []
    start = 0
    for boundary in _SENTENCE_END.finditer(text):
        punctuation = boundary.group()
        if punctuation.startswith("."):
            word_start = boundary.start()
            while word_start and (text[word_start - 1].isalnum() or text[word_start - 1] in "_."):
                word_start -= 1
            word = text[word_start:boundary.start()]
            next_character = boundary.end()
            while next_character < len(text) and text[next_character].isspace():
                next_character += 1
            following = text[next_character:next_character + 1]
            if (
                punctuation.startswith("..")
                or word.lower() in _ABBREVIATIONS
                or re.fullmatch(r"(?:[A-Za-z]\.)*[A-Za-z]", word)
                or (word[-1:].isdigit() and following.isdigit())
            ):
                continue
        passage = text[start:boundary.end()].strip()
        if passage:
            passages.append(passage)
        start = boundary.end()
    tail = text[start:].strip()
    if tail:
        passages.append(tail)
    if any(len(passage) > LONG_PASSAGE_CHARS for passage in passages):
        _warn(warnings, LONG_PASSAGE_WARNING)
    return passages


def complete_source_quote(text: str, quote: str) -> bool:
    """Require exact source text spanning one or more complete passages.

    Substring verification alone can accept a quotation that omits "No" or the
    beginning of a decimal. Ingestion proposals must also preserve the passage
    boundaries used for local extraction. Multiple adjacent passages are valid
    only with their original intervening whitespace. Outer source whitespace is
    harmless, but a normalized/reconstructed quotation is never accepted.
    """
    if not quote.strip() or quote not in text:
        return False
    quote = quote.strip()
    starts = []
    ends = set()
    cursor = 0
    for passage in source_passages(text):
        start = text.index(passage, cursor)
        cursor = start + len(passage)
        starts.append(start)
        ends.add(cursor)
    return any(start + len(quote) in ends and text.startswith(quote, start) for start in starts)


# These aliases express anatomical names, never diagnoses or causal relationships.
ALIASES = {
    "l5-s1": "intervertebral disk of fifth lumbar vertebra",
    "l4-l5": "intervertebral disk of fourth lumbar vertebra",
    "l3-l4": "intervertebral disk of third lumbar vertebra",
    "c5-c6": "intervertebral disk of fifth cervical vertebra",
    "c6-c7": "intervertebral disk of sixth cervical vertebra",
    "lumbar spine": "lumbar vertebral column",
    "cervical spine": "cervical vertebral column",
    "thoracic spine": "thoracic vertebral column",
    "spine": "vertebral column",
    "l5": "fifth lumbar vertebra",
    "l4": "fourth lumbar vertebra",
}


class Anatomy:
    def __init__(self, path: Path):
        atlas = json.loads(path.read_text())
        self.concepts = atlas["concepts"]
        self.by_id = {c["id"]: c for c in self.concepts}
        self.by_name = {c["name"].lower(): c for c in self.concepts}
        self.patterns = [(name, re.compile(r"(?<![\w])" + re.escape(name).replace(r"\ ", r"\s+") + r"(?![\w])", re.I)) for name in self.by_name if len(name) > 3]

    def search(self, query: str, limit: int = 20) -> list[dict]:
        term = query.lower().strip()
        if not term:
            return []
        matches = [c for c in self.concepts if term in c["name"].lower() or term in c["id"].lower()]
        return sorted(matches, key=lambda c: (c["name"].lower() != term, len(c["name"])))[:limit]

    def matches(self, text: str) -> list[tuple[str, dict | None]]:
        hits: list[tuple[int, int, str, dict | None]] = []
        for alias, target in ALIASES.items():
            for match in re.finditer(r"(?<![\w])" + re.escape(alias).replace(r"\ ", r"\s+") + r"(?![\w])", text, re.I):
                hits.append((match.start(), match.end(), match.group(), self.by_name.get(target)))
        for name, pattern in self.patterns:
            for match in pattern.finditer(text):
                hits.append((match.start(), match.end(), match.group(), self.by_name[name]))
        # Explicit nerve-root mentions stay visible even when the atlas has no matching mesh.
        for match in re.finditer(r"\b(?:(?:right|left)\s+)?[CSLT]\d\s+nerve\s+root\b", text, re.I):
            hits.append((match.start(), match.end(), match.group(), self.by_name.get(match.group().lower())))
        # Prefer complete phrases over partial ones, preserving laterality and levels.
        accepted = []
        for hit in sorted(hits, key=lambda h: (-(h[1]-h[0]), h[0])):
            if not any(hit[0] < old[1] and hit[1] > old[0] for old in accepted):
                accepted.append(hit)
        seen = set()
        result = []
        for _, _, phrase, concept in sorted(accepted):
            key = (phrase.lower(), concept["id"] if concept else None)
            if key not in seen:
                seen.add(key)
                result.append((phrase, concept))
        return result

    def extract(self, pages: list[dict], *, warnings: list[str] | None = None) -> list[dict]:
        findings = []
        for page in pages:
            # Keep original passages and negation intact. The UI calls these mentions,
            # not diagnoses; an LLM is not permitted to fill in missing facts.
            passages = source_passages(page["text"], warnings=warnings)
            for passage in passages:
                matches = self.matches(passage)
                for phrase, concept in matches:
                    if len(findings) >= MAX_FINDINGS:
                        _warn(warnings, FINDING_LIMIT_WARNING)
                        return findings
                    side = re.search(r"\b(left|right|bilateral)\b", phrase, re.I)
                    findings.append({
                        "id": str(uuid.uuid4()), "quote": passage, "page": page["page"],
                        "anatomy_query": phrase, "concept": concept,
                        "mapping_status": "matched" if concept else "unmapped",
                        "laterality": side.group().lower() if side else None,
                        "evidence_type": "source_mention", "approved": False,
                    })
        return findings
