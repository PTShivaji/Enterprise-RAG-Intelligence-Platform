"""Plain-text extraction with encoding detection and heading heuristics."""

from __future__ import annotations

import re

from app.core.exceptions import DocumentParsingError
from app.ingestion.cleaning import join_wrapped_lines, normalize_text
from app.ingestion.parsers.base import ParsedDocument, TextAssembler

_MD_HEADING = re.compile(r"^#{1,6}\s+(.+)$")
_NUMBERED_HEADING = re.compile(r"^(?:section\s+)?\d+(?:\.\d+)*[.)]?\s+[A-Z][^.!?]{0,80}$", re.I)


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            text = data.decode(encoding)
            if encoding == "utf-16" and data[:2] not in (b"\xff\xfe", b"\xfe\xff"):
                continue
            return text
        except UnicodeDecodeError:
            continue
    if b"\x00" in data[:4096]:
        raise DocumentParsingError("The file appears to be binary, not text")
    return data.decode("latin-1")


def _heading(paragraph: str) -> str | None:
    if "\n" in paragraph or len(paragraph) > 100:
        return None
    if m := _MD_HEADING.match(paragraph):
        return m.group(1).strip()
    if _NUMBERED_HEADING.match(paragraph):
        return paragraph
    letters = [c for c in paragraph if c.isalpha()]
    if len(letters) >= 4 and all(c.isupper() for c in letters) and not paragraph.endswith("."):
        return paragraph
    return None


def parse_txt(data: bytes) -> ParsedDocument:
    """Extract text from TXT/Markdown-like files; detect headings by convention."""
    text = normalize_text(_decode(data))
    if not text:
        raise DocumentParsingError("The text file is empty")
    assembler = TextAssembler()
    for paragraph in text.split("\n\n"):
        heading = _heading(paragraph.strip())
        if heading is not None:
            assembler.add_block(heading, heading=True)
        else:
            # Keep list structure (lines starting with bullets) but join wrapped prose.
            lines = paragraph.split("\n")
            is_list = sum(1 for ln in lines if re.match(r"^\s*([-*•]|\d+[.)])\s", ln)) >= 2
            assembler.add_block(paragraph if is_list else join_wrapped_lines(paragraph))
    first_heading = assembler.sections[0].title if assembler.sections else None
    return assembler.build(title=first_heading, metadata={})
