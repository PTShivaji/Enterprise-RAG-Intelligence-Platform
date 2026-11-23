"""Per-user RAG settings and model configuration."""

from __future__ import annotations

import os

from fastapi import APIRouter

from app.api.dependencies import ContainerDep, CurrentUser, RateLimited, SessionDep
from app.schemas.rag import ModelInfoResponse, RAGSettings, RAGSettingsUpdate
from app.services.settings_service import apply_update, get_user_settings, save_user_settings

router = APIRouter(tags=["Settings & Models"], dependencies=[RateLimited])

_PROVIDER_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "ollama": "OLLAMA_API_BASE",
}


@router.get("/settings", response_model=RAGSettings)
async def get_settings(session: SessionDep, container: ContainerDep, user: CurrentUser) -> RAGSettings:
    return await get_user_settings(session, container.settings, user.id)


@router.put("/settings", response_model=RAGSettings)
async def update_settings(body: RAGSettingsUpdate, session: SessionDep, container: ContainerDep,
                          user: CurrentUser) -> RAGSettings:
    """Update retrieval/generation/chunking preferences. Chunking changes apply on (re-)ingestion."""
    current = await get_user_settings(session, container.settings, user.id)
    updated = apply_update(current, body, container.settings, container.embeddings.model.max_seq_length - 2)
    await save_user_settings(session, user.id, updated)
    await container.cache.invalidate_user(user.id)
    return updated


@router.get("/models", response_model=ModelInfoResponse)
async def models(container: ContainerDep, _: CurrentUser) -> ModelInfoResponse:
    """Embedding/reranker in use and which LLM providers have credentials (never the keys)."""
    s = container.settings
    return ModelInfoResponse(
        embedding_model=container.embeddings.model_name,
        embedding_dimension=container.embeddings.dimension,
        embedding_max_seq_length=container.embeddings.model.max_seq_length,
        reranker_model=container.reranker.name if container.reranker else None,
        llm_allowed_models=s.llm_allowed_models,
        llm_default_model=s.llm_default_model,
        llm_configured_providers={"local": True} | {p: bool(os.environ.get(k)) for p, k in _PROVIDER_KEYS.items()},
    )
