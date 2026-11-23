"""Liveness, readiness and Prometheus metrics."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.api.dependencies import ContainerDep, require_admin

router = APIRouter(tags=["Health & Observability"])


@router.get("/health")
async def health(container: ContainerDep) -> dict:
    """Liveness: the process is up and serving."""
    return {"status": "ok", "version": container.settings.app_version}


@router.get("/health/ready")
async def ready(container: ContainerDep) -> JSONResponse:
    """Readiness: database, pgvector, Redis and models are usable."""
    checks: dict[str, dict] = {}
    try:
        async with container.db.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            ext = (await conn.execute(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))).scalar()
            dim = (await conn.execute(text(
                "SELECT atttypmod FROM pg_attribute WHERE attrelid = 'document_chunks'::regclass AND attname = 'embedding'"
            ))).scalar()
        checks["database"] = {"ok": True}
        checks["pgvector"] = {"ok": ext is not None, "version": ext}
        checks["vector_dimension"] = {
            "ok": dim == container.embeddings.dimension, "column": dim, "model": container.embeddings.dimension,
        }
    except Exception as exc:
        checks["database"] = {"ok": False, "error": type(exc).__name__}
    redis_ok = await container.cache.ping()
    checks["redis"] = {"ok": redis_ok, "required": False}
    checks["embedding_model"] = {"ok": True, "name": container.embeddings.model_name}
    checks["reranker"] = {"ok": True, "name": container.reranker.name if container.reranker else None}
    critical = all(v.get("ok") for k, v in checks.items() if k != "redis")
    status = "ready" if critical and redis_ok else ("degraded" if critical else "not_ready")
    return JSONResponse(status_code=200 if critical else 503, content={"status": status, "checks": checks})


@router.get("/metrics", dependencies=[Depends(require_admin)], summary="Prometheus metrics (admin only)")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
