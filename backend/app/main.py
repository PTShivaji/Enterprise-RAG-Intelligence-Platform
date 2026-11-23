"""FastAPI application factory."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.middleware import RequestContextMiddleware, register_exception_handlers
from app.api.routes import analytics, auth, chat, documents, evaluation, health, search
from app.api.routes import settings as settings_routes
from app.core.config import BACKEND_DIR, Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.services.container import AppContainer

logger = get_logger(__name__)

API_DESCRIPTION = """
Enterprise Retrieval-Augmented Generation platform.

**Pipeline:** upload -> parse (PDF/DOCX/TXT) -> token-aware chunking -> embeddings (pgvector)
-> hybrid retrieval (vector + full-text, RRF) -> cross-encoder reranking -> context engineering
-> grounded generation (LiteLLM or local extractive) -> citation verification.

Authenticate with **Authorize** (email as username) or `POST /api/v1/auth/login`.
"""


def create_app(settings: Settings | None = None, container: AppContainer | None = None) -> FastAPI:
    """Build the app. Tests inject a pre-built ``container``."""
    settings = settings or get_settings()
    # Make provider API keys from backend/.env visible to LiteLLM (reads os.environ).
    load_dotenv(BACKEND_DIR / ".env", override=False)
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = container is None
        app.state.container = container or await AppContainer.create(settings)
        if owned:
            from app.ingestion.chunking import ChunkingConfig
            from app.ingestion.pipeline import ingest_document, pending_documents

            # Resume documents interrupted mid-ingestion by a crash/restart.
            stuck = await pending_documents(app.state.container)
            cfg = ChunkingConfig(settings.chunk_strategy, settings.chunk_size_tokens, settings.chunk_overlap_tokens)
            # Keep strong references: the event loop only holds weak refs to tasks.
            app.state.background_tasks = set()
            for doc_id in stuck:
                logger.warning("Re-queuing interrupted ingestion", extra={"document_id": str(doc_id)})
                task = asyncio.create_task(ingest_document(app.state.container, doc_id, cfg))
                app.state.background_tasks.add(task)
                task.add_done_callback(app.state.background_tasks.discard)
        try:
            yield
        finally:
            if owned:
                await app.state.container.close()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=API_DESCRIPTION,
        lifespan=lifespan,
        docs_url=f"{settings.api_prefix}/docs",
        redoc_url=f"{settings.api_prefix}/redoc",
        openapi_url=f"{settings.api_prefix}/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    for module in (health, auth, documents, search, chat, settings_routes, evaluation, analytics):
        app.include_router(module.router, prefix=settings.api_prefix)
    return app


app = create_app()
