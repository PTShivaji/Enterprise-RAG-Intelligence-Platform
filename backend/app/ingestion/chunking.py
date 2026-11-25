"""Token-aware document chunking: fixed, recursive and sentence strategies.

Design
------
Every strategy reduces the text to an ordered list of *units* — character spans
``(start, end)`` that are each guaranteed to fit inside the token budget — and
then a single packer greedily merges adjacent units into chunks of at most
``chunk_size`` tokens with ``overlap`` tokens of trailing context carried into
the next chunk.

* **fixed**     units are words → classic sliding token window.
* **sentence**  units are sentences → chunks never cut a sentence in half
                (over-long sentences fall back to word units).
* **recursive** units are the *largest* structural pieces that fit:
                paragraphs → lines → sentences → words (LangChain-style).

Because units are spans over the original text, every chunk maps back to exact
character offsets, which is how page numbers and section headings are attached
(``ParsedDocument.page_at`` / ``section_at``). Token counts use a caller-supplied
counter — in production the embedding model's own tokenizer — so chunks can
never exceed what the embedding model can encode.
"""

from __future__ import annotations

import hashlib
import itertools
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from app.ingestion.parsers.base import ParsedDocument

ChunkStrategy = Literal["fixed", "recursive", "sentence"]
TokenCountFn = Callable[[str], int]

_WORD_RE = re.compile(r"\S+")
# Sentence boundary: terminal punctuation followed by whitespace and an uppercase
# letter/digit/quote, excluding common abbreviations.
_ABBREVIATIONS = {
    "e.g", "i.e", "etc", "mr", "mrs", "ms", "dr", "prof", "inc", "ltd", "co", "vs",
    "fig", "no", "approx", "dept", "st", "jr", "sr", "u.s", "a.m", "p.m",
}
_SENTENCE_END_RE = re.compile(r"[.!?][\"')\]]*\s+(?=[A-Z0-9\"'(\[])")


@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    strategy: ChunkStrategy = "recursive"
    chunk_size: int = 200
    overlap: int = 40
    respect_sections: bool = True

    def __post_init__(self) -> None:
        if self.chunk_size < 8:
            raise ValueError("chunk_size must be >= 8 tokens")
        if not 0 <= self.overlap < self.chunk_size:
            raise ValueError("overlap must be >= 0 and smaller than chunk_size")


@dataclass(slots=True)
class Chunk:
    """A chunk with exact source offsets and citation metadata."""

    index: int
    content: str
    char_start: int
    char_end: int
    token_count: int
    page_number: int | None = None
    page_end: int | None = None
    section: str | None = None
    metadata: dict = field(default_factory=dict)

    def stable_id(self, document_id: str) -> str:
        """Deterministic ID: identical document + position + content -> identical ID."""
        digest = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        return hashlib.sha256(f"{document_id}:{self.index}:{digest}".encode()).hexdigest()[:32]


Span = tuple[int, int]


# --------------------------------------------------------------------------- units
def _word_spans(text: str, start: int, end: int) -> list[Span]:
    return [(start + m.start(), start + m.end()) for m in _WORD_RE.finditer(text[start:end])]


def _sentence_spans(text: str, start: int, end: int) -> list[Span]:
    segment = text[start:end]
    spans: list[Span] = []
    cursor = 0
    for match in _SENTENCE_END_RE.finditer(segment):
        boundary = match.start() + 1
        preceding = segment[cursor:boundary].rsplit(None, 1)[-1].rstrip(".!?\"')]").lower()
        if preceding in _ABBREVIATIONS or (len(preceding) == 1 and preceding.isalpha()):
            continue  # "Dr. Smith", "J. Doe" are not sentence ends
        piece_end = match.start() + len(match.group(0).rstrip())
        if segment[cursor:piece_end].strip():
            spans.append(_strip_span(text, start + cursor, start + piece_end))
        cursor = match.end()
    if segment[cursor:].strip():
        spans.append(_strip_span(text, start + cursor, end))
    return spans


def _split_on(text: str, start: int, end: int, separator: str) -> list[Span]:
    spans: list[Span] = []
    cursor = start
    while cursor < end:
        idx = text.find(separator, cursor, end)
        if idx == -1:
            idx = end
        if text[cursor:idx].strip():
            spans.append(_strip_span(text, cursor, idx))
        cursor = idx + len(separator)
    return spans


def _strip_span(text: str, start: int, end: int) -> Span:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


class _Units:
    """Produces token-bounded units and caches token counts per span."""

    def __init__(self, text: str, count: TokenCountFn, limit: int) -> None:
        self.text = text
        self.count = count
        self.limit = limit
        self._cache: dict[Span, int] = {}

    def tokens(self, span: Span) -> int:
        if span not in self._cache:
            self._cache[span] = self.count(self.text[span[0] : span[1]])
        return self._cache[span]

    def fit_words(self, span: Span) -> list[Span]:
        """Word units; a single 'word' longer than the limit is hard-split by characters."""
        out: list[Span] = []
        for w in _word_spans(self.text, *span):
            if self.tokens(w) <= self.limit:
                out.append(w)
                continue
            step = max(1, (w[1] - w[0]) * self.limit // max(self.tokens(w), 1))
            out.extend((s, min(s + step, w[1])) for s in range(w[0], w[1], step))
        return out

    def fixed(self, span: Span) -> list[Span]:
        return self.fit_words(span)

    def sentences(self, span: Span) -> list[Span]:
        out: list[Span] = []
        for paragraph in _split_on(self.text, *span, "\n\n"):
            for sentence in _sentence_spans(self.text, *paragraph):
                out.extend([sentence] if self.tokens(sentence) <= self.limit else self.fit_words(sentence))
        return out

    def recursive(self, span: Span, level: int = 0) -> list[Span]:
        if self.tokens(span) <= self.limit:
            return [span]
        splitters: list[Callable[[Span], list[Span]]] = [
            lambda s: _split_on(self.text, *s, "\n\n"),
            lambda s: _split_on(self.text, *s, "\n"),
            lambda s: _sentence_spans(self.text, *s),
        ]
        while level < len(splitters):
            parts = splitters[level](span)
            if len(parts) > 1:
                out: list[Span] = []
                for part in parts:
                    out.extend(self.recursive(part, level + 1))
                return out
            level += 1
        return self.fit_words(span)


# --------------------------------------------------------------------------- packing
def _pack(units: list[Span], text: str, tokens: Callable[[Span], int], cfg: ChunkingConfig,
          count: TokenCountFn, heading_starts: frozenset[int] = frozenset()) -> list[Span]:
    """Greedily merge units into windows <= chunk_size with token overlap.

    Token counts are approximately additive across units; the merged window is
    re-measured exactly and shrunk if sub-word merges push it over the limit.
    A section heading is never left dangling as the last unit of a window — it is
    pushed to open the next chunk, where it provides context.
    """
    windows: list[Span] = []
    i = 0
    n = len(units)
    while i < n:
        j = i
        total = 0
        while j < n and total + tokens(units[j]) <= cfg.chunk_size:
            total += tokens(units[j])
            j += 1
        if j == i:  # single unit exactly at limit edge (should not happen) -> force progress
            j = i + 1
        # Exact re-measure; shrink while over budget.
        while j - i > 1 and count(text[units[i][0] : units[j - 1][1]]) > cfg.chunk_size:
            j -= 1
        if j < n and j - i > 1 and units[j - 1][0] in heading_starts:
            j -= 1
        windows.append((units[i][0], units[j - 1][1]))
        if j >= n:
            break
        # Overlap: step back over trailing units totalling <= overlap tokens,
        # but always advance at least one unit to guarantee termination.
        back = j
        carried = 0
        while back - 1 > i and carried + tokens(units[back - 1]) <= cfg.overlap:
            carried += tokens(units[back - 1])
            back -= 1
        i = back if cfg.overlap > 0 else j
    return windows


def _section_spans(parsed: ParsedDocument) -> list[Span]:
    """Split the text at section headings.

    A segment containing only a heading (e.g. a document title immediately followed
    by its first section heading) is folded into the next segment instead of
    becoming a heading-only chunk.
    """
    text = parsed.text
    titles = {s.start: s.title for s in parsed.sections}
    bounds = sorted({0, *titles, len(text)})
    spans: list[Span] = []
    carry_start: int | None = None
    for start, end in itertools.pairwise(bounds):
        body = text[start:end].strip()
        start_at = carry_start if carry_start is not None else start
        if start in titles and body == titles[start].strip() and end < len(text):
            carry_start = start_at  # heading-only: merge forward
            continue
        carry_start = None
        if body:
            spans.append(_strip_span(text, start_at, end))
    return spans


def chunk_document(parsed: ParsedDocument, cfg: ChunkingConfig, count_tokens: TokenCountFn) -> list[Chunk]:
    """Split a parsed document into chunks carrying page/section metadata."""
    text = parsed.text
    if not text.strip():
        return []
    units_builder = _Units(text, count_tokens, cfg.chunk_size)
    builders = {"fixed": units_builder.fixed, "sentence": units_builder.sentences, "recursive": units_builder.recursive}
    if cfg.strategy not in builders:  # pragma: no cover - guarded by typing/validation
        raise ValueError(f"Unknown chunking strategy: {cfg.strategy}")
    make_units = builders[cfg.strategy]
    heading_starts = frozenset(s.start for s in parsed.sections)

    windows: list[Span] = []
    if cfg.respect_sections and heading_starts:
        # Section-aware chunking: each section is chunked independently, so a chunk never
        # mixes two sections and overlap never leaks text across a section boundary.
        # Topically coherent chunks score far better with cross-encoders and embeddings
        # than chunks that blend unrelated sections.
        for span in _section_spans(parsed):
            windows.extend(_pack(make_units(span), text, units_builder.tokens, cfg, count_tokens, heading_starts))
    else:
        windows = _pack(make_units((0, len(text))), text, units_builder.tokens, cfg, count_tokens, heading_starts)

    chunks: list[Chunk] = []
    for start, end in windows:
        content = text[start:end].strip()
        if not content:
            continue
        chunks.append(
            Chunk(
                index=len(chunks),
                content=content,
                char_start=start,
                char_end=end,
                token_count=count_tokens(content),
                page_number=parsed.page_at(start),
                page_end=parsed.page_at(max(end - 1, start)),
                section=parsed.section_at(start) or parsed.section_at(end - 1),
                metadata={"strategy": cfg.strategy},
            )
        )
    return chunks


def build_embedding_text(chunk: Chunk, *, title: str | None, filename: str, use_header: bool) -> str:
    """Text actually embedded for a chunk.

    "Contextual chunk headers": prefixing the document title and section gives the
    embedding global context (e.g. a chunk saying "employees receive 20 days" is
    otherwise ambiguous about *what* the days are for). The stored ``content`` that
    is shown to users and the LLM stays unmodified.
    """
    if not use_header:
        return chunk.content
    header_parts = [title or filename]
    if chunk.section and chunk.section != title:
        header_parts.append(chunk.section)
    return " > ".join(header_parts) + "\n" + chunk.content
