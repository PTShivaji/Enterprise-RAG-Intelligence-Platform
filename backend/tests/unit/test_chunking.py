"""Chunking strategies: token limits, overlap, offsets, metadata and stability."""

from __future__ import annotations

import itertools
import re

import pytest

from app.ingestion.chunking import ChunkingConfig, build_embedding_text, chunk_document
from app.ingestion.parsers import parse_document
from app.ingestion.parsers.base import PageSpan, ParsedDocument
from tests.factories import LEAVE_POLICY_TXT, make_pdf


def count_words(text: str) -> int:
    return len(re.findall(r"\S+", text))


LONG_TEXT = "\n\n".join(
    " ".join(f"Sentence {p}-{s} talks about topic {p} in detail." for s in range(12)) for p in range(8)
)


@pytest.mark.parametrize("strategy", ["fixed", "recursive", "sentence"])
def test_chunks_respect_token_limit_and_offsets(strategy: str) -> None:
    parsed = ParsedDocument(text=LONG_TEXT)
    cfg = ChunkingConfig(strategy=strategy, chunk_size=60, overlap=10)
    chunks = chunk_document(parsed, cfg, count_words)
    assert len(chunks) > 5
    for c in chunks:
        assert c.token_count <= 60
        assert c.content == LONG_TEXT[c.char_start : c.char_end]  # exact source offsets
    # Full coverage: every word of the document appears in some chunk.
    covered = set()
    for c in chunks:
        covered.update(range(c.char_start, c.char_end))
    words = [m.start() for m in re.finditer(r"\S+", LONG_TEXT)]
    assert all(w in covered for w in words)


@pytest.mark.parametrize("strategy", ["fixed", "recursive", "sentence"])
def test_overlap_carries_context_forward(strategy: str) -> None:
    chunks = chunk_document(ParsedDocument(text=LONG_TEXT), ChunkingConfig(strategy, 60, 20), count_words)
    overlaps = sum(1 for a, b in itertools.pairwise(chunks) if b.char_start < a.char_end)
    assert overlaps >= len(chunks) // 2


def test_no_overlap_means_disjoint_chunks() -> None:
    chunks = chunk_document(ParsedDocument(text=LONG_TEXT), ChunkingConfig("fixed", 50, 0), count_words)
    for a, b in itertools.pairwise(chunks):
        assert b.char_start >= a.char_end


def test_sentence_strategy_never_cuts_sentences() -> None:
    chunks = chunk_document(ParsedDocument(text=LONG_TEXT), ChunkingConfig("sentence", 40, 0), count_words)
    for c in chunks:
        assert c.content.startswith("Sentence")
        assert c.content.endswith(".")


def test_recursive_prefers_paragraph_boundaries() -> None:
    text = "\n\n".join(["Alpha paragraph has five words.", "Beta paragraph has five words.", "Gamma paragraph is here now."])
    chunks = chunk_document(ParsedDocument(text=text), ChunkingConfig("recursive", 11, 0), count_words)
    assert [c.content for c in chunks] == [
        "Alpha paragraph has five words.\n\nBeta paragraph has five words.",
        "Gamma paragraph is here now.",
    ]


def test_page_metadata_is_attached_from_offsets() -> None:
    parsed = parse_document("pdf", make_pdf())
    chunks = chunk_document(parsed, ChunkingConfig("recursive", 30, 0), count_words)
    by_text = {c.content: c for c in chunks}
    torque = next(c for t, c in by_text.items() if "2.5 Nm" in t)
    assert torque.page_number == 2
    disconnect = next(c for t, c in by_text.items() if "DC disconnect" in t)
    assert disconnect.page_number == 1


def test_page_range_for_chunk_spanning_pages() -> None:
    text = "aaa bbb ccc ddd eee fff"
    parsed = ParsedDocument(text=text, pages=[PageSpan(1, 0, 11), PageSpan(2, 12, len(text))])
    (chunk,) = chunk_document(parsed, ChunkingConfig("fixed", 100, 0), count_words)
    assert (chunk.page_number, chunk.page_end) == (1, 2)


def test_sections_and_headings_open_chunks() -> None:
    parsed = parse_document("txt", LEAVE_POLICY_TXT.encode())
    chunks = chunk_document(parsed, ChunkingConfig("recursive", 45, 0), count_words)
    sick = next(c for c in chunks if "sick leave per year" in c.content)
    assert sick.section == "Sick Leave"
    # No chunk ends with a dangling heading line.
    headings = {s.title for s in parsed.sections}
    for c in chunks[:-1]:
        assert c.content.split("\n\n")[-1] not in headings or len(c.content.split("\n\n")) == 1


def test_section_aware_chunks_never_mix_sections() -> None:
    parsed = parse_document("txt", LEAVE_POLICY_TXT.encode())
    # Large budget: without section awareness everything would fit in one chunk.
    chunks = chunk_document(parsed, ChunkingConfig("recursive", 500, 50), count_words)
    starts = sorted(s.start for s in parsed.sections)
    titles = {s.start: s.title for s in parsed.sections}
    for c in chunks:
        inner = [s for s in starts if c.char_start < s < c.char_end]
        # Only allowed crossing: a heading-only prefix (document title) folded into the first section.
        for s in inner:
            prefix = parsed.text[c.char_start:s].strip()
            assert prefix in titles.values(), f"chunk crosses a section boundary: {c.content[:60]!r}"
    assert chunks[0].content.startswith("Leave Policy\n\nAnnual Leave")  # title folded into first section
    assert [c.section for c in chunks] == ["Leave Policy", "Carry Over", "Sick Leave"]
    mixed = chunk_document(parsed, ChunkingConfig("recursive", 500, 50, respect_sections=False), count_words)
    assert len(mixed) == 1


def test_stable_ids_are_deterministic_and_unique() -> None:
    parsed = ParsedDocument(text=LONG_TEXT)
    a = chunk_document(parsed, ChunkingConfig("recursive", 60, 10), count_words)
    b = chunk_document(parsed, ChunkingConfig("recursive", 60, 10), count_words)
    ids_a = [c.stable_id("doc-1") for c in a]
    assert ids_a == [c.stable_id("doc-1") for c in b]
    assert len(set(ids_a)) == len(ids_a)
    assert ids_a != [c.stable_id("doc-2") for c in a]


def test_huge_single_token_is_hard_split() -> None:
    text = "x" * 5000
    chunks = chunk_document(ParsedDocument(text=text), ChunkingConfig("recursive", 50, 0), lambda s: len(s) // 10 + 1)
    assert all(c.token_count <= 50 for c in chunks)
    assert "".join(c.content for c in chunks) == text


def test_invalid_config_rejected() -> None:
    with pytest.raises(ValueError):
        ChunkingConfig("fixed", 50, 50)
    with pytest.raises(ValueError):
        ChunkingConfig("fixed", 4, 0)


def test_contextual_header_only_affects_embedding_text() -> None:
    parsed = parse_document("txt", LEAVE_POLICY_TXT.encode())
    chunk = chunk_document(parsed, ChunkingConfig("recursive", 45, 0), count_words)[-1]
    text = build_embedding_text(chunk, title="Leave Policy", filename="leave.txt", use_header=True)
    assert text.startswith("Leave Policy > Sick Leave\n")
    assert text.endswith(chunk.content)
    assert build_embedding_text(chunk, title=None, filename="f.txt", use_header=False) == chunk.content
