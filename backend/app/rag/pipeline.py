"""End-to-end RAG orchestration (persistence-agnostic).

    question ─► preprocess ─► contextualise (follow-ups) ─► semantic cache?
             ─► retrieve (hybrid + rerank) ─► no evidence? → abstain (no LLM call)
             ─► build context (dedupe/merge/budget/compress) ─► grounded prompt
             ─► LLM (LiteLLM or local extractive) ─► citation verification ─► answer

``answer()`` and ``stream()`` share ``_prepare`` and ``_finalize`` so the blocking
and streaming paths are guaranteed to behave identically.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_cache import CacheService, fingerprint
from app.core.config import Settings
from app.core.logging import get_logger
from app.core.tokens import get_token_counter
from app.embeddings.service import EmbeddingService
from app.observability.metrics import ANSWERS
from app.rag.citations import verify_citations
from app.rag.context_builder import ContextBuilder
from app.rag.generation import ProviderRouter
from app.rag.prompt_builder import build_messages
from app.rag.types import INSUFFICIENT_EVIDENCE, BuiltContext, GenerationRequest, GenerationResult
from app.retrieval.query_processing import contextualize_query, preprocess_query
from app.retrieval.retriever import Retriever
from app.retrieval.types import RetrievalOptions, RetrievalResult

logger = get_logger(__name__)
HISTORY_TURN_MAX_TOKENS = 300


@dataclass(slots=True)
class RAGOptions:
    retrieval: RetrievalOptions
    model: str = "local"
    temperature: float = 0.1
    max_tokens: int = 700
    context_max_tokens: int = 2500
    use_semantic_cache: bool = True


@dataclass(slots=True)
class RAGAnswer:
    answer: str
    citations: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    verification: dict[str, Any]
    insufficient_evidence: bool
    model: str
    provider: str
    usage: dict[str, Any]
    timings_ms: dict[str, float]
    retrieval: dict[str, Any]
    context: dict[str, Any]
    semantic_cache_hit: bool = False
    retrieval_query: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class _Prepared:
    question: str
    retrieval_query: str
    options: RAGOptions
    retrieval: RetrievalResult | None = None
    context: BuiltContext | None = None
    messages: list[dict[str, str]] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    started: float = 0.0
    cache_fp: str | None = None
    query_vector: Any = None
    early: RAGAnswer | None = None


class RAGPipeline:
    def __init__(
        self,
        settings: Settings,
        retriever: Retriever,
        router: ProviderRouter,
        embeddings: EmbeddingService,
        cache: CacheService,
    ) -> None:
        self.settings = settings
        self.retriever = retriever
        self.router = router
        self.embeddings = embeddings
        self.cache = cache
        self.counter = get_token_counter()

    # ------------------------------------------------------------------ helpers
    def _trim_history(self, history: list[dict[str, str]]) -> list[dict[str, str]]:
        return [
            {"role": h["role"], "content": self.counter.truncate(h["content"], HISTORY_TURN_MAX_TOKENS)}
            for h in history
        ]

    @staticmethod
    def _retrieval_meta(r: RetrievalResult | None) -> dict[str, Any]:
        if r is None:
            return {}
        return {
            "cache_hit": r.cache_hit,
            "embedding_cache_hit": r.embedding_cache_hit,
            "expanded_terms": r.expanded_terms,
            "query_variants": r.query_variants,
            "candidates_considered": r.candidates_considered,
            "chunks_returned": len(r.chunks),
            "timings_ms": r.timings_ms,
        }

    @staticmethod
    def _context_meta(c: BuiltContext | None) -> dict[str, Any]:
        if c is None:
            return {}
        return {
            "sources": len(c.sources),
            "total_tokens": c.total_tokens,
            "budget_tokens": c.budget_tokens,
            "dropped_duplicates": c.dropped_duplicates,
            "merged_adjacent": c.merged_adjacent,
            "compressed_sources": c.compressed_sources,
            "truncated_sources": c.truncated_sources,
            "suspicious_sources": sum(1 for s in c.sources if s.suspicious),
        }

    def _semantic_fp(self, options: RAGOptions) -> str:
        r = options.retrieval
        return fingerprint({
            "model": options.model, "temp": options.temperature, "ctx": options.context_max_tokens,
            "retrieval": r.cache_params("", self.embeddings.model_name,
                                        self.retriever.reranker.name if r.rerank and self.retriever.reranker else "none"),
        })

    def _abstain(self, prep: _Prepared, reason: str) -> RAGAnswer:
        ANSWERS.labels(outcome="no_evidence").inc()
        prep.timings["total"] = round((time.perf_counter() - prep.started) * 1000, 2)
        return RAGAnswer(
            answer=INSUFFICIENT_EVIDENCE,
            citations=[],
            sources=[],
            verification={"insufficient_evidence": True, "reason": reason, "citation_count": 0},
            insufficient_evidence=True,
            model=prep.options.model,
            provider="none",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost_usd": 0.0},
            timings_ms=prep.timings,
            retrieval=self._retrieval_meta(prep.retrieval),
            context=self._context_meta(prep.context),
            retrieval_query=prep.retrieval_query,
        )

    # ------------------------------------------------------------------ stages
    async def _prepare(
        self,
        session: AsyncSession,
        owner_id: uuid.UUID,
        question: str,
        options: RAGOptions,
        history: list[dict[str, str]],
        prior_questions: list[str],
    ) -> _Prepared:
        started = time.perf_counter()
        q = preprocess_query(question)
        prep = _Prepared(question=q, retrieval_query=contextualize_query(q, prior_questions),
                         options=options, started=started)
        if not q:
            prep.early = self._abstain(prep, "empty_question")
            return prep

        # Semantic answer cache: only for stateless questions (history changes answers).
        if options.use_semantic_cache and not history and self.settings.semantic_cache_enabled:
            prep.cache_fp = self._semantic_fp(options)
            prep.query_vector, _ = await self.embeddings.embed_query(q)
            hit = await self.cache.semantic_lookup(owner_id, prep.cache_fp, prep.query_vector)
            if hit is not None:
                cached, similarity = hit
                answer = RAGAnswer(**cached)
                answer.semantic_cache_hit = True
                answer.timings_ms = {"total": round((time.perf_counter() - started) * 1000, 2)}
                answer.usage = {**answer.usage, "prompt_tokens": 0, "completion_tokens": 0,
                                "total_tokens": 0, "cost_usd": 0.0}
                answer.retrieval = {**answer.retrieval, "semantic_cache_similarity": round(similarity, 4)}
                ANSWERS.labels(outcome="semantic_cache").inc()
                prep.early = answer
                return prep

        t = time.perf_counter()
        prep.retrieval = await self.retriever.retrieve(
            session, owner_id=owner_id, query=prep.retrieval_query, options=options.retrieval, llm_model=options.model
        )
        prep.timings["retrieval"] = round((time.perf_counter() - t) * 1000, 2)
        if not prep.retrieval.chunks:
            prep.early = self._abstain(prep, "no_relevant_chunks")
            return prep

        t = time.perf_counter()
        builder = ContextBuilder(options.context_max_tokens)
        prep.context = builder.build(prep.retrieval.chunks, q)
        prep.messages = build_messages(q, prep.context.sources, self._trim_history(history))
        prep.timings["context"] = round((time.perf_counter() - t) * 1000, 2)
        return prep

    def _request(self, prep: _Prepared) -> GenerationRequest:
        assert prep.context is not None
        return GenerationRequest(
            question=prep.question,
            sources=prep.context.sources,
            messages=prep.messages,
            model=prep.options.model,
            temperature=prep.options.temperature,
            max_tokens=prep.options.max_tokens,
        )

    async def _finalize(self, prep: _Prepared, owner_id: uuid.UUID, gen: GenerationResult, history_used: bool) -> RAGAnswer:
        assert prep.context is not None
        report = verify_citations(gen.text, prep.context.sources)
        verification = report.verification()
        verification["grounded"] = report.insufficient_evidence or (
            bool(report.citations) and report.weakly_supported_sentences == 0
        )
        prep.timings["generation"] = gen.latency_ms
        prep.timings["total"] = round((time.perf_counter() - prep.started) * 1000, 2)
        outcome = "insufficient" if report.insufficient_evidence else ("grounded" if verification["grounded"] else "ungrounded")
        ANSWERS.labels(outcome=outcome).inc()
        answer = RAGAnswer(
            answer=report.answer,
            citations=[c.to_dict() for c in report.citations],
            sources=[s.to_dict() for s in prep.context.sources],
            verification=verification,
            insufficient_evidence=report.insufficient_evidence,
            model=gen.model,
            provider=gen.provider,
            usage={
                "prompt_tokens": gen.prompt_tokens,
                "completion_tokens": gen.completion_tokens,
                "total_tokens": gen.prompt_tokens + gen.completion_tokens,
                "context_tokens": prep.context.total_tokens,
                "cost_usd": gen.cost_usd,
            },
            timings_ms=prep.timings,
            retrieval=self._retrieval_meta(prep.retrieval),
            context=self._context_meta(prep.context),
            retrieval_query=prep.retrieval_query,
        )
        if prep.cache_fp is not None and prep.query_vector is not None and not history_used and verification["grounded"]:
            await self.cache.semantic_store(owner_id, prep.cache_fp, prep.question, prep.query_vector, answer.to_dict())
        return answer

    # ------------------------------------------------------------------ public
    async def answer(
        self,
        session: AsyncSession,
        *,
        owner_id: uuid.UUID,
        question: str,
        options: RAGOptions,
        history: list[dict[str, str]] | None = None,
        prior_questions: list[str] | None = None,
    ) -> RAGAnswer:
        history = history or []
        prep = await self._prepare(session, owner_id, question, options, history, prior_questions or [])
        if prep.early is not None:
            return prep.early
        gen = await self.router.for_model(options.model).generate(self._request(prep))
        return await self._finalize(prep, owner_id, gen, bool(history))

    async def stream(
        self,
        session: AsyncSession,
        *,
        owner_id: uuid.UUID,
        question: str,
        options: RAGOptions,
        history: list[dict[str, str]] | None = None,
        prior_questions: list[str] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield events: ``sources`` -> ``token``* -> ``done`` (final, verified answer).

        Tokens are streamed as generated; the ``done`` event carries the verified
        answer (invalid citation markers removed), which clients should display.
        """
        history = history or []
        prep = await self._prepare(session, owner_id, question, options, history, prior_questions or [])
        if prep.early is not None:
            yield {"type": "done", "answer": prep.early.to_dict()}
            return
        assert prep.context is not None
        yield {"type": "sources", "sources": [s.to_dict() for s in prep.context.sources],
               "retrieval": self._retrieval_meta(prep.retrieval)}
        final: GenerationResult | None = None
        async for delta in self.router.for_model(options.model).stream(self._request(prep)):
            if delta.final is not None:
                final = delta.final
            elif delta.text:
                yield {"type": "token", "text": delta.text}
        if final is None:  # pragma: no cover - providers always emit a final result
            raise RuntimeError("LLM stream ended without a final result")
        answer = await self._finalize(prep, owner_id, final, bool(history))
        yield {"type": "done", "answer": answer.to_dict()}
