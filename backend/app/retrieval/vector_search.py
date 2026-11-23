"""Semantic retrieval over pgvector (cosine distance, HNSW index)."""

from __future__ import annotations

import uuid

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk
from app.retrieval.filters import build_conditions
from app.retrieval.types import RetrievedChunk, SearchFilters

CHUNK_COLUMNS = (
    DocumentChunk.id,
    DocumentChunk.document_id,
    Document.filename,
    Document.file_type,
    DocumentChunk.content,
    DocumentChunk.chunk_index,
    DocumentChunk.char_start,
    DocumentChunk.char_end,
    DocumentChunk.page_number,
    DocumentChunk.page_end,
    DocumentChunk.section,
)


def row_to_chunk(row) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=row.id,
        document_id=str(row.document_id),
        filename=row.filename,
        file_type=row.file_type,
        content=row.content,
        chunk_index=row.chunk_index,
        char_start=row.char_start,
        char_end=row.char_end,
        page_number=row.page_number,
        page_end=row.page_end,
        section=row.section,
    )


class VectorSearcher:
    """Top-K cosine-similarity search restricted to the caller's documents.

    HNSW is an approximate index; combined with a selective ``owner_id`` filter,
    plain HNSW can return fewer than K rows (post-filtering). On pgvector >= 0.8 we
    enable ``hnsw.iterative_scan`` so the index keeps scanning until K filtered
    rows are found, and raise ``ef_search`` above K for better recall.
    """

    def __init__(self, *, iterative_scan: bool = False) -> None:
        self.iterative_scan = iterative_scan

    async def search(
        self,
        session: AsyncSession,
        *,
        owner_id: uuid.UUID,
        query_vector: np.ndarray,
        embedding_model: str,
        k: int,
        filters: SearchFilters,
    ) -> list[RetrievedChunk]:
        vec = np.asarray(query_vector, dtype=np.float32).tolist()
        distance = DocumentChunk.embedding.cosine_distance(vec)
        stmt = (
            select(*CHUNK_COLUMNS, (1 - distance).label("score"))
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(*build_conditions(owner_id, embedding_model, filters))
            .order_by(distance)
            .limit(k)
        )
        ef_search = max(40, min(int(k) * 4, 1000))  # validated int, safe to inline
        # SET LOCAL lasts until the end of the current (auto-begun) transaction only.
        await session.execute(text(f"SET LOCAL hnsw.ef_search = {ef_search}"))
        if self.iterative_scan:
            await session.execute(text("SET LOCAL hnsw.iterative_scan = 'relaxed_order'"))
        rows = (await session.execute(stmt)).all()
        results: list[RetrievedChunk] = []
        for rank, row in enumerate(rows, start=1):
            chunk = row_to_chunk(row)
            chunk.vector_score = float(row.score)
            chunk.vector_rank = rank
            results.append(chunk)
        # relaxed_order may return slightly out-of-order rows; restore exact order.
        results.sort(key=lambda c: c.vector_score or 0.0, reverse=True)
        for rank, chunk in enumerate(results, start=1):
            chunk.vector_rank = rank
        return results

    async def score_chunks(
        self, session: AsyncSession, *, owner_id: uuid.UUID, query_vector: np.ndarray, chunk_ids: list[str]
    ) -> dict[str, float]:
        """Exact cosine similarity for specific chunks (used to score keyword-only hits)."""
        if not chunk_ids:
            return {}
        vec = np.asarray(query_vector, dtype=np.float32).tolist()
        stmt = select(DocumentChunk.id, (1 - DocumentChunk.embedding.cosine_distance(vec)).label("score")).where(
            DocumentChunk.owner_id == owner_id, DocumentChunk.id.in_(chunk_ids)
        )
        return {row.id: float(row.score) for row in (await session.execute(stmt)).all()}
