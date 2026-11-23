"""Data structures for context construction, generation and citations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

INSUFFICIENT_EVIDENCE = "I could not find sufficient evidence in your documents to answer this question."


@dataclass(slots=True)
class ContextSource:
    """One numbered source block placed in the prompt (may merge adjacent chunks)."""

    index: int  # 1-based citation number used as [n] in answers
    chunk_id: str  # primary (highest-ranked) chunk
    chunk_ids: list[str]
    document_id: str
    filename: str
    content: str
    page_number: int | None
    page_end: int | None
    section: str | None
    token_count: int
    vector_score: float | None = None
    keyword_score: float | None = None
    rerank_score: float | None = None
    fused_score: float | None = None
    compressed: bool = False
    suspicious: bool = False  # contains instruction-like text (possible prompt injection)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BuiltContext:
    sources: list[ContextSource]
    total_tokens: int
    budget_tokens: int
    dropped_duplicates: int = 0
    merged_adjacent: int = 0
    compressed_sources: int = 0
    truncated_sources: int = 0


@dataclass(slots=True)
class GenerationRequest:
    question: str
    sources: list[ContextSource]
    messages: list[dict[str, str]]
    model: str
    temperature: float = 0.1
    max_tokens: int = 700


@dataclass(slots=True)
class GenerationResult:
    text: str
    model: str
    provider: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None
    latency_ms: float = 0.0


@dataclass(slots=True)
class StreamDelta:
    """Either a text delta or (when ``final`` is set) the completed result."""

    text: str = ""
    final: GenerationResult | None = None


@dataclass(slots=True)
class Citation:
    index: int
    document_id: str
    filename: str
    chunk_id: str
    chunk_ids: list[str]
    page_number: int | None
    page_end: int | None
    section: str | None
    text: str  # supporting excerpt from the source
    retrieval_score: float | None
    rerank_score: float | None
    vector_score: float | None
    support_score: float  # lexical support of the citing sentences by this source

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CitationReport:
    answer: str  # answer text with invalid citation markers removed
    citations: list[Citation]
    invalid_markers: list[int] = field(default_factory=list)
    uncited_sentences: int = 0
    weakly_supported_sentences: int = 0
    grounding_score: float = 0.0  # mean support of cited sentences in [0, 1]
    insufficient_evidence: bool = False

    def verification(self) -> dict[str, Any]:
        return {
            "invalid_markers_removed": self.invalid_markers,
            "uncited_sentences": self.uncited_sentences,
            "weakly_supported_sentences": self.weakly_supported_sentences,
            "grounding_score": round(self.grounding_score, 4),
            "insufficient_evidence": self.insufficient_evidence,
            "citation_count": len(self.citations),
        }
