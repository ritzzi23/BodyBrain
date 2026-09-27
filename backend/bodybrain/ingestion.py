from datetime import date
from io import BytesIO
import re

from pypdf import PdfReader


class InvalidDocument(ValueError):
    pass


def parse_document(content: bytes, filename: str, max_chars: int = 150_000) -> list[dict]:
    suffix = filename.lower().rsplit(".", 1)[-1]
    if suffix == "pdf":
        if not content.startswith(b"%PDF-"):
            raise InvalidDocument("This file does not have a valid PDF header.")
        try:
            reader = PdfReader(BytesIO(content), strict=False)
            if reader.is_encrypted:
                raise InvalidDocument("Unlock this PDF before uploading it.")
            if len(reader.pages) > 100:
                raise InvalidDocument("Upload at most 100 PDF pages at a time.")
            pages = []
            total = 0
            for number, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                total += len(text)
                if total > max_chars:
                    raise InvalidDocument("The extracted text is too large. Split this document into smaller files.")
                pages.append({"page": number, "text": text})
        except InvalidDocument:
            raise
        except Exception as exc:
            raise InvalidDocument("Could not read this PDF. Try a text-based PDF or paste its text.") from exc
    elif suffix in {"txt", "md"}:
        try:
            pages = [{"page": 1, "text": content.decode("utf-8-sig")}]
        except UnicodeDecodeError as exc:
            raise InvalidDocument("Text files must use UTF-8 encoding.") from exc
    else:
        raise InvalidDocument("Supported formats are PDF, TXT, and Markdown.")
    if not any(p["text"].strip() for p in pages):
        raise InvalidDocument("No readable text was found. Scanned PDFs need OCR; paste the report text for now.")
    if sum(len(p["text"]) for p in pages) > max_chars:
        raise InvalidDocument("Document exceeds the 150,000-character limit.")
    if any("\x00" in p["text"] for p in pages):
        raise InvalidDocument("This looks like binary content, not a text document.")
    return pages


def explicit_date(text: str) -> str | None:
    # Only a labeled ISO record date is automatically recognized. Other dates are
    # left unset rather than confusing birthdays, historical dates, and upload time.
    match = re.search(r"(?im)^\s*(?:report date|visit date|event date|date)\s*:\s*(\d{4}-\d{2}-\d{2})\b", text)
    if match:
        try:
            return date.fromisoformat(match.group(1)).isoformat()
        except ValueError:
            pass
    return None
