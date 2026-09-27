from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from bodybrain.ingestion import InvalidDocument, parse_document


def pdf_content(texts: list[str]) -> bytes:
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }))
    for text in texts:
        page = writer.add_blank_page(width=600, height=800)
        if text:
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
            })
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode())
            page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_exactly_100_pdf_pages_are_accepted():
    content = pdf_content(["Source note."] + [""] * 99)

    pages = parse_document(content, "synthetic.pdf")

    assert len(pages) == 100
    assert pages[0]["text"] == "Source note."
    assert pages[-1]["page"] == 100


def test_101_pdf_pages_are_rejected():
    content = pdf_content(["Source note."] + [""] * 100)

    with pytest.raises(InvalidDocument, match="100 PDF pages"):
        parse_document(content, "synthetic.pdf")


@pytest.mark.parametrize("filename", ["synthetic.txt", "synthetic.md"])
def test_text_at_150000_characters_is_accepted(filename):
    text = "a" * 150_000

    assert parse_document(text.encode(), filename) == [{"page": 1, "text": text}]


@pytest.mark.parametrize("filename", ["synthetic.txt", "synthetic.md"])
def test_text_over_150000_characters_is_rejected(filename):
    with pytest.raises(InvalidDocument, match="150,000-character limit"):
        parse_document(b"a" * 150_001, filename)


def test_pdf_at_150000_extracted_characters_across_pages_is_accepted():
    content = pdf_content(["a" * 75_000, "b" * 75_000])

    pages = parse_document(content, "synthetic.pdf")

    assert len(pages) == 2
    assert sum(len(page["text"]) for page in pages) == 150_000


def test_pdf_over_150000_extracted_characters_across_pages_is_rejected():
    content = pdf_content(["a" * 75_000, "b" * 75_001])

    with pytest.raises(InvalidDocument, match="extracted text is too large"):
        parse_document(content, "synthetic.pdf")
