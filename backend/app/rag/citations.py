"""Citation extraction and verification.

LLMs can emit citation markers that point at nothing ("[7]" with five sources)
or attach correct-looking markers to unsupported claims. After generation we:

1. Parse ``[n]`` / ``[n, m]`` / ``[n][m]`` markers.
2. **Remove** markers referencing non-existent sources (never remap or invent).
3. For each answer sentence that carries citations, measure *support*: the
   fraction of its content terms found in the cited source(s). Sentences under
   ``WEAK_SUPPORT`` are counted as weakly supported.
4. Count factual sentences that carry no citation at all.
5. Emit one ``Citation`` per *referenced* source, with a supporting excerpt (the
   source sentence most similar to the citing answer sentences) and scores.

Citations are returned separately from the answer text.
"""

from __future__ import annotations

import re

from app.core.text import containment, content_terms, split_sentences
from app.rag.types import INSUFFICIENT_EVIDENCE, Citation, CitationReport, ContextSource

_MARKER_RE = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")
WEAK_SUPPORT = 0.5
_EXCERPT_CHARS = 400
_NON_FACTUAL = re.compile(r"^(based on|according to|here is|here are|in summary|sources?:)", re.I)


def _markers(text: str) -> list[int]:
    out: list[int] = []
    for match in _MARKER_RE.finditer(text):
        out.extend(int(n) for n in re.findall(r"\d+", match.group(1)))
    return out


def _strip_invalid(text: str, valid: set[int]) -> tuple[str, list[int]]:
    invalid: list[int] = []

    def repl(match: re.Match[str]) -> str:
        nums = [int(n) for n in re.findall(r"\d+", match.group(1))]
        keep = [n for n in nums if n in valid]
        invalid.extend(n for n in nums if n not in valid)
        return f"[{', '.join(str(n) for n in keep)}]" if keep else ""

    cleaned = _MARKER_RE.sub(repl, text)
    cleaned = re.sub(r"[ \t]+([.,;:])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned, invalid


def _best_excerpt(source: ContextSource, citing_sentences: list[str]) -> str:
    candidates = split_sentences(source.content) or [source.content]
    terms = [t for s in citing_sentences for t in content_terms(_MARKER_RE.sub("", s))]
    if not terms:
        return source.content[:_EXCERPT_CHARS]
    term_set = set(terms)
    best = max(candidates, key=lambda c: containment(content_terms(c), term_set) + containment(terms, set(content_terms(c))))
    return best[:_EXCERPT_CHARS]


def is_insufficient(answer: str) -> bool:
    return INSUFFICIENT_EVIDENCE.lower().rstrip(".") in answer.lower()


def verify_citations(answer: str, sources: list[ContextSource]) -> CitationReport:
    """Validate citation markers against the sources actually given to the model."""
    by_index = {s.index: s for s in sources}
    cleaned, invalid = _strip_invalid(answer, set(by_index))
    insufficient = is_insufficient(cleaned)

    supports: list[float] = []
    weak = uncited = 0
    citing: dict[int, list[str]] = {}
    support_by_source: dict[int, list[float]] = {}
    for sentence in split_sentences(cleaned):
        bare = _MARKER_RE.sub("", sentence).strip()
        terms = content_terms(bare)
        refs = [n for n in dict.fromkeys(_markers(sentence)) if n in by_index]
        if not refs:
            if len(terms) >= 4 and not _NON_FACTUAL.match(bare) and not is_insufficient(bare):
                uncited += 1
            continue
        cited_terms: set[str] = set()
        for n in refs:
            cited_terms |= set(content_terms(by_index[n].content))
            citing.setdefault(n, []).append(sentence)
        support = containment(terms, cited_terms) if terms else 1.0
        supports.append(support)
        if support < WEAK_SUPPORT:
            weak += 1
        for n in refs:
            support_by_source.setdefault(n, []).append(
                containment(terms, set(content_terms(by_index[n].content))) if terms else 1.0
            )

    citations = []
    for n in sorted(citing):
        s = by_index[n]
        vals = support_by_source.get(n, [0.0])
        citations.append(
            Citation(
                index=n,
                document_id=s.document_id,
                filename=s.filename,
                chunk_id=s.chunk_id,
                chunk_ids=s.chunk_ids,
                page_number=s.page_number,
                page_end=s.page_end,
                section=s.section,
                text=_best_excerpt(s, citing[n]),
                retrieval_score=s.fused_score if s.fused_score is not None else s.vector_score,
                rerank_score=s.rerank_score,
                vector_score=s.vector_score,
                support_score=round(sum(vals) / len(vals), 4),
            )
        )
    return CitationReport(
        answer=cleaned.strip(),
        citations=citations,
        invalid_markers=invalid,
        uncited_sentences=uncited,
        weakly_supported_sentences=weak,
        grounding_score=(sum(supports) / len(supports)) if supports else 0.0,
        insufficient_evidence=insufficient,
    )
