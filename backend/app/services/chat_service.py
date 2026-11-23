"""Conversation persistence and conversation memory.

Memory = the most recent ``recent_turns`` exchanges plus up to ``relevant_turns``
*older* exchanges that are lexically relevant to the new question (so a long
conversation can recall an early topic without sending the whole transcript).

Document knowledge and conversation memory are kept separate: history goes into
the prompt as prior chat turns that the system prompt declares are not a source
of facts, while facts come only from retrieved ``<source>`` blocks.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.text import containment, content_terms
from app.models.conversation import Conversation, Message
from app.models.usage import UsageEvent
from app.rag.pipeline import RAGAnswer

_CITATION_MARKER = re.compile(r"\s*\[\d{1,3}(?:\s*,\s*\d{1,3})*\]")
RELEVANCE_MIN = 0.25


@dataclass(slots=True)
class Memory:
    history: list[dict[str, str]]
    prior_questions: list[str]


async def get_owned_conversation(session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID,
                                 *, with_messages: bool = False) -> Conversation:
    stmt = select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
    conversation = (await session.execute(stmt)).scalar_one_or_none()
    if conversation is None:
        raise NotFoundError("Conversation not found")
    if with_messages:
        await session.refresh(conversation, attribute_names=["messages"])
    return conversation


async def get_or_create_conversation(session: AsyncSession, user_id: uuid.UUID,
                                     conversation_id: uuid.UUID | None, first_message: str) -> Conversation:
    if conversation_id is not None:
        return await get_owned_conversation(session, user_id, conversation_id)
    title = re.sub(r"\s+", " ", first_message).strip()
    conversation = Conversation(user_id=user_id, title=(title[:77] + "...") if len(title) > 80 else title)
    session.add(conversation)
    await session.flush()
    return conversation


def _pairs(messages: list[Message]) -> list[tuple[Message, Message | None]]:
    pairs: list[tuple[Message, Message | None]] = []
    for i, msg in enumerate(messages):
        if msg.role == "user":
            nxt = messages[i + 1] if i + 1 < len(messages) and messages[i + 1].role == "assistant" else None
            pairs.append((msg, nxt))
    return pairs


async def load_memory(session: AsyncSession, conversation: Conversation, question: str, *,
                      recent_turns: int, relevant_turns: int, max_messages: int = 200) -> Memory:
    rows = await session.execute(
        select(Message).where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc()).limit(max_messages)
    )
    messages = list(reversed(list(rows.scalars())))
    pairs = _pairs(messages)
    recent = pairs[-recent_turns:] if recent_turns else []
    older = pairs[: len(pairs) - len(recent)]

    q_terms = content_terms(question)
    scored = []
    for idx, (u, a) in enumerate(older):
        text = u.content + " " + (a.content if a else "")
        score = containment(q_terms, set(content_terms(text)))
        if score >= RELEVANCE_MIN:
            scored.append((score, idx))
    relevant_idx = sorted(i for _, i in sorted(scored, reverse=True)[:relevant_turns])
    selected = [older[i] for i in relevant_idx] + recent

    history: list[dict[str, str]] = []
    for u, a in selected:
        history.append({"role": "user", "content": u.content})
        if a is not None:
            # Old [n] markers refer to *previous* source lists; strip them to avoid confusing the model.
            history.append({"role": "assistant", "content": _CITATION_MARKER.sub("", a.content)})
    return Memory(history=history, prior_questions=[u.content for u, _ in pairs])


async def persist_exchange(session: AsyncSession, conversation: Conversation, *, user_id: uuid.UUID,
                           question: str, answer: RAGAnswer) -> Message:
    session.add(Message(conversation_id=conversation.id, role="user", content=question))
    await session.flush()
    assistant = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=answer.answer,
        citations=answer.citations,
        message_metadata={
            "model": answer.model,
            "provider": answer.provider,
            "usage": answer.usage,
            "timings_ms": answer.timings_ms,
            "verification": answer.verification,
            "insufficient_evidence": answer.insufficient_evidence,
            "semantic_cache_hit": answer.semantic_cache_hit,
            "retrieval_query": answer.retrieval_query,
        },
    )
    session.add(assistant)
    conversation.updated_at = func.now()  # bump so recent conversations sort first
    session.add(UsageEvent(
        user_id=user_id,
        event_type="chat",
        query=question[:2000],
        latency_ms=answer.timings_ms.get("total", 0.0),
        retrieval_ms=answer.timings_ms.get("retrieval"),
        llm_ms=answer.timings_ms.get("generation"),
        prompt_tokens=int(answer.usage.get("prompt_tokens") or 0),
        completion_tokens=int(answer.usage.get("completion_tokens") or 0),
        cost_usd=answer.usage.get("cost_usd"),
        cache_hit=answer.semantic_cache_hit or bool(answer.retrieval.get("cache_hit")),
        model=answer.model,
        success=True,
        event_metadata={
            "insufficient_evidence": answer.insufficient_evidence,
            "citations": len(answer.citations),
            "grounded": answer.verification.get("grounded"),
        },
    ))
    await session.commit()
    await session.refresh(assistant)
    return assistant


async def list_conversations(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int, offset: int
) -> list[Conversation]:
    rows = await session.execute(
        select(Conversation).where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc()).limit(limit).offset(offset)
    )
    return list(rows.scalars())


async def delete_conversation(session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
    await get_owned_conversation(session, user_id, conversation_id)
    await session.execute(
        delete(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
    )
    await session.commit()
