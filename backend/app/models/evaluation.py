"""Evaluation runs and their persisted metrics."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EvaluationRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One execution of the evaluation harness over a dataset."""

    __tablename__ = "evaluation_runs"
    __table_args__ = (Index("ix_eval_runs_user_created", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
