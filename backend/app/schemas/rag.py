"""Search, chat, settings and evaluation schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import ORMModel


# --------------------------------------------------------------------- settings
class RAGSettings(BaseModel):
    """Per-user RAG configuration (validated; persisted as JSON)."""

    top_k: int = Field(5, ge=1, le=20)
    search_mode: Literal["vector", "keyword", "hybrid"] = "hybrid"
    rerank: bool = True
    candidate_multiplier: int = Field(4, ge=1, le=10)
    similarity_threshold: float = Field(0.25, ge=-1.0, le=1.0)
    rerank_min_score: float = Field(-6.0, ge=-20.0, le=20.0)
    query_expansion: Literal["none", "prf", "multi_query"] = "prf"
    llm_model: str = "local"
    temperature: float = Field(0.1, ge=0.0, le=1.5)
    max_output_tokens: int = Field(700, ge=64, le=4000)
    context_max_tokens: int = Field(2500, ge=200, le=12000)
    chunk_strategy: Literal["fixed", "recursive", "sentence"] = "recursive"
    chunk_size_tokens: int = Field(200, ge=32, le=2000)
    chunk_overlap_tokens: int = Field(40, ge=0, le=500)
    semantic_cache: bool = True

    @model_validator(mode="after")
    def _overlap(self) -> RAGSettings:
        if self.chunk_overlap_tokens >= self.chunk_size_tokens:
            raise ValueError("chunk_overlap_tokens must be smaller than chunk_size_tokens")
        return self


class RAGSettingsUpdate(BaseModel):
    """Partial update; unspecified fields are unchanged."""

    top_k: int | None = Field(None, ge=1, le=20)
    search_mode: Literal["vector", "keyword", "hybrid"] | None = None
    rerank: bool | None = None
    candidate_multiplier: int | None = Field(None, ge=1, le=10)
    similarity_threshold: float | None = Field(None, ge=-1.0, le=1.0)
    rerank_min_score: float | None = Field(None, ge=-20.0, le=20.0)
    query_expansion: Literal["none", "prf", "multi_query"] | None = None
    llm_model: str | None = None
    temperature: float | None = Field(None, ge=0.0, le=1.5)
    max_output_tokens: int | None = Field(None, ge=64, le=4000)
    context_max_tokens: int | None = Field(None, ge=200, le=12000)
    chunk_strategy: Literal["fixed", "recursive", "sentence"] | None = None
    chunk_size_tokens: int | None = Field(None, ge=32, le=2000)
    chunk_overlap_tokens: int | None = Field(None, ge=0, le=500)
    semantic_cache: bool | None = None


class ModelInfoResponse(BaseModel):
    embedding_model: str
    embedding_dimension: int
    embedding_max_seq_length: int
    reranker_model: str | None
    llm_allowed_models: list[str]
    llm_default_model: str
    llm_configured_providers: dict[str, bool]


# ----------------------------------------------------------------------- search
class SearchFiltersSchema(BaseModel):
    document_ids: list[uuid.UUID] | None = None
    file_types: list[Literal["pdf", "docx", "txt"]] | None = None
    filename_contains: str | None = Field(None, max_length=200)
    page_from: int | None = Field(None, ge=1)
    page_to: int | None = Field(None, ge=1)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int | None = Field(None, ge=1, le=50)
    search_mode: Literal["vector", "keyword", "hybrid"] | None = None
    rerank: bool | None = None
    similarity_threshold: float | None = Field(None, ge=-1.0, le=1.0)
    query_expansion: Literal["none", "prf", "multi_query"] | None = None
    filters: SearchFiltersSchema = Field(default_factory=SearchFiltersSchema)
    debug: bool = False


class SearchResultItem(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    file_type: str
    content: str
    chunk_index: int
    page_number: int | None
    page_end: int | None
    section: str | None
    vector_score: float | None
    keyword_score: float | None
    vector_rank: int | None
    keyword_rank: int | None
    fused_score: float | None
    rerank_score: float | None
    final_rank: int | None


class SearchResponse(BaseModel):
    query: str
    search_mode: str
    reranked: bool
    results: list[SearchResultItem]
    expanded_terms: list[str]
    query_variants: list[str]
    cache_hit: bool
    embedding_cache_hit: bool
    candidates_considered: int
    timings_ms: dict[str, float]
    stages: dict[str, list[dict[str, Any]]] | None = None


class SearchHistoryItem(BaseModel):
    id: uuid.UUID
    query: str | None
    latency_ms: float
    results: int | None
    cache_hit: bool | None
    created_at: datetime


# ------------------------------------------------------------------------- chat
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: uuid.UUID | None = None
    model: str | None = None
    top_k: int | None = Field(None, ge=1, le=20)
    search_mode: Literal["vector", "keyword", "hybrid"] | None = None
    rerank: bool | None = None
    filters: SearchFiltersSchema = Field(default_factory=SearchFiltersSchema)


class CitationSchema(BaseModel):
    index: int
    document_id: str
    filename: str
    chunk_id: str
    chunk_ids: list[str]
    page_number: int | None
    page_end: int | None
    section: str | None
    text: str
    retrieval_score: float | None
    rerank_score: float | None
    vector_score: float | None
    support_score: float


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    answer: str
    citations: list[CitationSchema]
    insufficient_evidence: bool
    verification: dict[str, Any]
    model: str
    provider: str
    usage: dict[str, Any]
    timings_ms: dict[str, float]
    retrieval: dict[str, Any]
    context: dict[str, Any]
    semantic_cache_hit: bool
    retrieval_query: str


class MessageSchema(ORMModel):
    id: uuid.UUID
    role: str
    content: str
    citations: list[dict[str, Any]]
    metadata: dict[str, Any] = Field(validation_alias="message_metadata")
    created_at: datetime


class ConversationSummary(ORMModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationSummary):
    messages: list[MessageSchema]


# ------------------------------------------------------------------- evaluation
class EvalItem(BaseModel):
    id: str = Field(max_length=100)
    category: str = Field("general", max_length=50)
    question: str = Field(min_length=1, max_length=1000)
    expected_answer: str | None = Field(None, max_length=4000)
    expected_documents: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list, description="Verbatim phrases that a relevant chunk contains")
    answerable: bool = True


class EvaluationRunRequest(BaseModel):
    name: str = Field("evaluation", max_length=200)
    dataset: list[EvalItem] | None = Field(None, description="Omit to use the bundled sample dataset")
    configurations: list[RAGSettingsUpdate] | None = Field(
        None, description="Retrieval/generation configurations to compare (ablation). Omit for the current settings."
    )
    k: int = Field(5, ge=1, le=20)
    generate_answers: bool = True


class EvaluationRunResponse(ORMModel):
    id: uuid.UUID
    name: str
    status: str
    config: dict[str, Any]
    metrics: dict[str, Any]
    results: list[dict[str, Any]]
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class EvaluationRunSummary(ORMModel):
    id: uuid.UUID
    name: str
    status: str
    metrics: dict[str, Any]
    created_at: datetime
    completed_at: datetime | None
