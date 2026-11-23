"""Ingestion pipeline: file -> parse -> clean -> chunk -> embed -> index.

Runs as a background task with its own DB session. Re-ingestion is atomic:
old chunks are deleted and new chunks inserted in the same transaction, so a
document is never half-indexed. Any failure marks the document FAILED with a
safe error message (and is logged with the exception), never silently.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select

from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.ingestion.chunking import ChunkingConfig, build_embedding_text, chunk_document
from app.ingestion.metadata import derive_title, document_statistics
from app.ingestion.parsers import parse_document
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.usage import UsageEvent
from app.observability.metrics import INGESTION_CHUNKS, INGESTION_DOCS, INGESTION_LATENCY
from app.services.container import AppContainer

logger = get_logger(__name__)
INSERT_BATCH = 200


async def ingest_document(container: AppContainer, document_id: uuid.UUID, cfg: ChunkingConfig) -> None:
    """Parse, chunk, embed and index one document. Safe to call repeatedly."""
    start = time.perf_counter()
    async with container.db.session_factory() as session:
        document = await session.get(Document, document_id)
        if document is None:
            logger.warning("Ingestion skipped: document not found", extra={"document_id": str(document_id)})
            return
        document.status = DocumentStatus.PROCESSING
        document.error_message = None
        await session.commit()
        owner_id = document.owner_id
        file_type = document.file_type
        try:
            data = await asyncio.to_thread(Path(document.storage_path).read_bytes)
            parsed = await asyncio.to_thread(parse_document, file_type, data)
            embeddings = container.embeddings
            chunks = await asyncio.to_thread(chunk_document, parsed, cfg, embeddings.count_tokens)
            if not chunks:
                raise AppError("No text content could be extracted from the document")
            title = derive_title(parsed, document.filename)
            texts = [
                build_embedding_text(
                    c, title=title, filename=document.filename,
                    use_header=container.settings.contextual_chunk_headers,
                )
                for c in chunks
            ]
            vectors = await embeddings.embed_documents(texts)

            await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
            rows = [
                DocumentChunk(
                    id=c.stable_id(str(document.id)),
                    document_id=document.id,
                    owner_id=owner_id,
                    chunk_index=c.index,
                    content=c.content,
                    page_number=c.page_number,
                    page_end=c.page_end,
                    section=c.section,
                    token_count=c.token_count,
                    char_start=c.char_start,
                    char_end=c.char_end,
                    chunk_metadata=c.metadata,
                    embedding=vectors[i].tolist(),
                    embedding_model=embeddings.model_name,
                )
                for i, c in enumerate(chunks)
            ]
            for i in range(0, len(rows), INSERT_BATCH):
                session.add_all(rows[i : i + INSERT_BATCH])
                await session.flush()

            elapsed_ms = int((time.perf_counter() - start) * 1000)
            document.status = DocumentStatus.INDEXED
            document.chunk_count = len(chunks)
            document.token_count = sum(c.token_count for c in chunks)
            document.page_count = parsed.page_count
            document.title = title
            document.doc_metadata = document_statistics(parsed, chunks)
            document.embedding_model = embeddings.model_name
            document.chunking_config = {"strategy": cfg.strategy, "chunk_size": cfg.chunk_size, "overlap": cfg.overlap}
            document.ingestion_ms = elapsed_ms
            document.indexed_at = datetime.now(UTC)
            session.add(UsageEvent(
                user_id=owner_id, event_type="ingest", latency_ms=elapsed_ms, success=True,
                model=embeddings.model_name,
                event_metadata={"document_id": str(document.id), "chunks": len(chunks), "file_type": file_type},
            ))
            await session.commit()
            INGESTION_DOCS.labels(status="indexed", file_type=file_type).inc()
            INGESTION_CHUNKS.inc(len(chunks))
            INGESTION_LATENCY.observe(time.perf_counter() - start)
            logger.info("Document indexed", extra={"document_id": str(document.id), "chunks": len(chunks), "ms": elapsed_ms})
        except Exception as exc:
            await session.rollback()
            message = exc.message if isinstance(exc, AppError) else "Unexpected error while processing the document"
            logger.exception("Ingestion failed", extra={"document_id": str(document_id)})
            failed = await session.get(Document, document_id)
            if failed is not None:
                failed.status = DocumentStatus.FAILED
                failed.error_message = message
                failed.chunk_count = 0
                await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
                session.add(UsageEvent(
                    user_id=owner_id, event_type="ingest", latency_ms=(time.perf_counter() - start) * 1000,
                    success=False, event_metadata={"document_id": str(document_id), "error": message},
                ))
                await session.commit()
            INGESTION_DOCS.labels(status="failed", file_type=file_type).inc()
        finally:
            # Corpus changed (or chunks were removed): invalidate this user's caches.
            await container.cache.invalidate_user(owner_id)


async def pending_documents(container: AppContainer) -> list[uuid.UUID]:
    """Documents left in PROCESSING by a crash (re-queued on start-up)."""
    async with container.db.session_factory() as session:
        rows = await session.execute(select(Document.id).where(Document.status == DocumentStatus.PROCESSING))
        return list(rows.scalars())
