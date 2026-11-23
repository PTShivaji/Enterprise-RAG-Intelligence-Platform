"""Search Explorer / Retrieval Debugger endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.dependencies import ContainerDep, CurrentUser, RateLimited, SessionDep
from app.models.usage import UsageEvent
from app.schemas.rag import SearchHistoryItem, SearchRequest, SearchResponse, SearchResultItem
from app.services.settings_service import get_user_settings, retrieval_options, to_filters

router = APIRouter(prefix="/search", tags=["Search"], dependencies=[RateLimited])


@router.post("", response_model=SearchResponse)
async def search(body: SearchRequest, session: SessionDep, container: ContainerDep, user: CurrentUser) -> SearchResponse:
    """Run retrieval only (no generation). ``debug=true`` returns every pipeline stage."""
    prefs = await get_user_settings(session, container.settings, user.id)
    options = retrieval_options(
        prefs,
        rerank_available=container.reranker is not None,
        filters=to_filters(body.filters),
        top_k=body.top_k,
        mode=body.search_mode,
        rerank=body.rerank,
        similarity_threshold=body.similarity_threshold,
        query_expansion=body.query_expansion,
    )
    result = await container.retriever.retrieve(
        session, owner_id=user.id, query=body.query, options=options, llm_model=prefs.llm_model, debug=body.debug
    )
    session.add(UsageEvent(
        user_id=user.id, event_type="search", query=body.query[:2000],
        latency_ms=result.timings_ms.get("total", 0.0), retrieval_ms=result.timings_ms.get("total"),
        cache_hit=result.cache_hit, success=True,
        event_metadata={"results": len(result.chunks), "mode": options.mode, "rerank": options.rerank},
    ))
    await session.commit()
    return SearchResponse(
        query=result.query,
        search_mode=options.mode,
        reranked=options.rerank,
        results=[SearchResultItem(**{k: v for k, v in c.to_dict().items() if k not in ("char_start", "char_end")})
                 for c in result.chunks],
        expanded_terms=result.expanded_terms,
        query_variants=result.query_variants,
        cache_hit=result.cache_hit,
        embedding_cache_hit=result.embedding_cache_hit,
        candidates_considered=result.candidates_considered,
        timings_ms=result.timings_ms,
        stages=result.stages if body.debug else None,
    )


@router.get("/history", response_model=list[SearchHistoryItem])
async def history(session: SessionDep, user: CurrentUser,
                  limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[SearchHistoryItem]:
    rows = await session.execute(
        select(UsageEvent).where(UsageEvent.user_id == user.id, UsageEvent.event_type == "search")
        .order_by(UsageEvent.created_at.desc()).limit(limit)
    )
    return [
        SearchHistoryItem(id=e.id, query=e.query, latency_ms=e.latency_ms,
                          results=e.event_metadata.get("results"), cache_hit=e.cache_hit, created_at=e.created_at)
        for e in rows.scalars()
    ]
