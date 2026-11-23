"""Document and chunk schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class DocumentResponse(ORMModel):
    id: uuid.UUID
    filename: str
    file_type: str
    content_type: str
    size_bytes: int
    sha256: str
    status: str
    error_message: str | None
    page_count: int | None
    chunk_count: int
    token_count: int
    title: str | None
    metadata: dict[str, Any] = Field(validation_alias="doc_metadata")
    embedding_model: str | None
    chunking_config: dict[str, Any]
    ingestion_ms: int | None
    created_at: datetime
    updated_at: datetime
    indexed_at: datetime | None


class DocumentUploadResponse(BaseModel):
    document: DocumentResponse
    duplicate: bool = False
    ingestion_queued: bool = False


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int


class DocumentStatusResponse(BaseModel):
    id: uuid.UUID
    status: str
    chunk_count: int
    error_message: str | None
    indexed_at: datetime | None


class IngestRequest(BaseModel):
    """Optional per-ingestion chunking override (defaults to the user's settings)."""

    chunk_strategy: str | None = Field(default=None, pattern="^(fixed|recursive|sentence)$")
    chunk_size_tokens: int | None = Field(default=None, ge=32, le=2000)
    chunk_overlap_tokens: int | None = Field(default=None, ge=0, le=500)


class ChunkResponse(ORMModel):
    id: str
    chunk_index: int
    content: str
    page_number: int | None
    page_end: int | None
    section: str | None
    token_count: int
    char_start: int
    char_end: int


class ChunkListResponse(BaseModel):
    items: list[ChunkResponse]
    total: int
