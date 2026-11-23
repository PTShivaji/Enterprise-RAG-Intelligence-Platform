"""SQL filter construction shared by vector and keyword search.

Owner isolation is applied here unconditionally: there is no code path that
queries chunks without ``owner_id = :current_user``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ColumnElement, and_, func, or_

from app.models.document import Document, DocumentChunk, DocumentStatus
from app.retrieval.types import SearchFilters


def build_conditions(owner_id: uuid.UUID, embedding_model: str, filters: SearchFilters) -> list[ColumnElement[bool]]:
    """Return WHERE conditions for chunk queries joined with ``documents``."""
    conditions: list[ColumnElement[bool]] = [
        DocumentChunk.owner_id == owner_id,
        Document.owner_id == owner_id,
        DocumentChunk.embedding_model == embedding_model,
        Document.status == DocumentStatus.INDEXED,
    ]
    if filters.document_ids:
        conditions.append(DocumentChunk.document_id.in_(filters.document_ids))
    if filters.file_types:
        conditions.append(Document.file_type.in_([f.lower() for f in filters.file_types]))
    if filters.filename_contains:
        # Bound parameter + escaped wildcards: no SQL injection, literal matching.
        pattern = filters.filename_contains.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        conditions.append(func.lower(Document.filename).like(f"%{pattern.lower()}%", escape="\\"))
    if filters.page_from is not None:
        conditions.append(
            or_(DocumentChunk.page_number.is_(None), func.coalesce(DocumentChunk.page_end, DocumentChunk.page_number) >= filters.page_from)
        )
    if filters.page_to is not None:
        conditions.append(or_(DocumentChunk.page_number.is_(None), DocumentChunk.page_number <= filters.page_to))
    return [and_(*conditions)]
