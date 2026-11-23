"""Per-user RAG settings and their translation into pipeline options."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ValidationFailedError
from app.ingestion.chunking import ChunkingConfig
from app.models.user import UserSettings
from app.rag.pipeline import RAGOptions
from app.retrieval.types import RetrievalOptions, SearchFilters
from app.schemas.rag import RAGSettings, RAGSettingsUpdate, SearchFiltersSchema


def default_rag_settings(settings: Settings) -> RAGSettings:
    """Server-configured defaults."""
    return RAGSettings(
        top_k=settings.retrieval_top_k,
        search_mode=settings.search_mode,
        rerank=settings.reranker_enabled,
        candidate_multiplier=settings.retrieval_candidate_multiplier,
        similarity_threshold=settings.similarity_threshold,
        rerank_min_score=settings.rerank_min_score,
        query_expansion=settings.query_expansion,
        llm_model=settings.llm_default_model,
        temperature=settings.llm_temperature,
        max_output_tokens=settings.llm_max_output_tokens,
        context_max_tokens=settings.context_max_tokens,
        chunk_strategy=settings.chunk_strategy,
        chunk_size_tokens=settings.chunk_size_tokens,
        chunk_overlap_tokens=settings.chunk_overlap_tokens,
        semantic_cache=settings.semantic_cache_enabled,
    )


async def get_user_settings(session: AsyncSession, settings: Settings, user_id: uuid.UUID) -> RAGSettings:
    row = await session.get(UserSettings, user_id)
    base = default_rag_settings(settings).model_dump()
    if row is not None:
        base.update({k: v for k, v in row.settings.items() if k in base})
    return RAGSettings.model_validate(base)


def apply_update(
    current: RAGSettings, update: RAGSettingsUpdate, settings: Settings, max_chunk_tokens: int
) -> RAGSettings:
    merged = current.model_dump() | update.model_dump(exclude_none=True)
    try:
        result = RAGSettings.model_validate(merged)
    except ValueError as exc:
        raise ValidationFailedError(str(exc)) from exc
    if result.llm_model not in settings.llm_allowed_models:
        raise ValidationFailedError(
            f"Model '{result.llm_model}' is not allowed", details={"allowed": settings.llm_allowed_models}
        )
    if result.chunk_size_tokens > max_chunk_tokens:
        raise ValidationFailedError(
            f"chunk_size_tokens must be <= {max_chunk_tokens} for the current embedding model"
        )
    return result


async def save_user_settings(session: AsyncSession, user_id: uuid.UUID, value: RAGSettings) -> None:
    row = await session.get(UserSettings, user_id)
    if row is None:
        session.add(UserSettings(user_id=user_id, settings=value.model_dump()))
    else:
        row.settings = value.model_dump()
    await session.commit()


def to_filters(schema: SearchFiltersSchema) -> SearchFilters:
    return SearchFilters(
        document_ids=schema.document_ids,
        file_types=list(schema.file_types) if schema.file_types else None,
        filename_contains=schema.filename_contains,
        page_from=schema.page_from,
        page_to=schema.page_to,
    )


def retrieval_options(user: RAGSettings, *, rerank_available: bool, filters: SearchFilters | None = None,
                      **overrides) -> RetrievalOptions:
    opts = RetrievalOptions(
        top_k=user.top_k,
        mode=user.search_mode,
        rerank=user.rerank and rerank_available,
        candidate_multiplier=user.candidate_multiplier,
        similarity_threshold=user.similarity_threshold,
        rerank_min_score=user.rerank_min_score,
        query_expansion=user.query_expansion,
        filters=filters or SearchFilters(),
    )
    for key, value in overrides.items():
        if value is not None:
            setattr(opts, key, value)
    opts.rerank = opts.rerank and rerank_available
    return opts


def rag_options(user: RAGSettings, retrieval: RetrievalOptions, model: str | None = None) -> RAGOptions:
    return RAGOptions(
        retrieval=retrieval,
        model=model or user.llm_model,
        temperature=user.temperature,
        max_tokens=user.max_output_tokens,
        context_max_tokens=user.context_max_tokens,
        use_semantic_cache=user.semantic_cache,
    )


def chunking_config(user: RAGSettings, strategy: str | None = None, size: int | None = None,
                    overlap: int | None = None) -> ChunkingConfig:
    try:
        return ChunkingConfig(
            strategy=strategy or user.chunk_strategy,  # type: ignore[arg-type]
            chunk_size=size or user.chunk_size_tokens,
            overlap=overlap if overlap is not None else user.chunk_overlap_tokens,
        )
    except ValueError as exc:
        raise ValidationFailedError(str(exc)) from exc
