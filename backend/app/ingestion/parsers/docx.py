"""DOCX extraction with python-docx: paragraphs, heading styles and tables."""

from __future__ import annotations

import io
import zipfile

from docx import Document as load_docx
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.core.exceptions import DocumentParsingError
from app.ingestion.cleaning import normalize_text
from app.ingestion.parsers.base import ParsedDocument, TextAssembler


def _iter_blocks(document: DocxDocument):
    """Yield paragraphs and tables in document order."""
    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def _table_to_text(table: Table) -> str:
    rows = []
    for row in table.rows:
        cells = [normalize_text(cell.text).replace("\n", " ") for cell in row.cells]
        # Merged cells repeat; drop consecutive duplicates.
        deduped = [c for i, c in enumerate(cells) if i == 0 or c != cells[i - 1]]
        rows.append(" | ".join(deduped))
    return "\n".join(r for r in rows if r.strip(" |"))


def parse_docx(data: bytes) -> ParsedDocument:
    """Extract text from a DOCX, treating Heading/Title styles as sections.

    DOCX files have no fixed pages, so chunks from DOCX carry section metadata
    but ``page_number`` is ``None`` (we never invent page numbers).
    """
    try:
        document = load_docx(io.BytesIO(data))
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise DocumentParsingError("The DOCX file is corrupted or unreadable") from exc
    except Exception as exc:
        raise DocumentParsingError("The DOCX file could not be parsed") from exc

    assembler = TextAssembler()
    for block in _iter_blocks(document):
        if isinstance(block, Paragraph):
            text = normalize_text(block.text)
            style = (block.style.name if block.style is not None else "") or ""
            is_heading = style.startswith("Heading") or style == "Title"
            assembler.add_block(text, heading=is_heading)
        else:
            assembler.add_block(_table_to_text(block))

    props = document.core_properties
    metadata = {
        k: v for k, v in {
            "author": props.author,
            "subject": props.subject,
            "created": props.created.isoformat() if props.created else None,
        }.items() if v
    }
    parsed = assembler.build(title=props.title or None, metadata=metadata)
    if not parsed.text.strip():
        raise DocumentParsingError("The DOCX file contains no extractable text")
    return parsed
