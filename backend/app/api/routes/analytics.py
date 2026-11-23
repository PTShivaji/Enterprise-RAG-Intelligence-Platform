"""Analytics endpoints (scoped to the current user)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.api.dependencies import ContainerDep, CurrentUser, RateLimited, SessionDep
from app.services import analytics_service

router = APIRouter(prefix="/analytics", tags=["Analytics"], dependencies=[RateLimited])


@router.get("/overview")
async def overview(session: SessionDep, container: ContainerDep, user: CurrentUser) -> dict[str, Any]:
    """Documents, chunks, queries, latency (avg/p95), tokens, cost and cache hit rates."""
    return await analytics_service.overview(session, container.cache, user.id)


@router.get("/usage")
async def usage(session: SessionDep, user: CurrentUser,
                days: Annotated[int, Query(ge=1, le=365)] = 30) -> dict[str, Any]:
    """Daily time series of queries, latency breakdown and tokens."""
    return await analytics_service.usage(session, user.id, days)
