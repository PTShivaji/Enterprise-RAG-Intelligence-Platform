"""Shared API schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorResponse(BaseModel):
    """Safe error envelope returned for every failure."""

    error: str
    message: str
    request_id: str | None = None
    details: dict[str, Any] | None = None


class MessageResponse(BaseModel):
    message: str
