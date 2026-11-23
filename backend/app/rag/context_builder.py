"""Context engineering: turn ranked chunks into a token-budgeted, citable context.

Steps (in order):

1. **De-duplicate** — exact (normalised text hash) and near-duplicates (Jaccard
   over word 3-shingles >= 0.8). Re-uploaded or boilerplate-heavy corpora
   otherwise waste budget on repeated text.
2. **Merge adjacent chunks** — two selected chunks from the same document whose
   character spans overlap/touch are stitched into one source, removing the
   duplicated overlap text and giving the LLM a coherent passage.
3. **Budget** — sources are added in rank order until ``max_tokens`` is reached.
4. **Query-aware compression** — a source that does not fit (or exceeds a per-
   source cap) is reduced to its most query-relevant sentences, kept in original
   order with "..." gap markers, instead of being dropped or blindly truncated.
5. **Injection screening** — instruction-like text is flagged (not removed; the
   prompt treats all sources as untrusted data either way).

Every source keeps its document id, chunk ids, filename, pages and section, so
citations survive all transformations.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.core.text import content_terms, jaccard, shingles, split_sentences
from app.core.tokens import TokenCounter, get_token_counter
from app.rag.types import BuiltContext, ContextSource
from app.retrieval.types import RetrievedChunk

NEAR_DUPLICATE_THRESHOLD = 0.8
MIN_COMPRESSED_TOKENS = 40
_INJECTION_PATTERNS = re.compile(
    r"(ignore (all |any )?(previous|prior|above) (instructions|prompts)|disregard (the )?(system|previous)"
    r"|you are now|system prompt|reveal (your|the) (instructions|prompt)|act as (an? )?(admin|developer))",
    re.IGNORECASE,
)


@dataclass(slots=True)
class _Group:
    chunks: list[RetrievedChunk]
    content: str
    start: int
    end: int


def _norm_hash(text: str) -> str:
    return hashlib.sha1(re.sub(r"\s+", " ", text.lower()).strip().encode(), usedforsecurity=False).hexdigest()


def compress_to_budget(text: str, query: str, max_tokens: int, counter: TokenCounter) -> str:
    """Keep the most query-relevant sentences (original order) within ``max_tokens``."""
    sentences = split_sentences(text)
    if len(sentences) <= 1:
        return counter.truncate(text, max_tokens)
    q_terms = set(content_terms(query))
    scored = []
    for pos, sentence in enumerate(sentences):
        terms = content_terms(sentence)
        overlap = sum(1 for t in terms if t in q_terms)
        # Normalise by sqrt(length) so long sentences don't win just by size;
        # slight positional prior: earlier sentences often state the topic.
        score = overlap / (len(terms) ** 0.5 if terms else 1.0) + 0.05 / (pos + 1)
        scored.append((score, pos, sentence))
    kept: list[tuple[int, str]] = []
    used = 0
    for _score, pos, sentence in sorted(scored, key=lambda x: (-x[0], x[1])):
        tokens = counter.count(sentence) + 1
        if used + tokens > max_tokens:
            continue
        kept.append((pos, sentence))
        used += tokens
    if not kept:
        return counter.truncate(text, max_tokens)
    kept.sort()
    out: list[str] = []
    prev = -1
    for pos, sentence in kept:
        if prev != -1 and pos != prev + 1:
            out.append("...")
        out.append(sentence)
        prev = pos
    return " ".join(out)


class ContextBuilder:
    def __init__(self, max_tokens: int = 2500, *, per_source_max_tokens: int | None = None,
                 counter: TokenCounter | None = None) -> None:
        self.max_tokens = max_tokens
        self.per_source_max_tokens = per_source_max_tokens or max(200, max_tokens // 2)
        self.counter = counter or get_token_counter()

    # ----------------------------------------------------------- dedupe & merge
    @staticmethod
    def deduplicate(chunks: list[RetrievedChunk]) -> tuple[list[RetrievedChunk], int]:
        kept: list[RetrievedChunk] = []
        seen_hashes: set[str] = set()
        kept_shingles: list[set[str]] = []
        dropped = 0
        for chunk in chunks:
            h = _norm_hash(chunk.content)
            sh = shingles(chunk.content)
            if h in seen_hashes or any(jaccard(sh, other) >= NEAR_DUPLICATE_THRESHOLD for other in kept_shingles):
                dropped += 1
                continue
            seen_hashes.add(h)
            kept_shingles.append(sh)
            kept.append(chunk)
        return kept, dropped

    @staticmethod
    def merge_adjacent(chunks: list[RetrievedChunk]) -> tuple[list[_Group], int]:
        """Merge chunks of the same document whose spans overlap or touch.

        Groups are emitted in the rank order of their best chunk. Merging is only
        performed when the overlapping text verifiably matches, so no content is
        ever fabricated or lost.
        """
        groups: list[_Group] = []
        merged = 0
        for chunk in chunks:
            target = None
            for g in groups:
                if g.chunks[0].document_id != chunk.document_id:
                    continue
                if chunk.char_start <= g.end and chunk.char_end >= g.start:
                    target = g
                    break
            if target is None:
                groups.append(_Group([chunk], chunk.content, chunk.char_start, chunk.char_end))
                continue
            combined = ContextBuilder._stitch(target, chunk)
            if combined is None:
                groups.append(_Group([chunk], chunk.content, chunk.char_start, chunk.char_end))
                continue
            target.content, target.start, target.end = combined
            target.chunks.append(chunk)
            merged += 1
        return groups, merged

    @staticmethod
    def _stitch(group: _Group, chunk: RetrievedChunk) -> tuple[str, int, int] | None:
        # Invariant from the chunker: content == document_text[char_start:char_end].
        if chunk.char_start >= group.start and chunk.char_end <= group.end:
            return group.content, group.start, group.end  # chunk fully contained
        if chunk.char_start <= group.start and chunk.char_end >= group.end:
            return chunk.content, chunk.char_start, chunk.char_end  # chunk contains group
        if chunk.char_start > group.start:
            left, l_start, right, r_start, r_end = group.content, group.start, chunk.content, chunk.char_start, chunk.char_end
        else:
            left, l_start, right, r_start, r_end = chunk.content, chunk.char_start, group.content, group.start, group.end
        offset = r_start - l_start
        if offset > len(left):
            return None
        overlap = left[offset:]
        if not right.startswith(overlap):
            return None  # offsets disagree with text: refuse to merge rather than corrupt
        return left + right[len(overlap):], l_start, r_end

    # ------------------------------------------------------------------- build
    def build(self, chunks: list[RetrievedChunk], query: str) -> BuiltContext:
        deduped, dropped = self.deduplicate(chunks)
        groups, merged = self.merge_adjacent(deduped)
        sources: list[ContextSource] = []
        used = 0
        compressed = truncated = 0
        for group in groups:
            remaining = self.max_tokens - used
            if remaining < MIN_COMPRESSED_TOKENS:
                truncated += 1
                continue
            content = group.content
            tokens = self.counter.count(content)
            was_compressed = False
            cap = min(self.per_source_max_tokens, remaining)
            if tokens > cap:
                content = compress_to_budget(content, query, cap, self.counter)
                tokens = self.counter.count(content)
                was_compressed = True
                compressed += 1
            primary = group.chunks[0]
            pages = [c.page_number for c in group.chunks if c.page_number is not None]
            page_ends = [c.page_end or c.page_number for c in group.chunks if c.page_number is not None]
            sources.append(
                ContextSource(
                    index=len(sources) + 1,
                    chunk_id=primary.chunk_id,
                    chunk_ids=[c.chunk_id for c in group.chunks],
                    document_id=primary.document_id,
                    filename=primary.filename,
                    content=content,
                    page_number=min(pages) if pages else None,
                    page_end=max(page_ends) if page_ends else None,
                    section=primary.section,
                    token_count=tokens,
                    vector_score=primary.vector_score,
                    keyword_score=primary.keyword_score,
                    rerank_score=primary.rerank_score,
                    fused_score=primary.fused_score,
                    compressed=was_compressed,
                    suspicious=bool(_INJECTION_PATTERNS.search(content)),
                )
            )
            used += tokens
        return BuiltContext(
            sources=sources,
            total_tokens=used,
            budget_tokens=self.max_tokens,
            dropped_duplicates=dropped,
            merged_adjacent=merged,
            compressed_sources=compressed,
            truncated_sources=truncated,
        )
