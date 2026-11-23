"""User accounts, roles and per-user settings."""

from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy import Boolean, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserRole(enum.StrEnum):
    USER = "user"
    ADMIN = "admin"


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An authenticated principal. Every document/conversation is owned by a user."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(200))
    hashed_password: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda e: [m.value for m in e]),
        default=UserRole.USER,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class UserSettings(TimestampMixin, Base):
    """Per-user RAG preferences (retrieval, chunking and model choices).

    Stored as validated JSON so new knobs do not require schema migrations; the
    Pydantic ``RAGSettings`` schema is the source of truth for shape and bounds.
    """

    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
