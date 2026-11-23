"""Shared fixtures.

* Unit tests need nothing external.
* Integration tests use the real PostgreSQL + pgvector test database
  (``TEST_DATABASE_URL``, migrated with Alembic) — never SQLite — and are skipped
  with a clear reason if it is unreachable.
* Redis is the real compose service on isolated DB index 15. Embeddings use the
  deterministic hash model and the reranker a lexical-overlap reranker, so tests
  are fast and reproducible.
  Real models are exercised separately under the ``models`` marker.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

os.environ.setdefault("ENVIRONMENT", "test")
os.environ["LOG_JSON"] = "false"
os.environ["LOG_LEVEL"] = "WARNING"

import httpx  # noqa: E402
import pytest  # noqa: E402
from redis.asyncio import Redis  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import Settings, get_settings  # noqa: E402
from app.database.session import Database  # noqa: E402
from app.embeddings.hash_embedding import HashEmbedding  # noqa: E402
from app.retrieval.reranker import LexicalOverlapReranker  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    base = get_settings()
    storage = Path(tempfile.mkdtemp(prefix="rag-test-storage-"))
    return Settings(
        environment="test",
        database_url=base.test_database_url,
        embedding_provider="hash",
        storage_dir=storage,
        admin_emails=["admin@example.com"],
        rate_limit_per_minute=10_000,
        auth_rate_limit_per_minute=10_000,
        llm_default_model="local",
        reranker_enabled=True,
        similarity_threshold=0.0,
        rerank_min_score=-20.0,
        semantic_cache_enabled=True,
        chunk_size_tokens=40,  # small chunks so multi-page fixtures yield page-local chunks
        chunk_overlap_tokens=8,
        log_json=False,
        log_level="WARNING",
    )


@pytest.fixture(scope="session")
async def database(test_settings: Settings) -> AsyncIterator[Database]:
    db = Database(test_settings.database_url, pool_size=5, max_overflow=5)
    try:
        async with db.engine.connect() as conn:
            exists = (await conn.execute(text("SELECT to_regclass('public.document_chunks')"))).scalar()
    except Exception as exc:  # pragma: no cover - environment dependent
        await db.dispose()
        pytest.skip(f"Test database unavailable ({type(exc).__name__}). Start it with: docker compose up -d postgres")
    if exists is None:  # pragma: no cover
        await db.dispose()
        pytest.skip("Test database is not migrated. Run: alembic -x db_url=<TEST_DATABASE_URL> upgrade head")
    yield db
    await db.dispose()


@pytest.fixture
async def clean_db(database: Database) -> Database:
    async with database.engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE users, documents, document_chunks, conversations, messages, "
            "evaluation_runs, usage_events, user_settings RESTART IDENTITY CASCADE"
        ))
    return database


TEST_REDIS_DB = 15


@pytest.fixture
async def redis_client(test_settings: Settings) -> AsyncIterator[Redis]:
    """Real Redis (the compose service) on an isolated DB index, flushed around each test.

    fakeredis 2.40 is incompatible with redis-py 8.2 (it introspects ``__init__.__closure__``),
    and testing against real Redis is more faithful anyway.
    """
    url = test_settings.redis_url.rsplit("/", 1)[0] + f"/{TEST_REDIS_DB}"
    client = Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)
    try:
        await client.ping()
    except Exception as exc:  # pragma: no cover - environment dependent
        await client.aclose()
        pytest.skip(f"Redis unavailable ({type(exc).__name__}). Start it with: docker compose up -d redis")
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def container(test_settings: Settings, clean_db: Database, redis_client: Redis):  # noqa: ANN201
    from app.services.container import AppContainer

    c = await AppContainer.create(
        test_settings,
        db=clean_db,
        redis=redis_client,
        embedding_model=HashEmbedding(test_settings.embedding_dimension),
        reranker=LexicalOverlapReranker(),
    )
    yield c  # the session-scoped Database is disposed by its own fixture


@pytest.fixture
async def client(container, test_settings: Settings) -> AsyncIterator[httpx.AsyncClient]:  # noqa: ANN001
    from app.main import create_app

    app = create_app(test_settings, container=container)
    app.state.container = container  # ASGITransport does not run the lifespan
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1", timeout=60) as ac:
        yield ac


async def register_and_login(client: httpx.AsyncClient, email: str | None = None,
                             password: str = "Passw0rd!x") -> dict[str, str]:
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    r = await client.post("/auth/register", json={"email": email, "password": password, "full_name": "Test User"})
    assert r.status_code == 201, r.text
    r = await client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
async def auth_headers(client: httpx.AsyncClient) -> dict[str, str]:
    return await register_and_login(client)
