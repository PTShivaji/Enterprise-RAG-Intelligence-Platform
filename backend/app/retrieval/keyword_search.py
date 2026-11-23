"""Lexical retrieval with PostgreSQL full-text search.

``plainto_tsquery`` safely parses arbitrary user text (no tsquery syntax errors,
no injection) but AND-s every term, which is far too strict for natural-language
questions. We rewrite its ``&`` operators to ``|`` so any matching term counts,
then rank with ``ts_rank`` (normalisation flag 1 = divide by 1 + log(doc length)),
which rewards documents matching more and rarer-in-document terms. PostgreSQL has
no native BM25; this is the standard built-in approximation.
"""

from __future__ import annotations

import uuid

from sqlalchemy import String, cast, func, literal_column, select
from sqlalchemy.dialects.postgresql import TSQUERY
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk
from app.retrieval.filters import build_conditions
from app.retrieval.types import RetrievedChunk, SearchFilters
from app.retrieval.vector_search import CHUNK_COLUMNS, row_to_chunk

_MAX_QUERY_CHARS = 1000


def or_tsquery(query: str):
    """Build ``replace(plainto_tsquery('english', q)::text, '&', '|')::tsquery``."""
    plain = func.plainto_tsquery(literal_column("'english'::regconfig"), query)
    return cast(func.replace(cast(plain, String), "&", "|"), TSQUERY)


class KeywordSearcher:
    """Full-text search over the generated ``content_tsv`` column (GIN index)."""

    async def search(
        self,
        session: AsyncSession,
        *,
        owner_id: uuid.UUID,
        query: str,
        embedding_model: str,
        k: int,
        filters: SearchFilters,
    ) -> list[RetrievedChunk]:
        query = query[:_MAX_QUERY_CHARS].strip()
        if not query:
            return []
        tsq = or_tsquery(query)
        rank = func.ts_rank(DocumentChunk.content_tsv, tsq, 1)
        stmt = (
            select(*CHUNK_COLUMNS, rank.label("score"))
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(*build_conditions(owner_id, embedding_model, filters))
            .where(DocumentChunk.content_tsv.op("@@")(tsq))
            .order_by(rank.desc(), DocumentChunk.id)
            .limit(k)
        )
        rows = (await session.execute(stmt)).all()
        results: list[RetrievedChunk] = []
        for rank_pos, row in enumerate(rows, start=1):
            chunk = row_to_chunk(row)
            chunk.keyword_score = float(row.score)
            chunk.keyword_rank = rank_pos
            results.append(chunk)
        return results
