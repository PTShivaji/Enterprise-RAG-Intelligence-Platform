"""Centralised, typed application configuration.

All runtime configuration comes from environment variables (optionally loaded from
``backend/.env``). Nothing secret is hard-coded; insecure defaults are rejected
when ``ENVIRONMENT=production``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]

_INSECURE_SECRET = "change-me-to-a-long-random-string-at-least-32-chars"  # noqa: S105 - sentinel, rejected in prod


class Settings(BaseSettings):
    """Application settings loaded from the environment."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Application
    app_name: str = "Enterprise RAG Intelligence Platform"
    app_version: str = "1.0.0"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = True
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:8080"]
    )

    # Security
    jwt_secret_key: str = _INSECURE_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    admin_emails: list[str] = Field(default_factory=list)
    rate_limit_per_minute: int = 120
    auth_rate_limit_per_minute: int = 10

    # Database
    database_url: str = "postgresql+asyncpg://rag:rag_password@localhost:5442/rag_platform"
    test_database_url: str = "postgresql+asyncpg://rag:rag_password@localhost:5442/rag_test"
    db_pool_size: int = 10
    db_max_overflow: int = 10

    # Redis / cache
    redis_url: str = "redis://localhost:6380/0"
    cache_enabled: bool = True
    embedding_cache_ttl_seconds: int = 86_400
    retrieval_cache_ttl_seconds: int = 600

    # Uploads
    storage_dir: Path = BACKEND_DIR / "storage"
    max_upload_size_mb: int = 25

    # Embeddings
    embedding_provider: Literal["sentence-transformers", "hash"] = "sentence-transformers"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimension: int = 384
    embedding_batch_size: int = 32
    embedding_device: str = "cpu"

    # Reranking
    reranker_enabled: bool = True
    reranker_provider: Literal["cross-encoder", "none"] = "cross-encoder"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # Chunking
    chunk_strategy: Literal["fixed", "recursive", "sentence"] = "recursive"
    # Measured in the *embedding model's* tokenizer. Must stay below the model's
    # max_seq_length (256 for MiniLM) or text would be silently truncated when embedded.
    chunk_size_tokens: int = Field(200, ge=32, le=2000)
    chunk_overlap_tokens: int = Field(40, ge=0, le=500)
    contextual_chunk_headers: bool = True

    # Retrieval
    retrieval_top_k: int = Field(5, ge=1, le=50)
    retrieval_candidate_multiplier: int = Field(4, ge=1, le=20)
    similarity_threshold: float = Field(0.25, ge=-1.0, le=1.0)
    # Reranker logit below which a candidate is treated as irrelevant (ms-marco scale).
    # Liberal cutoff: retrieval maximises recall; the answer stage decides abstention.
    # (Measured: -6 dropped relevant paraphrase chunks with MiniLM-L6 cross-encoder.)
    rerank_min_score: float = Field(-10.0, ge=-20.0, le=20.0)
    # Local extractive mode: best sentence-level cross-encoder logit needed to answer.
    # Calibrated on evaluation/datasets/sample_qa.json (best balanced accuracy, ties broken toward
    # abstaining), then validated on the held-out sample_qa_holdout.json. See docs/EVALUATION.md.
    local_answer_min_logit: float = Field(1.0, ge=-20.0, le=20.0)
    rrf_k: int = 60
    search_mode: Literal["vector", "keyword", "hybrid"] = "hybrid"
    # PRF measurably lowered MRR on the sample benchmark (see docs/EVALUATION.md); opt-in.
    query_expansion: Literal["none", "prf", "multi_query"] = "none"
    context_max_tokens: int = 2500
    semantic_cache_enabled: bool = True
    semantic_cache_threshold: float = Field(0.95, ge=0.5, le=1.0)
    semantic_cache_ttl_seconds: int = 3600
    semantic_cache_max_entries: int = 200

    # LLM
    llm_default_model: str = "local"
    llm_allowed_models: list[str] = Field(
        default_factory=lambda: [
            "local",
            "gpt-4o-mini",
            "anthropic/claude-haiku-5-5",
            "gemini/gemini-2.0-flash",
            "ollama/llama3.2",
        ]
    )
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2
    llm_temperature: float = 0.1
    llm_max_output_tokens: int = 700

    # Conversation memory
    history_recent_turns: int = 4
    history_relevant_turns: int = 2

    @field_validator("storage_dir", mode="after")
    @classmethod
    def _resolve_storage(cls, value: Path) -> Path:
        return value if value.is_absolute() else (BACKEND_DIR / value).resolve()

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        if self.chunk_overlap_tokens >= self.chunk_size_tokens:
            raise ValueError("CHUNK_OVERLAP_TOKENS must be smaller than CHUNK_SIZE_TOKENS")
        if self.environment == "production":
            if self.jwt_secret_key == _INSECURE_SECRET or len(self.jwt_secret_key) < 32:
                raise ValueError("A strong JWT_SECRET_KEY (>=32 chars) is required in production")
            if "*" in self.cors_origins:
                raise ValueError("Wildcard CORS origins are not allowed in production")
        if self.llm_default_model not in self.llm_allowed_models:
            self.llm_allowed_models = [self.llm_default_model, *self.llm_allowed_models]
        return self

    @property
    def max_upload_size_bytes(self) -> int:
        """Upload size limit in bytes."""
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings singleton (override in tests via dependency/env)."""
    return Settings()
