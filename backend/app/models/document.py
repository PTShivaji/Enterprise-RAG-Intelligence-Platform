"""Documents and their embedded chunks (pgvector + full-text search)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import get_settings
from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# The vector column dimension is fixed at migration time. The configured embedding
# model is validated against it at start-up so dimensions can never be mixed.
EMBEDDING_DIM = get_settings().embedding_dimension


class DocumentStatus(enum.StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An uploaded source file owned by a single user."""

    __tablename__ = "documents"
    __table_args__ = (
        # Duplicate detection: the same bytes cannot be uploaded twice by the same user.
        UniqueConstraint("owner_id", "sha256", name="uq_documents_owner_sha256"),
        Index("ix_documents_owner_created", "owner_id", "created_at"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status", values_callable=lambda e: [m.value for m in e]),
        default=DocumentStatus.UPLOADED,
        nullable=False,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    doc_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
    embedding_model: Mapped[str | None] = mapped_column(String(200))
    chunking_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    ingestion_ms: Mapped[int | None] = mapped_column(Integer)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class DocumentChunk(TimestampMixin, Base):
    """A retrievable unit of text with its embedding and full-text vector.

    ``owner_id`` is denormalised from ``documents`` so that every retrieval query can
    filter by owner directly on this table (user isolation + index efficiency).
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_index"),
        Index("ix_chunks_owner_model", "owner_id", "embedding_model"),
        Index("ix_chunks_content_tsv", "content_tsv", postgresql_using="gin"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    # Stable, content-derived identifier: sha256(document_id:index:content)[:32].
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(500))
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    content_tsv = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', content)", persisted=True)
    )

    document: Mapped[Document] = relationship(back_populates="chunks")
