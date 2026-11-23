"""PDF extraction with PyMuPDF: page-level text plus font-size heading detection."""

from __future__ import annotations

import statistics
from typing import Any

import pymupdf

from app.core.exceptions import DocumentParsingError
from app.ingestion.cleaning import join_wrapped_lines, normalize_text
from app.ingestion.parsers.base import ParsedDocument, TextAssembler

_HEADING_SIZE_RATIO = 1.15
_HEADING_MAX_CHARS = 120


def _block_text_and_size(block: dict[str, Any]) -> tuple[str, float, bool]:
    lines: list[str] = []
    sizes: list[float] = []
    bold = True
    for line in block.get("lines", []):
        spans = line.get("spans", [])
        lines.append("".join(span.get("text", "") for span in spans))
        for span in spans:
            if span.get("text", "").strip():
                sizes.append(float(span.get("size", 0)))
                bold = bold and bool(int(span.get("flags", 0)) & 16)
    text = normalize_text(join_wrapped_lines("\n".join(lines)))
    return text, (max(sizes) if sizes else 0.0), bold and bool(sizes)


def parse_pdf(data: bytes) -> ParsedDocument:
    """Extract text page by page, recording page offsets and probable headings.

    Headings are detected heuristically: short blocks whose font size is clearly
    larger than the document's median body size (or bold short lines).
    """
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise DocumentParsingError("The PDF file is corrupted or unreadable") from exc
    if doc.needs_pass:
        doc.close()
        raise DocumentParsingError("Encrypted PDFs are not supported")

    try:
        pages: list[list[tuple[str, float, bool]]] = []
        all_sizes: list[float] = []
        for page in doc:
            blocks = page.get_text("dict", sort=True).get("blocks", [])
            parsed = [_block_text_and_size(b) for b in blocks if b.get("type") == 0]
            parsed = [p for p in parsed if p[0]]
            pages.append(parsed)
            all_sizes.extend(size for text, size, _ in parsed if len(text) > _HEADING_MAX_CHARS)
        body_size = statistics.median(all_sizes) if all_sizes else 0.0

        assembler = TextAssembler()
        for page_number, blocks in enumerate(pages, start=1):
            start = assembler.start_page()
            for text, size, bold in blocks:
                short = len(text) <= _HEADING_MAX_CHARS and not text.endswith((".", ",", ";"))
                larger = body_size > 0 and size >= body_size * _HEADING_SIZE_RATIO
                assembler.add_block(text, heading=short and (larger or bold))
            assembler.end_page(page_number, start)

        meta = doc.metadata or {}
        metadata = {
            k: v for k, v in {
                "author": meta.get("author"),
                "subject": meta.get("subject"),
                "creation_date": meta.get("creationDate"),
                "producer": meta.get("producer"),
            }.items() if v
        }
        metadata["page_count"] = doc.page_count
        parsed_doc = assembler.build(title=(meta.get("title") or None), metadata=metadata)
    finally:
        doc.close()

    if not parsed_doc.text.strip():
        raise DocumentParsingError(
            "No extractable text found in PDF (it may be scanned images; OCR is not enabled)"
        )
    return parsed_doc
