import asyncio

from finagent.content_automation import (
    _extract_document_bytes_docling_primary,
    _extract_source_url_markdown,
)


def test_docling_primary_for_document_bytes(monkeypatch):
    monkeypatch.setattr(
        "finagent.content_automation._docling_extract_markdown",
        lambda file_bytes, filename: ("docling extracted content", None),
    )
    monkeypatch.setattr(
        "finagent.content_automation._pymupdf_extract_text",
        lambda file_bytes: ("pymupdf content", None),
    )

    text, parser_used, extraction_error = _extract_document_bytes_docling_primary(
        b"%PDF-1.4 sample",
        "sample.pdf",
        "application/pdf",
    )

    assert text == "docling extracted content"
    assert parser_used == "docling_markdown"
    assert extraction_error is None


def test_pymupdf_fallback_when_docling_is_empty(monkeypatch):
    monkeypatch.setattr(
        "finagent.content_automation._docling_extract_markdown",
        lambda file_bytes, filename: ("", "docling_empty_markdown"),
    )
    monkeypatch.setattr(
        "finagent.content_automation._pymupdf_extract_text",
        lambda file_bytes: ("pymupdf extracted content", None),
    )

    text, parser_used, extraction_error = _extract_document_bytes_docling_primary(
        b"%PDF-1.4 sample",
        "sample.pdf",
        "application/pdf",
    )

    assert text == "pymupdf extracted content"
    assert parser_used == "pymupdf"
    assert extraction_error == "docling_empty_markdown"


def test_source_url_prefers_document_extraction(monkeypatch):
    async def _fake_document_extract(source_url: str):
        return "document block", [{"title": "doc", "url": source_url}]

    monkeypatch.setattr(
        "finagent.content_automation._extract_source_document_markdown",
        _fake_document_extract,
    )

    text, sources = asyncio.run(_extract_source_url_markdown("https://example.com/report.pdf"))

    assert text == "document block"
    assert sources == [{"title": "doc", "url": "https://example.com/report.pdf"}]
