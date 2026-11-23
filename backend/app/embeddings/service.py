"""Embedding service: model lifecycle, batching, caching and dimension guarding."""

from __future__ import annotations

import asyncio
import time

import numpy as np

from app.cache.redis_cache import CacheService
from app.core.config import Settings
from app.core.exceptions import EmbeddingDimensionError
from app.core.logging import get_logger
from app.embeddings.base import EmbeddingModel
from app.observability.metrics import EMBEDDING_LATENCY

logger = get_logger(__name__)


def create_embedding_model(settings: Settings) -> EmbeddingModel:
    """Instantiate the configured embedding backend."""
    if settings.embedding_provider == "hash":
        from app.embeddings.hash_embedding import HashEmbedding

        return HashEmbedding(settings.embedding_dimension)
    from app.embeddings.sentence_transformer import SentenceTransformerEmbedding

    return SentenceTransformerEmbedding(settings.embedding_model, device=settings.embedding_device)


class EmbeddingService:
    """Async facade over an ``EmbeddingModel``.

    * Validates on start-up that the model's dimension equals the pgvector column
      dimension, so vectors of different sizes can never be mixed in one index.
    * Runs encoding in a worker thread so the event loop is never blocked.
    * Caches *query* embeddings in Redis (content-addressed by model + text).
    """

    def __init__(self, model: EmbeddingModel, settings: Settings, cache: CacheService | None = None) -> None:
        if model.dimension != settings.embedding_dimension:
            raise EmbeddingDimensionError(
                f"Embedding model '{model.name}' has dimension {model.dimension} but the "
                f"database vector column is {settings.embedding_dimension}. Set "
                "EMBEDDING_DIMENSION correctly, migrate, and re-index all documents."
            )
        if settings.chunk_size_tokens > model.max_seq_length - 2:
            raise ValueError(
                f"CHUNK_SIZE_TOKENS={settings.chunk_size_tokens} exceeds the embedding model's "
                f"max_seq_length ({model.max_seq_length}); chunks would be truncated."
            )
        self.model = model
        self.settings = settings
        self.cache = cache

    @property
    def model_name(self) -> str:
        return self.model.name

    @property
    def dimension(self) -> int:
        return self.model.dimension

    def count_tokens(self, text: str) -> int:
        return self.model.count_tokens(text)

    async def embed_documents(self, texts: list[str]) -> np.ndarray:
        """Batch-embed document chunks (not cached: each chunk is embedded once)."""
        start = time.perf_counter()
        vectors = await asyncio.to_thread(
            self.model.embed, texts, batch_size=self.settings.embedding_batch_size, is_query=False
        )
        EMBEDDING_LATENCY.labels(kind="documents").observe(time.perf_counter() - start)
        return vectors

    async def embed_query(self, text: str) -> tuple[np.ndarray, bool]:
        """Embed a single query. Returns ``(vector, cache_hit)``."""
        if self.cache is not None:
            cached = await self.cache.get_embedding(self.model.name, text)
            if cached is not None and cached.shape == (self.dimension,):
                return cached, True
        start = time.perf_counter()
        vector = (await asyncio.to_thread(self.model.embed, [text], batch_size=1, is_query=True))[0]
        EMBEDDING_LATENCY.labels(kind="query").observe(time.perf_counter() - start)
        if self.cache is not None:
            await self.cache.set_embedding(self.model.name, text, vector)
        return vector, False

    async def embed_queries(self, texts: list[str]) -> np.ndarray:
        """Embed several queries (used for multi-query expansion and evaluation)."""
        return await asyncio.to_thread(self.model.embed, texts, batch_size=32, is_query=True)
