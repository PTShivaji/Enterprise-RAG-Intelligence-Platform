"""Cross-encoder reranking.

Bi-encoders (embedding search) encode query and passage *independently*, which is
fast enough for millions of chunks but loses fine-grained interaction. A
cross-encoder reads ``[query, passage]`` jointly through full attention and
outputs a relevance logit — far more accurate, but O(candidates) model calls.
Hence the two-stage design: cheap recall of ``top_k * multiplier`` candidates,
then precise reranking of only those.
"""

from __future__ import annotations

import asyncio
import threading
import time
from abc import ABC, abstractmethod

from app.core.config import Settings
from app.core.logging import get_logger
from app.observability.metrics import RETRIEVAL_LATENCY
from app.retrieval.types import RetrievedChunk

logger = get_logger(__name__)


class Reranker(ABC):
    name: str = "none"

    @abstractmethod
    def _score(self, query: str, passages: list[str]) -> list[float]:
        """Return one relevance score per passage (higher is more relevant)."""

    async def rerank(
        self, query: str, chunks: list[RetrievedChunk], *, top_k: int, min_score: float | None = None
    ) -> list[RetrievedChunk]:
        """Score, sort and truncate candidates; drop those below ``min_score``."""
        if not chunks:
            return []
        start = time.perf_counter()
        scores = await asyncio.to_thread(self._score, query, [c.content for c in chunks])
        RETRIEVAL_LATENCY.labels(stage="rerank").observe(time.perf_counter() - start)
        for chunk, score in zip(chunks, scores, strict=True):
            chunk.rerank_score = round(float(score), 4)
        ranked = sorted(chunks, key=lambda c: c.rerank_score or 0.0, reverse=True)
        if min_score is not None:
            ranked = [c for c in ranked if (c.rerank_score or 0.0) >= min_score]
        return ranked[:top_k]


class CrossEncoderReranker(Reranker):
    def __init__(self, model_name: str, *, device: str = "cpu", max_length: int = 512) -> None:
        from sentence_transformers import CrossEncoder

        logger.info("Loading cross-encoder reranker", extra={"model": model_name})
        self._model = CrossEncoder(model_name, device=device, max_length=max_length)
        self._lock = threading.Lock()
        self.name = model_name

    def _score(self, query: str, passages: list[str]) -> list[float]:
        with self._lock:
            scores = self._model.predict(
                [(query, p) for p in passages], batch_size=32, show_progress_bar=False
            )
        return [float(s) for s in scores]


class LexicalOverlapReranker(Reranker):
    """Deterministic test double: scores by query-term containment (not used in production)."""

    name = "lexical-overlap"

    def _score(self, query: str, passages: list[str]) -> list[float]:
        from app.core.text import containment, content_terms

        q = content_terms(query)
        return [containment(q, set(content_terms(p))) * 10 - 5 for p in passages]


def create_reranker(settings: Settings) -> Reranker | None:
    """Instantiate the configured reranker, or ``None`` when disabled."""
    if not settings.reranker_enabled or settings.reranker_provider == "none":
        return None
    return CrossEncoderReranker(settings.reranker_model, device=settings.embedding_device)
