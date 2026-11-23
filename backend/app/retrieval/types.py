"""Retrieval data structures passed between retrieval, reranking and context building."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

SearchMode = Literal["vector", "keyword", "hybrid"]
QueryExpansion = Literal["none", "prf", "multi_query"]


@dataclass(slots=True)
class RetrievedChunk:
    """A candidate chunk with every score it accumulated through the pipeline."""

    chunk_id: str
    document_id: str
    filename: str
    file_type: str
    content: str
    chunk_index: int
    char_start: int
    char_end: int
    page_number: int | None = None
    page_end: int | None = None
    section: str | None = None
    vector_score: float | None = None  # cosine similarity in [-1, 1]
    keyword_score: float | None = None  # ts_rank (length-normalised)
    vector_rank: int | None = None
    keyword_rank: int | None = None
    fused_score: float | None = None  # RRF score
    rerank_score: float | None = None  # cross-encoder logit
    final_rank: int | None = None

    @property
    def score(self) -> float:
        """Best available relevance score, most-informed stage first."""
        for value in (self.rerank_score, self.fused_score, self.vector_score, self.keyword_score):
            if value is not None:
                return value
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RetrievedChunk:
        return cls(**data)


@dataclass(slots=True)
class SearchFilters:
    """Metadata filters. All filters are AND-ed and always combined with owner isolation."""

    document_ids: list[uuid.UUID] | None = None
    file_types: list[str] | None = None
    filename_contains: str | None = None
    page_from: int | None = None
    page_to: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_ids": sorted(str(d) for d in self.document_ids) if self.document_ids else None,
            "file_types": sorted(self.file_types) if self.file_types else None,
            "filename_contains": self.filename_contains,
            "page_from": self.page_from,
            "page_to": self.page_to,
        }


@dataclass(slots=True)
class RetrievalOptions:
    top_k: int = 5
    mode: SearchMode = "hybrid"
    rerank: bool = True
    candidate_multiplier: int = 4
    similarity_threshold: float = 0.25
    rerank_min_score: float = -6.0
    query_expansion: QueryExpansion = "prf"
    filters: SearchFilters = field(default_factory=SearchFilters)
    use_cache: bool = True

    @property
    def candidate_k(self) -> int:
        return self.top_k * self.candidate_multiplier if self.rerank else self.top_k

    def cache_params(self, query: str, model: str, reranker: str) -> dict[str, Any]:
        return {
            "q": query,
            "top_k": self.top_k,
            "mode": self.mode,
            "rerank": self.rerank,
            "mult": self.candidate_multiplier,
            "thr": self.similarity_threshold,
            "rmin": self.rerank_min_score,
            "exp": self.query_expansion,
            "filters": self.filters.to_dict(),
            "model": model,
            "reranker": reranker,
        }


@dataclass(slots=True)
class RetrievalResult:
    query: str
    chunks: list[RetrievedChunk]
    timings_ms: dict[str, float] = field(default_factory=dict)
    cache_hit: bool = False
    embedding_cache_hit: bool = False
    expanded_terms: list[str] = field(default_factory=list)
    query_variants: list[str] = field(default_factory=list)
    stages: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    candidates_considered: int = 0
