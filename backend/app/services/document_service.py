"""Document upload, listing, deletion and chunk inspection (ownership enforced)."""

from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_cache import CacheService
from app.core.config import Settings
from app.core.exceptions import NotFoundError, PayloadTooLargeError, ValidationFailedError
from app.core.logging import get_logger
from app.ingestion.parsers import CONTENT_TYPES, detect_file_type
from app.models.document import Document, DocumentChunk, DocumentStatus

logger = get_logger(__name__)
_READ_CHUNK = 1024 * 1024
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


def sanitize_filename(name: str | None) -> str:
    """Strip directories and unsafe characters (the stored path never uses it)."""
    base = Path(name or "document").name
    base = _SAFE_NAME.sub("_", base).strip(" .") or "document"
    return base[:255]


async def _read_limited(upload: UploadFile, limit: int) -> bytes:
    """Read an upload in chunks, aborting as soon as the size limit is exceeded."""
    parts: list[bytes] = []
    size = 0
    while chunk := await upload.read(_READ_CHUNK):
        size += len(chunk)
        if size > limit:
            raise PayloadTooLargeError(f"File exceeds the {limit // (1024 * 1024)} MB upload limit")
        parts.append(chunk)
    return b"".join(parts)


async def save_upload(session: AsyncSession, settings: Settings, cache: CacheService, *,
                      owner_id: uuid.UUID, upload: UploadFile) -> tuple[Document, bool]:
    """Validate and store an upload. Returns ``(document, is_duplicate)``."""
    filename = sanitize_filename(upload.filename)
    data = await _read_limited(upload, settings.max_upload_size_bytes)
    if not data:
        raise ValidationFailedError("The uploaded file is empty")
    file_type = detect_file_type(filename, data[:8])
    digest = hashlib.sha256(data).hexdigest()

    existing = (await session.execute(
        select(Document).where(Document.owner_id == owner_id, Document.sha256 == digest)
    )).scalar_one_or_none()
    if existing is not None:
        return existing, True

    doc_id = uuid.uuid4()
    user_dir = settings.storage_dir / str(owner_id)
    path = user_dir / f"{doc_id}.{file_type}"
    await asyncio.to_thread(user_dir.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_bytes, data)
    document = Document(
        id=doc_id, owner_id=owner_id, filename=filename, file_type=file_type,
        content_type=CONTENT_TYPES[file_type], size_bytes=len(data), sha256=digest,
        storage_path=str(path), status=DocumentStatus.UPLOADED,
    )
    session.add(document)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        path.unlink(missing_ok=True)
        raise
    await session.refresh(document)
    logger.info("Document uploaded", extra={"document_id": str(doc_id), "file_type": file_type, "bytes": len(data)})
    return document, False


async def get_owned_document(session: AsyncSession, owner_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    """Fetch a document, returning 404 (not 403) for other users' documents to avoid leaking existence."""
    document = (await session.execute(
        select(Document).where(Document.id == document_id, Document.owner_id == owner_id)
    )).scalar_one_or_none()
    if document is None:
        raise NotFoundError("Document not found")
    return document


async def list_documents(session: AsyncSession, owner_id: uuid.UUID, *, limit: int, offset: int,
                         status: str | None = None) -> tuple[list[Document], int]:
    stmt = select(Document).where(Document.owner_id == owner_id)
    count_stmt = select(func.count()).select_from(Document).where(Document.owner_id == owner_id)
    if status:
        stmt = stmt.where(Document.status == status)
        count_stmt = count_stmt.where(Document.status == status)
    total = (await session.execute(count_stmt)).scalar_one()
    rows = await session.execute(stmt.order_by(Document.created_at.desc()).limit(limit).offset(offset))
    return list(rows.scalars()), total


async def delete_document(session: AsyncSession, cache: CacheService, owner_id: uuid.UUID,
                          document_id: uuid.UUID) -> None:
    """Delete a document, its chunks (FK cascade) and stored file; invalidate caches."""
    document = await get_owned_document(session, owner_id, document_id)
    path = Path(document.storage_path)
    await session.delete(document)
    await session.commit()
    try:
        await asyncio.to_thread(path.unlink, missing_ok=True)
    except OSError:
        logger.exception("Stored file could not be removed", extra={"document_id": str(document_id)})
    await cache.invalidate_user(owner_id)


async def list_chunks(session: AsyncSession, owner_id: uuid.UUID, document_id: uuid.UUID, *,
                      limit: int, offset: int) -> tuple[list[DocumentChunk], int]:
    await get_owned_document(session, owner_id, document_id)
    base = select(DocumentChunk).where(DocumentChunk.document_id == document_id, DocumentChunk.owner_id == owner_id)
    total = (await session.execute(
        select(func.count()).select_from(DocumentChunk).where(
            DocumentChunk.document_id == document_id, DocumentChunk.owner_id == owner_id)
    )).scalar_one()
    rows = await session.execute(base.order_by(DocumentChunk.chunk_index).limit(limit).offset(offset))
    return list(rows.scalars()), total
