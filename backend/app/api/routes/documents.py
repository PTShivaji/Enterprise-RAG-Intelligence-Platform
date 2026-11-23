"""Document management and ingestion endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Query, UploadFile, status

from app.api.dependencies import ContainerDep, CurrentUser, RateLimited, SessionDep
from app.core.exceptions import ConflictError
from app.ingestion.pipeline import ingest_document
from app.models.document import DocumentStatus
from app.schemas.common import MessageResponse
from app.schemas.documents import (
    ChunkListResponse,
    ChunkResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentStatusResponse,
    DocumentUploadResponse,
    IngestRequest,
)
from app.services import document_service
from app.services.settings_service import chunking_config, get_user_settings

router = APIRouter(prefix="/documents", tags=["Documents"], dependencies=[RateLimited])


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload(
    background: BackgroundTasks,
    session: SessionDep,
    container: ContainerDep,
    user: CurrentUser,
    file: Annotated[UploadFile, File(description="PDF, DOCX or TXT")],
    auto_ingest: Annotated[bool, Query(description="Start ingestion immediately")] = True,
) -> DocumentUploadResponse:
    """Upload a document. Identical bytes already uploaded by this user are not re-stored."""
    document, duplicate = await document_service.save_upload(
        session, container.settings, container.cache, owner_id=user.id, upload=file
    )
    queued = False
    if auto_ingest and not duplicate:
        cfg = chunking_config(await get_user_settings(session, container.settings, user.id))
        background.add_task(ingest_document, container, document.id, cfg)
        queued = True
    return DocumentUploadResponse(
        document=DocumentResponse.model_validate(document), duplicate=duplicate, ingestion_queued=queued
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    session: SessionDep,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    status_filter: Annotated[DocumentStatus | None, Query(alias="status")] = None,
) -> DocumentListResponse:
    items, total = await document_service.list_documents(
        session, user.id, limit=limit, offset=offset, status=status_filter.value if status_filter else None
    )
    return DocumentListResponse(items=[DocumentResponse.model_validate(d) for d in items], total=total)


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> DocumentResponse:
    return DocumentResponse.model_validate(await document_service.get_owned_document(session, user.id, document_id))


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
async def document_status(document_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> DocumentStatusResponse:
    d = await document_service.get_owned_document(session, user.id, document_id)
    return DocumentStatusResponse(id=d.id, status=d.status.value, chunk_count=d.chunk_count,
                                  error_message=d.error_message, indexed_at=d.indexed_at)


@router.get("/{document_id}/chunks", response_model=ChunkListResponse)
async def document_chunks(
    document_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ChunkListResponse:
    items, total = await document_service.list_chunks(session, user.id, document_id, limit=limit, offset=offset)
    return ChunkListResponse(items=[ChunkResponse.model_validate(c) for c in items], total=total)


@router.post("/{document_id}/ingest", response_model=DocumentStatusResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest(
    document_id: uuid.UUID,
    background: BackgroundTasks,
    session: SessionDep,
    container: ContainerDep,
    user: CurrentUser,
    body: IngestRequest | None = None,
) -> DocumentStatusResponse:
    """(Re-)ingest a document, optionally with a different chunking configuration."""
    d = await document_service.get_owned_document(session, user.id, document_id)
    if d.status == DocumentStatus.PROCESSING:
        raise ConflictError("Document is already being processed")
    body = body or IngestRequest()
    user_settings = await get_user_settings(session, container.settings, user.id)
    cfg = chunking_config(user_settings, body.chunk_strategy, body.chunk_size_tokens, body.chunk_overlap_tokens)
    if cfg.chunk_size > container.embeddings.model.max_seq_length - 2:
        raise ConflictError("chunk_size_tokens exceeds the embedding model's maximum sequence length")
    d.status = DocumentStatus.PROCESSING
    await session.commit()
    background.add_task(ingest_document, container, d.id, cfg)
    return DocumentStatusResponse(id=d.id, status=d.status.value, chunk_count=d.chunk_count,
                                  error_message=None, indexed_at=d.indexed_at)


@router.delete("/{document_id}", response_model=MessageResponse)
async def delete(document_id: uuid.UUID, session: SessionDep, container: ContainerDep, user: CurrentUser) -> MessageResponse:
    await document_service.delete_document(session, container.cache, user.id, document_id)
    return MessageResponse(message="Document deleted")
