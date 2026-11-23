"""Chat (grounded Q&A) and conversation endpoints, including SSE streaming."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.api.dependencies import ContainerDep, CurrentUser, RateLimited, SessionDep
from app.core.exceptions import AppError, ValidationFailedError
from app.core.logging import get_logger
from app.models.user import User
from app.rag.pipeline import RAGAnswer, RAGOptions
from app.schemas.common import MessageResponse
from app.schemas.rag import ChatRequest, ChatResponse, ConversationDetail, ConversationSummary
from app.services import chat_service
from app.services.container import AppContainer
from app.services.settings_service import get_user_settings, rag_options, retrieval_options, to_filters

logger = get_logger(__name__)
router = APIRouter(tags=["Chat"], dependencies=[RateLimited])


async def _options(session, container: AppContainer, user: User, body: ChatRequest) -> RAGOptions:
    prefs = await get_user_settings(session, container.settings, user.id)
    model = body.model or prefs.llm_model
    if model not in container.settings.llm_allowed_models:
        raise ValidationFailedError(f"Model '{model}' is not allowed",
                                    details={"allowed": container.settings.llm_allowed_models})
    retrieval = retrieval_options(
        prefs, rerank_available=container.reranker is not None, filters=to_filters(body.filters),
        top_k=body.top_k, mode=body.search_mode, rerank=body.rerank,
    )
    return rag_options(prefs, retrieval, model)


def _response(conversation_id: uuid.UUID, message_id: uuid.UUID, a: RAGAnswer) -> ChatResponse:
    return ChatResponse(
        conversation_id=conversation_id, message_id=message_id, answer=a.answer, citations=a.citations,
        insufficient_evidence=a.insufficient_evidence, verification=a.verification, model=a.model,
        provider=a.provider, usage=a.usage, timings_ms=a.timings_ms, retrieval=a.retrieval, context=a.context,
        semantic_cache_hit=a.semantic_cache_hit, retrieval_query=a.retrieval_query,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, session: SessionDep, container: ContainerDep, user: CurrentUser) -> ChatResponse:
    """Ask a question; returns a grounded answer with verified citations (separate from the text)."""
    options = await _options(session, container, user, body)
    conversation = await chat_service.get_or_create_conversation(session, user.id, body.conversation_id, body.message)
    memory = await chat_service.load_memory(
        session, conversation, body.message,
        recent_turns=container.settings.history_recent_turns,
        relevant_turns=container.settings.history_relevant_turns,
    )
    answer = await container.pipeline.answer(
        session, owner_id=user.id, question=body.message, options=options,
        history=memory.history, prior_questions=memory.prior_questions,
    )
    message = await chat_service.persist_exchange(session, conversation, user_id=user.id, question=body.message, answer=answer)
    return _response(conversation.id, message.id, answer)


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/chat/stream", response_class=StreamingResponse,
             responses={200: {"content": {"text/event-stream": {}},
                              "description": "SSE events: conversation, sources, token*, done | error"}})
async def chat_stream(body: ChatRequest, session: SessionDep, container: ContainerDep, user: CurrentUser) -> StreamingResponse:
    """Server-Sent Events stream. The ``done`` event carries the verified answer and citations."""
    options = await _options(session, container, user, body)
    conversation = await chat_service.get_or_create_conversation(session, user.id, body.conversation_id, body.message)
    await session.commit()
    memory = await chat_service.load_memory(
        session, conversation, body.message,
        recent_turns=container.settings.history_recent_turns,
        relevant_turns=container.settings.history_relevant_turns,
    )

    async def events() -> AsyncIterator[str]:
        yield _sse("conversation", {"conversation_id": str(conversation.id)})
        try:
            async for event in container.pipeline.stream(
                session, owner_id=user.id, question=body.message, options=options,
                history=memory.history, prior_questions=memory.prior_questions,
            ):
                if event["type"] == "done":
                    answer = RAGAnswer(**event["answer"])
                    message = await chat_service.persist_exchange(
                        session, conversation, user_id=user.id, question=body.message, answer=answer
                    )
                    yield _sse("done", _response(conversation.id, message.id, answer).model_dump(mode="json"))
                else:
                    yield _sse(event["type"], {k: v for k, v in event.items() if k != "type"})
        except AppError as exc:
            yield _sse("error", {"error": exc.code, "message": exc.message})
        except Exception:
            logger.exception("Streaming chat failed")
            yield _sse("error", {"error": "internal_error", "message": "An unexpected error occurred"})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/conversations", response_model=list[ConversationSummary])
async def conversations(session: SessionDep, user: CurrentUser,
                        limit: Annotated[int, Query(ge=1, le=200)] = 50,
                        offset: Annotated[int, Query(ge=0)] = 0) -> list[ConversationSummary]:
    items = await chat_service.list_conversations(session, user.id, limit=limit, offset=offset)
    return [ConversationSummary.model_validate(c) for c in items]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def conversation(conversation_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> ConversationDetail:
    conv = await chat_service.get_owned_conversation(session, user.id, conversation_id, with_messages=True)
    return ConversationDetail.model_validate(conv)


@router.delete("/conversations/{conversation_id}", response_model=MessageResponse)
async def delete_conversation(conversation_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> MessageResponse:
    await chat_service.delete_conversation(session, user.id, conversation_id)
    return MessageResponse(message="Conversation deleted")
