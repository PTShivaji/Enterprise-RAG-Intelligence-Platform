"""Usage analytics computed from persisted usage events (per user)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_cache import CacheService
from app.models.conversation import Conversation
from app.models.document import Document, DocumentChunk
from app.models.usage import UsageEvent


async def overview(session: AsyncSession, cache: CacheService, user_id: uuid.UUID) -> dict[str, Any]:
    docs_by_status = dict((await session.execute(
        select(Document.status, func.count()).where(Document.owner_id == user_id).group_by(Document.status)
    )).all())
    chunks = (await session.execute(
        select(func.count()).select_from(DocumentChunk).where(DocumentChunk.owner_id == user_id)
    )).scalar_one()
    conversations = (await session.execute(
        select(func.count()).select_from(Conversation).where(Conversation.user_id == user_id)
    )).scalar_one()
    q = (await session.execute(
        select(
            func.count(),
            func.avg(UsageEvent.latency_ms),
            func.percentile_cont(0.95).within_group(UsageEvent.latency_ms),
            func.sum(UsageEvent.prompt_tokens),
            func.sum(UsageEvent.completion_tokens),
            func.sum(UsageEvent.cost_usd),
            func.sum(cast(UsageEvent.cache_hit, Integer)),
        ).where(UsageEvent.user_id == user_id, UsageEvent.event_type.in_(["chat", "search"]))
    )).one()
    total_queries = int(q[0] or 0)
    recent = (await session.execute(
        select(UsageEvent).where(UsageEvent.user_id == user_id).order_by(UsageEvent.created_at.desc()).limit(10)
    )).scalars()
    return {
        "documents": {str(k.value if hasattr(k, "value") else k): v for k, v in docs_by_status.items()},
        "total_documents": sum(docs_by_status.values()),
        "total_chunks": chunks,
        "total_conversations": conversations,
        "total_queries": total_queries,
        "avg_latency_ms": round(float(q[1]), 2) if q[1] is not None else None,
        "p95_latency_ms": round(float(q[2]), 2) if q[2] is not None else None,
        "prompt_tokens": int(q[3] or 0),
        "completion_tokens": int(q[4] or 0),
        "cost_usd": round(float(q[5]), 6) if q[5] is not None else 0.0,
        "query_cache_hit_rate": round(int(q[6] or 0) / total_queries, 4) if total_queries else 0.0,
        "cache": await cache.stats(),  # global cache counters (no user data)
        "recent_activity": [
            {
                "event_type": e.event_type,
                "query": (e.query or "")[:120] or None,
                "latency_ms": round(e.latency_ms, 1),
                "success": e.success,
                "created_at": e.created_at.isoformat(),
            }
            for e in recent
        ],
    }


async def usage(session: AsyncSession, user_id: uuid.UUID, days: int) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=days)
    day = func.date_trunc("day", UsageEvent.created_at)
    rows = (await session.execute(
        select(
            day.label("day"),
            UsageEvent.event_type,
            func.count(),
            func.avg(UsageEvent.latency_ms),
            func.avg(UsageEvent.retrieval_ms),
            func.avg(UsageEvent.llm_ms),
            func.sum(UsageEvent.prompt_tokens + UsageEvent.completion_tokens),
        )
        .where(UsageEvent.user_id == user_id, UsageEvent.created_at >= since)
        .group_by(day, UsageEvent.event_type)
        .order_by(day)
    )).all()
    return {
        "days": days,
        "series": [
            {
                "day": r[0].date().isoformat(),
                "event_type": r[1],
                "count": r[2],
                "avg_latency_ms": round(float(r[3]), 2) if r[3] is not None else None,
                "avg_retrieval_ms": round(float(r[4]), 2) if r[4] is not None else None,
                "avg_llm_ms": round(float(r[5]), 2) if r[5] is not None else None,
                "tokens": int(r[6] or 0),
            }
            for r in rows
        ],
    }
