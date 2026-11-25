"""LLM provider failure handling, local extractive mode, Redis caching and security primitives."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import numpy as np
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.cache.redis_cache import CacheService
from app.core.config import Settings
from app.core.exceptions import AuthenticationError, LLMProviderError
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.embeddings.hash_embedding import HashEmbedding
from app.embeddings.service import EmbeddingService
from app.evaluation import metrics as m
from app.rag.generation import LiteLLMProvider, LocalExtractiveProvider
from app.rag.types import INSUFFICIENT_EVIDENCE, ContextSource, GenerationRequest

SETTINGS = Settings(llm_timeout_seconds=1, llm_max_retries=0, jwt_secret_key="x" * 40)


def req(sources: list[ContextSource] | None = None, model: str = "gpt-4o-mini") -> GenerationRequest:
    return GenerationRequest(question="How many days of annual leave?", sources=sources or [],
                             messages=[{"role": "user", "content": "hi"}], model=model)


def src(i: int, text: str) -> ContextSource:
    return ContextSource(index=i, chunk_id=f"c{i}", chunk_ids=[f"c{i}"], document_id="d", filename="f.txt",
                         content=text, page_number=None, page_end=None, section=None, token_count=10)


# ----------------------------------------------------------------- LiteLLM provider
class Timeout(Exception): ...


class AuthenticationFailure(Exception): ...


@pytest.mark.parametrize(("exc", "kind"), [(Timeout("t"), "timeout"), (AuthenticationFailure("bad key"), "auth"),
                                           (RuntimeError("boom"), "provider_error")])
async def test_litellm_errors_become_safe_provider_errors(monkeypatch, exc: Exception, kind: str) -> None:
    import litellm

    async def fail(**_):
        raise exc

    monkeypatch.setattr(litellm, "acompletion", fail)
    with pytest.raises(LLMProviderError) as info:
        await LiteLLMProvider(SETTINGS).generate(req())
    assert info.value.details["kind"] == kind
    assert "bad key" not in info.value.message  # provider internals never leak to clients


async def test_litellm_hard_timeout(monkeypatch) -> None:
    import asyncio

    import litellm

    async def hang(**_):
        await asyncio.sleep(30)

    monkeypatch.setattr(litellm, "acompletion", hang)
    settings = Settings(llm_timeout_seconds=0.05, llm_max_retries=0)
    settings.llm_timeout_seconds = 0.05
    start = time.perf_counter()
    with pytest.raises(LLMProviderError) as info:
        provider = LiteLLMProvider(settings)
        provider.settings = SimpleNamespace(llm_timeout_seconds=-4.9, llm_max_retries=0)  # ceiling = 0.1s
        await provider.generate(req())
    assert info.value.details["kind"] == "timeout"
    assert time.perf_counter() - start < 5


async def test_litellm_success_reports_usage(monkeypatch) -> None:
    import litellm

    async def ok(**kwargs):
        assert kwargs["num_retries"] == 0 and kwargs["timeout"] == 1
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Employees get 22 days [1]."))],
            usage=SimpleNamespace(prompt_tokens=120, completion_tokens=9),
        )

    monkeypatch.setattr(litellm, "acompletion", ok)
    result = await LiteLLMProvider(SETTINGS).generate(req())
    assert (result.prompt_tokens, result.completion_tokens) == (120, 9)
    assert result.cost_usd is not None and result.cost_usd > 0  # gpt-4o-mini is in LiteLLM's price table


async def test_litellm_streaming_yields_deltas_then_final(monkeypatch) -> None:
    import litellm

    async def stream(**_):
        async def gen():
            for piece in ["Employees ", "get ", "22 days [1]."]:
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=piece))], usage=None)
            yield SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=50, completion_tokens=6))
        return gen()

    monkeypatch.setattr(litellm, "acompletion", stream)
    deltas = [d async for d in LiteLLMProvider(SETTINGS).stream(req())]
    assert "".join(d.text for d in deltas if d.final is None) == "Employees get 22 days [1]."
    assert deltas[-1].final.completion_tokens == 6


# ------------------------------------------------------------- local extractive mode
async def test_local_extractive_answers_with_verbatim_cited_sentences() -> None:
    emb = EmbeddingService(HashEmbedding(384), Settings())
    provider = LocalExtractiveProvider(emb, min_relevance=0.2)
    sources = [src(1, "The cafeteria opens at 8am. Annual leave is 22 days for employees with two years of service."),
               src(2, "Inverter fans need cleaning.")]
    result = await provider.generate(req(sources, model="local"))
    assert "Annual leave is 22 days for employees with two years of service. [1]" in result.text
    assert "Inverter" not in result.text
    assert result.prompt_tokens == 0 and result.cost_usd == 0.0


async def test_local_extractive_abstains_without_relevant_evidence() -> None:
    emb = EmbeddingService(HashEmbedding(384), Settings())
    result = await LocalExtractiveProvider(emb).generate(req([src(1, "Inverter fans need cleaning every month.")], "local"))
    assert result.text == INSUFFICIENT_EVIDENCE


# ------------------------------------------------------------------------- caching
@pytest.fixture
async def cache(redis_client) -> CacheService:
    return CacheService(redis_client, Settings(semantic_cache_threshold=0.95))


async def test_embedding_cache_roundtrip_and_metrics(cache: CacheService) -> None:
    vec = np.arange(4, dtype=np.float32)
    assert await cache.get_embedding("m", "q") is None
    await cache.set_embedding("m", "q", vec)
    assert np.array_equal(await cache.get_embedding("m", "q"), vec)
    stats = await cache.stats()
    assert stats["embedding"] == {"hit": 1, "miss": 1, "hit_rate": 0.5}


async def test_retrieval_cache_is_user_scoped_and_invalidated(cache: CacheService) -> None:
    alice, bob = uuid.uuid4(), uuid.uuid4()
    params = {"q": "leave policy"}
    await cache.set_retrieval(alice, params, {"chunks": [{"secret": "alice-only"}]})
    assert (await cache.get_retrieval(alice, params))["chunks"][0]["secret"] == "alice-only"
    assert await cache.get_retrieval(bob, params) is None  # same query, other user: miss
    await cache.invalidate_user(alice)  # e.g. a document was deleted
    assert await cache.get_retrieval(alice, params) is None


async def test_semantic_cache_threshold_and_isolation(cache: CacheService) -> None:
    alice, bob = uuid.uuid4(), uuid.uuid4()
    v = np.zeros(8, dtype=np.float32)
    v[0] = 1.0
    await cache.semantic_store(alice, "cfg", "leave?", v, {"answer": "22 days"})
    near = np.array([0.99, 0.141, 0, 0, 0, 0, 0, 0], dtype=np.float32)
    near /= np.linalg.norm(near)
    hit = await cache.semantic_lookup(alice, "cfg", near)
    assert hit is not None and hit[0]["answer"] == "22 days" and hit[1] >= 0.95
    far = np.array([0.7, 0.714, 0, 0, 0, 0, 0, 0], dtype=np.float32)
    assert await cache.semantic_lookup(alice, "cfg", far / np.linalg.norm(far)) is None
    assert await cache.semantic_lookup(bob, "cfg", v) is None
    assert await cache.semantic_lookup(alice, "other-config", v) is None
    await cache.invalidate_user(alice)
    assert await cache.semantic_lookup(alice, "cfg", v) is None


async def test_redis_outage_degrades_to_cache_miss() -> None:
    class DownPipeline:
        """Mirrors redis-py: building a pipeline is sync; failure surfaces on execute()."""

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc) -> None:
            return None

        def __getattr__(self, name):
            if name == "execute":
                async def fail():
                    raise RedisConnectionError("down")
                return fail
            return lambda *a, **k: self

    class DownRedis:
        def pipeline(self, *a, **k) -> DownPipeline:
            return DownPipeline()

        def __getattr__(self, name):
            async def fail(*a, **k):
                raise RedisConnectionError("down")
            return fail

    cache = CacheService(DownRedis(), Settings())  # type: ignore[arg-type]
    assert await cache.get_embedding("m", "q") is None
    await cache.set_embedding("m", "q", np.ones(3, dtype=np.float32))
    assert await cache.get_retrieval(uuid.uuid4(), {"q": 1}) is None
    assert await cache.hit_rate_limit("k", 1) is False
    assert await cache.ping() is False


async def test_rate_limiter(cache: CacheService) -> None:
    results = [await cache.hit_rate_limit("user:x", 3) for _ in range(5)]
    assert results == [False, False, False, True, True]


# ------------------------------------------------------------------------ security
def test_password_hashing() -> None:
    h = hash_password("Sup3r-secret")
    assert h != "Sup3r-secret" and verify_password("Sup3r-secret", h)
    assert not verify_password("wrong", h)
    long_pw = "a1" * 60  # > 72 bytes is pre-hashed, not truncated
    assert verify_password(long_pw, hash_password(long_pw)) and not verify_password(long_pw[:72], hash_password(long_pw))


def test_jwt_roundtrip_tamper_and_expiry() -> None:
    uid = uuid.uuid4()
    token, expires = create_access_token(uid, "admin", SETTINGS)
    payload = decode_access_token(token, SETTINGS)
    assert payload.user_id == uid and payload.role == "admin" and expires == 3600
    with pytest.raises(AuthenticationError):
        decode_access_token(token, Settings(jwt_secret_key="y" * 40))
    expired = jwt.encode({"sub": str(uid), "jti": "j", "type": "access",
                          "exp": datetime.now(UTC) - timedelta(seconds=5)}, SETTINGS.jwt_secret_key, algorithm="HS256")
    with pytest.raises(AuthenticationError, match="expired"):
        decode_access_token(expired, SETTINGS)
    none_alg = jwt.encode({"sub": str(uid), "jti": "j", "type": "access",
                           "exp": datetime.now(UTC) + timedelta(minutes=5)}, key="", algorithm="none")
    with pytest.raises(AuthenticationError):
        decode_access_token(none_alg, SETTINGS)


def test_production_rejects_insecure_config() -> None:
    insecure = "change-me-to-a-long-random-string-at-least-32-chars"
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(_env_file=None, environment="production", jwt_secret_key=insecure)
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(_env_file=None, environment="production", jwt_secret_key="short")
    with pytest.raises(ValueError, match="CORS"):
        Settings(_env_file=None, environment="production", jwt_secret_key="z" * 40, cors_origins=["*"])


# --------------------------------------------------------------- evaluation metrics
def test_retrieval_metrics() -> None:
    evidence = ["22 days of paid annual leave", "carried over to the next year"]
    retrieved = [
        "Cafeteria opening hours are 8am to 4pm.",
        "Employees receive 22 days of paid annual leave per year.",
        "Up to 5 days may be carried over to the next year.",
    ]
    res = m.retrieval_metrics(retrieved, evidence, k=3)
    assert res["precision_at_k"] == pytest.approx(2 / 3)
    assert res["recall_at_k"] == 1.0
    assert res["mrr"] == 0.5
    assert res["hit_at_k"] == 1.0
    assert 0 < res["ndcg_at_k"] < 1
    assert m.retrieval_metrics(retrieved, evidence, k=1)["recall_at_k"] == 0.0


def test_generation_proxies() -> None:
    ctx = ["Employees receive 22 days of paid annual leave per year."]
    assert m.faithfulness("Employees receive 22 days of paid annual leave [1].", ctx) == 1.0
    assert m.faithfulness("The company offers free helicopter rides to staff.", ctx) == 0.0
    assert m.answer_term_recall("They get 22 days of annual leave.", "22 days annual leave") == 1.0
    assert m.latency_summary([10, 20, 30, 40]) == {"mean": 25.0, "p50": 25.0, "p95": 38.5}
