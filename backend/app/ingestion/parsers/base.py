"""Common parsed-document representation shared by all parsers.

Parsers produce ONE normalised text string plus offset maps for pages and
sections. Chunkers then work over the full text (so chunks may span page
boundaries naturally) and derive each chunk's page range and section from the
offset maps — this is what keeps citation metadata attached to every chunk.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class PageSpan:
    page_number: int  # 1-based
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class SectionSpan:
    title: str
    start: int


@dataclass(slots=True)
class ParsedDocument:
    """Normalised text with page and section offset maps."""

    text: str
    pages: list[PageSpan] = field(default_factory=list)
    sections: list[SectionSpan] = field(default_factory=list)
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def page_count(self) -> int | None:
        return len(self.pages) or None

    def page_at(self, offset: int) -> int | None:
        """Return the 1-based page containing character ``offset`` (None if no pages)."""
        if not self.pages:
            return None
        starts = [p.start for p in self.pages]
        idx = max(bisect.bisect_right(starts, offset) - 1, 0)
        return self.pages[idx].page_number

    def section_at(self, offset: int) -> str | None:
        """Return the most recent section heading at or before ``offset``."""
        if not self.sections:
            return None
        starts = [s.start for s in self.sections]
        idx = bisect.bisect_right(starts, offset) - 1
        return self.sections[idx].title if idx >= 0 else None


class TextAssembler:
    """Incrementally builds ``ParsedDocument`` text while recording offsets."""

    def __init__(self) -> None:
        self._parts: list[str] = []
        self._length = 0
        self.pages: list[PageSpan] = []
        self.sections: list[SectionSpan] = []

    @property
    def offset(self) -> int:
        return self._length

    def add_block(self, text: str, *, heading: bool = False) -> None:
        """Append a paragraph-level block separated by a blank line."""
        text = text.strip()
        if not text:
            return
        if self._length:
            self._append("\n\n")
        if heading:
            self.sections.append(SectionSpan(title=text[:500], start=self._length))
        self._append(text)

    def start_page(self) -> int:
        return self._length + (2 if self._length else 0)

    def end_page(self, page_number: int, start: int) -> None:
        start = min(start, self._length)
        if self._length > start:
            self.pages.append(PageSpan(page_number=page_number, start=start, end=self._length))

    def _append(self, text: str) -> None:
        self._parts.append(text)
        self._length += len(text)

    def build(self, *, title: str | None, metadata: dict[str, Any]) -> ParsedDocument:
        return ParsedDocument(
            text="".join(self._parts),
            pages=self.pages,
            sections=self.sections,
            title=title,
            metadata=metadata,
        )
