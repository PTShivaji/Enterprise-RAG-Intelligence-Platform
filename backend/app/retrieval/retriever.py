"""Retrieval orchestrator: query -> candidates -> fusion -> threshold -> rerank -> top-K.

Pipeline (hybrid mode, defaults):

  1. preprocess query
  2. embed query                    (Redis embedding cache)
  3. vector search,  K' = top_k * candidate_multiplier
  4. [multi_query]  LLM paraphrases -> extra vector searches -> RRF
  5. [prf]          expansion terms mined from top vector hits
  6. keyword search (expanded query), K'
  7. RRF fusion of vector + keyword lists
  8. exact cosine for keyword-only hits, then similarity threshold
  9. cross-encoder rerank -> drop below rerank_min_score -> top_k

The final list is cached per (user, corpus version, query, options).
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_cache import CacheService
from app.core.config import Settings
from app.core.logging import get_logger
from app.embeddings.service import EmbeddingService
from app.observability.metrics import RETRIEVAL_LATENCY
from app.retrieval.hybrid_search import reciprocal_rank_fusion
from app.retrieval.keyword_search import KeywordSearcher
from app.retrieval.query_processing import (
    MULTI_QUERY_PROMPT,
    parse_query_variants,
    preprocess_query,
    prf_expansion_terms,
)
from app.retrieval.reranker import Reranker
from app.retrieval.types import RetrievalOptions, RetrievalResult, RetrievedChunk
from app.retrieval.vector_search import VectorSearcher

logger = get_logger(__name__)


def _stage_view(chunks: list[RetrievedChunk]) -> list[dict[str, Any]]:
    view = []
    for c in chunks:
        d = c.to_dict()
        d["content"] = c.content[:300]
        view.append(d)
    return view


class Retriever:
    def __init__(
        self,
        settings: Settings,
        embeddings: EmbeddingService,
        cache: CacheService,
        reranker: Reranker | None,
        vector: VectorSearcher | None = None,
        keyword: KeywordSearcher | None = None,
        llm_router: Any | None = None,
    ) -> None:
        self.settings = settings
        self.embeddings = embeddings
        self.cache = cache
        self.reranker = reranker
        self.vector = vector or VectorSearcher()
        self.keyword = keyword or KeywordSearcher()
        self.llm_router = llm_router

    def default_options(self, **overrides: Any) -> RetrievalOptions:
        s = self.settings
        opts = RetrievalOptions(
            top_k=s.retrieval_top_k,
            mode=s.search_mode,
            rerank=s.reranker_enabled and self.reranker is not None,
            candidate_multiplier=s.retrieval_candidate_multiplier,
            similarity_threshold=s.similarity_threshold,
            rerank_min_score=s.rerank_min_score,
            query_expansion=s.query_expansion,
        )
        for key, value in overrides.items():
            if value is not None:
                setattr(opts, key, value)
        return opts

    async def _query_variants(self, query: str, llm_model: str | None) -> list[str]:
        if self.llm_router is None or llm_model is None or self.llm_router.is_local(llm_model):
            logger.info("multi_query expansion needs a remote LLM; falling back to PRF")
            return []
        try:
            text = await self.llm_router.for_model(llm_model).complete_text(
                MULTI_QUERY_PROMPT.format(n=3, question=query), model=llm_model, max_tokens=150
            )
            return parse_query_variants(text, query, 3)
        except Exception as exc:  # expansion is an optimisation; degrade, but log it
            logger.warning("Query variant generation failed", extra={"error": type(exc).__name__})
            return []

    async def retrieve(
        self,
        session: AsyncSession,
        *,
        owner_id: uuid.UUID,
        query: str,
        options: RetrievalOptions,
        llm_model: str | None = None,
        debug: bool = False,
    ) -> RetrievalResult:
        total_start = time.perf_counter()
        q = preprocess_query(query)
        result = RetrievalResult(query=q, chunks=[])
        if not q:
            return result
        use_rerank = options.rerank and self.reranker is not None
        reranker_name = self.reranker.name if use_rerank and self.reranker else "none"
        params = options.cache_params(q, self.embeddings.model_name, reranker_name)

        if options.use_cache and not debug:
            cached = await self.cache.get_retrieval(owner_id, params)
            if cached is not None:
                result.chunks = [RetrievedChunk.from_dict(c) for c in cached["chunks"]]
                result.expanded_terms = cached.get("expanded_terms", [])
                result.query_variants = cached.get("query_variants", [])
                result.cache_hit = True
                result.timings_ms["total"] = round((time.perf_counter() - total_start) * 1000, 2)
                return result

        timings: dict[str, float] = {}

        def mark(stage: str, start: float) -> None:
            elapsed = time.perf_counter() - start
            timings[stage] = round(elapsed * 1000, 2)
            RETRIEVAL_LATENCY.labels(stage=stage).observe(elapsed)

        t = time.perf_counter()
        q_vec, result.embedding_cache_hit = await self.embeddings.embed_query(q)
        mark("embed", t)

        n = options.top_k * options.candidate_multiplier if use_rerank else options.top_k
        # Hybrid fusion benefits from a deeper pool even without reranking.
        pool = max(n, options.top_k * 2) if options.mode == "hybrid" else n
        model = self.embeddings.model_name
        vector_hits: list[RetrievedChunk] = []
        keyword_hits: list[RetrievedChunk] = []

        if options.mode in ("vector", "hybrid"):
            t = time.perf_counter()
            vector_hits = await self.vector.search(
                session, owner_id=owner_id, query_vector=q_vec, embedding_model=model, k=pool, filters=options.filters
            )
            mark("vector_search", t)
            if options.query_expansion == "multi_query":
                t = time.perf_counter()
                variants = await self._query_variants(q, llm_model)
                if variants:
                    result.query_variants = variants
                    variant_vecs = await self.embeddings.embed_queries(variants)
                    lists = [vector_hits]
                    for vec in variant_vecs:
                        lists.append(await self.vector.search(
                            session, owner_id=owner_id, query_vector=vec, embedding_model=model,
                            k=pool, filters=options.filters,
                        ))
                    vector_hits = reciprocal_rank_fusion(lists, k=self.settings.rrf_k, limit=pool)
                    for rank, c in enumerate(vector_hits, start=1):
                        c.vector_rank = rank
                mark("multi_query", t)

        if options.mode in ("keyword", "hybrid"):
            keyword_query = q
            # PRF also serves as the fallback when multi_query produced no variants.
            use_prf = options.query_expansion in ("prf", "multi_query") and not result.query_variants
            if options.mode == "hybrid" and use_prf:
                result.expanded_terms = prf_expansion_terms(q, vector_hits)
                if result.expanded_terms:
                    keyword_query = f"{q} {' '.join(result.expanded_terms)}"
            t = time.perf_counter()
            keyword_hits = await self.keyword.search(
                session, owner_id=owner_id, query=keyword_query, embedding_model=model, k=pool, filters=options.filters
            )
            mark("keyword_search", t)

        if options.mode == "hybrid":
            t = time.perf_counter()
            candidates = reciprocal_rank_fusion([vector_hits, keyword_hits], k=self.settings.rrf_k, limit=n)
            mark("fusion", t)
        elif options.mode == "vector":
            candidates = vector_hits[:n]
        else:
            candidates = keyword_hits[:n]

        # Every candidate gets an exact cosine score (keyword-only hits lack one),
        # so the similarity threshold is applied uniformly.
        missing = [c.chunk_id for c in candidates if c.vector_score is None]
        if missing:
            scores = await self.vector.score_chunks(session, owner_id=owner_id, query_vector=q_vec, chunk_ids=missing)
            for c in candidates:
                if c.chunk_id in scores:
                    c.vector_score = round(scores[c.chunk_id], 6)
        result.candidates_considered = len(candidates)
        if options.mode != "keyword":
            candidates = [c for c in candidates if (c.vector_score or 0.0) >= options.similarity_threshold]

        if use_rerank and self.reranker is not None:
            t = time.perf_counter()
            final = await self.reranker.rerank(q, candidates, top_k=options.top_k, min_score=options.rerank_min_score)
            mark("rerank", t)
        else:
            final = candidates[: options.top_k]
        for rank, c in enumerate(final, start=1):
            c.final_rank = rank
        result.chunks = final
        timings["total"] = round((time.perf_counter() - total_start) * 1000, 2)
        result.timings_ms = timings

        if debug:
            result.stages = {
                "vector": _stage_view(vector_hits),
                "keyword": _stage_view(keyword_hits),
                "fused": _stage_view(candidates),
                "final": _stage_view(final),
            }
        if options.use_cache:
            await self.cache.set_retrieval(
                owner_id,
                params,
                {
                    "chunks": [c.to_dict() for c in final],
                    "expanded_terms": result.expanded_terms,
                    "query_variants": result.query_variants,
                },
            )
        return result
