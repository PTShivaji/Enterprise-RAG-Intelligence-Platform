"""Usage events: the raw material for analytics, latency and token metrics."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UsageEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One measured operation (search, chat, ingestion, evaluation)."""

    __tablename__ = "usage_events"
    __table_args__ = (
        Index("ix_usage_user_created", "user_id", "created_at"),
        Index("ix_usage_type_created", "event_type", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)  # search|chat|ingest|eval
    query: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    retrieval_ms: Mapped[float | None] = mapped_column(Float)
    llm_ms: Mapped[float | None] = mapped_column(Float)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    cache_hit: Mapped[bool | None] = mapped_column(Boolean)
    model: Mapped[str | None] = mapped_column(String(200))
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
