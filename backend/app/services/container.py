"""Application container: builds and owns long-lived components.

Created once in the FastAPI lifespan and injected through dependencies. Tests
build it with lightweight components (hash embeddings, lexical reranker,
fakeredis) through the same constructor, so production wiring is exercised.
"""

from __future__ import annotations

from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy import text

from app.cache.redis_cache import CacheService
from app.core.config import Settings
from app.core.logging import get_logger
from app.database.session import Database
from app.embeddings.base import EmbeddingModel
from app.embeddings.service import EmbeddingService, create_embedding_model
from app.rag.generation import ProviderRouter
from app.rag.pipeline import RAGPipeline
from app.retrieval.reranker import Reranker, create_reranker
from app.retrieval.retriever import Retriever
from app.retrieval.vector_search import VectorSearcher

logger = get_logger(__name__)


@dataclass
class AppContainer:
    settings: Settings
    db: Database
    redis: Redis | None
    cache: CacheService
    embeddings: EmbeddingService
    reranker: Reranker | None
    retriever: Retriever
    router: ProviderRouter
    pipeline: RAGPipeline
    pgvector_version: str | None = None

    @classmethod
    async def create(
        cls,
        settings: Settings,
        *,
        db: Database | None = None,
        redis: Redis | None = None,
        embedding_model: EmbeddingModel | None = None,
        reranker: Reranker | bool | None = True,
    ) -> AppContainer:
        """Wire all components. ``reranker=True`` means "build from settings"."""
        db = db or Database.from_settings(settings)
        if redis is None and settings.cache_enabled:
            redis = Redis.from_url(settings.redis_url, socket_timeout=2, socket_connect_timeout=2)
        cache = CacheService(redis, settings)

        model = embedding_model or create_embedding_model(settings)
        embeddings = EmbeddingService(model, settings, cache)
        rr = create_reranker(settings) if reranker is True else (reranker or None)

        pgvector_version = await cls._pgvector_version(db)
        iterative = pgvector_version is not None and tuple(int(p) for p in pgvector_version.split(".")[:2]) >= (0, 8)
        router = ProviderRouter(settings, embeddings, rr)
        retriever = Retriever(settings, embeddings, cache, rr, vector=VectorSearcher(iterative_scan=iterative),
                              llm_router=router)
        pipeline = RAGPipeline(settings, retriever, router, embeddings, cache)
        logger.info(
            "Container ready",
            extra={
                "embedding_model": model.name,
                "dimension": model.dimension,
                "reranker": rr.name if rr else None,
                "pgvector": pgvector_version,
                "hnsw_iterative_scan": iterative,
            },
        )
        return cls(settings, db, redis, cache, embeddings, rr, retriever, router, pipeline, pgvector_version)

    @staticmethod
    async def _pgvector_version(db: Database) -> str | None:
        try:
            async with db.engine.connect() as conn:
                return (await conn.execute(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))).scalar()
        except Exception as exc:
            logger.error("Could not query pgvector version", extra={"error": type(exc).__name__})
            return None

    async def close(self) -> None:
        if self.redis is not None:
            await self.redis.aclose()
        await self.db.dispose()
