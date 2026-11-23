"""Redis caching for the RAG pipeline.

Three caches with different safety properties:

1. **Query-embedding cache** — key = hash(model, text). Content-addressed and
   deterministic: a hit returns exactly what the caller would have computed, so
   sharing it across users leaks nothing.
2. **Retrieval-result cache** — key includes ``user_id`` and that user's *corpus
   version*. Uploading/ingesting/deleting a document increments the version, so all
   stale entries become unreachable in O(1) (and expire via TTL).
3. **Semantic answer cache** — per user + corpus version + pipeline-config
   fingerprint. A new question whose embedding has cosine >= threshold with a
   cached question reuses the cached answer. Only used for stateless questions
   (no conversation history), since history changes the right answer.

Redis failures never break a request: they are logged, counted
(``rag_cache_events_total{result="error"}``) and treated as misses.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import time
import uuid
from typing import Any

import numpy as np
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings
from app.core.logging import get_logger
from app.observability.metrics import CACHE_EVENTS

logger = get_logger(__name__)


def _h(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def fingerprint(payload: dict[str, Any]) -> str:
    """Stable hash of a JSON-serialisable configuration/params dict."""
    return _h(json.dumps(payload, sort_keys=True, default=str))[:24]


class CacheService:
    """Async Redis cache. Construct with ``redis=None`` to disable caching entirely."""

    STATS_KEY = "rag:stats:cache"

    def __init__(self, redis: Redis | None, settings: Settings) -> None:
        self.redis = redis if settings.cache_enabled else None
        self.settings = settings

    # ------------------------------------------------------------------ helpers
    async def _record(self, cache: str, result: str) -> None:
        CACHE_EVENTS.labels(cache=cache, result=result).inc()
        if self.redis is None or result == "error":
            return
        # Persistent stats are best-effort; the Prometheus counter above is always recorded.
        with contextlib.suppress(RedisError, OSError):
            await self.redis.hincrby(self.STATS_KEY, f"{cache}:{result}", 1)

    def _error(self, cache: str, op: str, exc: Exception) -> None:
        CACHE_EVENTS.labels(cache=cache, result="error").inc()
        logger.warning("Redis cache operation failed", extra={"cache": cache, "op": op, "error": type(exc).__name__})

    async def ping(self) -> bool:
        if self.redis is None:
            return False
        try:
            return bool(await self.redis.ping())
        except (RedisError, OSError):
            return False

    # ------------------------------------------------------------ embeddings
    async def get_embedding(self, model: str, text: str) -> np.ndarray | None:
        if self.redis is None:
            return None
        try:
            raw = await self.redis.get(f"rag:emb:{_h(model)[:16]}:{_h(text)}")
        except (RedisError, OSError) as exc:
            self._error("embedding", "get", exc)
            return None
        await self._record("embedding", "hit" if raw else "miss")
        return np.frombuffer(raw, dtype=np.float32).copy() if raw else None

    async def set_embedding(self, model: str, text: str, vector: np.ndarray) -> None:
        if self.redis is None:
            return
        try:
            await self.redis.set(
                f"rag:emb:{_h(model)[:16]}:{_h(text)}",
                np.asarray(vector, dtype=np.float32).tobytes(),
                ex=self.settings.embedding_cache_ttl_seconds,
            )
        except (RedisError, OSError) as exc:
            self._error("embedding", "set", exc)

    # -------------------------------------------------------- corpus version
    async def corpus_version(self, user_id: uuid.UUID) -> int:
        if self.redis is None:
            return 0
        try:
            return int(await self.redis.get(f"rag:ver:{user_id}") or 0)
        except (RedisError, OSError) as exc:
            self._error("version", "get", exc)
            return -1  # sentinel: forces a key that is never written while Redis is down

    async def invalidate_user(self, user_id: uuid.UUID) -> None:
        """Invalidate all retrieval and semantic-answer entries for a user."""
        if self.redis is None:
            return
        try:
            await self.redis.incr(f"rag:ver:{user_id}")
        except (RedisError, OSError) as exc:
            self._error("version", "incr", exc)

    # ------------------------------------------------------------- retrieval
    async def _retrieval_key(self, user_id: uuid.UUID, params: dict[str, Any]) -> str | None:
        version = await self.corpus_version(user_id)
        if version < 0:
            return None
        return f"rag:ret:{user_id}:v{version}:{fingerprint(params)}"

    async def get_retrieval(self, user_id: uuid.UUID, params: dict[str, Any]) -> dict[str, Any] | None:
        if self.redis is None:
            return None
        key = await self._retrieval_key(user_id, params)
        if key is None:
            return None
        try:
            raw = await self.redis.get(key)
        except (RedisError, OSError) as exc:
            self._error("retrieval", "get", exc)
            return None
        await self._record("retrieval", "hit" if raw else "miss")
        return json.loads(raw) if raw else None

    async def set_retrieval(self, user_id: uuid.UUID, params: dict[str, Any], results: dict[str, Any]) -> None:
        if self.redis is None:
            return
        key = await self._retrieval_key(user_id, params)
        if key is None:
            return
        try:
            await self.redis.set(key, json.dumps(results, default=str), ex=self.settings.retrieval_cache_ttl_seconds)
        except (RedisError, OSError) as exc:
            self._error("retrieval", "set", exc)

    # ---------------------------------------------------------- semantic cache
    async def _semantic_key(self, user_id: uuid.UUID, config_fp: str) -> str | None:
        version = await self.corpus_version(user_id)
        if version < 0:
            return None
        return f"rag:sem:{user_id}:v{version}:{config_fp}"

    async def semantic_lookup(
        self, user_id: uuid.UUID, config_fp: str, query_vector: np.ndarray
    ) -> tuple[dict[str, Any], float] | None:
        """Return ``(cached_response, similarity)`` for the most similar cached question."""
        if self.redis is None or not self.settings.semantic_cache_enabled:
            return None
        key = await self._semantic_key(user_id, config_fp)
        if key is None:
            return None
        try:
            entries = await self.redis.hgetall(key)
        except (RedisError, OSError) as exc:
            self._error("semantic", "get", exc)
            return None
        best: tuple[dict[str, Any], float] | None = None
        if entries:
            q = np.asarray(query_vector, dtype=np.float32)
            records = [json.loads(v) for v in entries.values()]
            matrix = np.stack([np.frombuffer(base64.b64decode(r["vector"]), dtype=np.float32) for r in records])
            sims = matrix @ q  # vectors are unit-normalised -> cosine similarity
            idx = int(np.argmax(sims))
            if float(sims[idx]) >= self.settings.semantic_cache_threshold:
                best = (records[idx]["response"], float(sims[idx]))
        await self._record("semantic", "hit" if best else "miss")
        return best

    async def semantic_store(
        self, user_id: uuid.UUID, config_fp: str, query: str, query_vector: np.ndarray, response: dict[str, Any]
    ) -> None:
        if self.redis is None or not self.settings.semantic_cache_enabled:
            return
        key = await self._semantic_key(user_id, config_fp)
        if key is None:
            return
        record = {
            "query": query,
            "vector": base64.b64encode(np.asarray(query_vector, dtype=np.float32).tobytes()).decode(),
            "response": response,
            "stored_at": time.time(),
        }
        try:
            if await self.redis.hlen(key) >= self.settings.semantic_cache_max_entries:
                return  # bounded memory; entries expire with the TTL
            await self.redis.hset(key, _h(query)[:16], json.dumps(record, default=str))
            await self.redis.expire(key, self.settings.semantic_cache_ttl_seconds)
        except (RedisError, OSError) as exc:
            self._error("semantic", "set", exc)

    # ------------------------------------------------------------ statistics
    async def stats(self) -> dict[str, dict[str, int | float]]:
        """Persistent hit/miss counters per cache with hit rates."""
        if self.redis is None:
            return {}
        try:
            raw = await self.redis.hgetall(self.STATS_KEY)
        except (RedisError, OSError) as exc:
            self._error("stats", "get", exc)
            return {}
        out: dict[str, dict[str, int | float]] = {}
        for field, value in raw.items():
            name = field.decode() if isinstance(field, bytes) else field
            cache, result = name.split(":", 1)
            out.setdefault(cache, {"hit": 0, "miss": 0})[result] = int(value)
        for v in out.values():
            total = v["hit"] + v["miss"]
            v["hit_rate"] = round(v["hit"] / total, 4) if total else 0.0
        return out

    # --------------------------------------------------- auth support (tokens)
    async def revoke_token(self, jti: str, ttl_seconds: int) -> None:
        if self.redis is None:
            return
        try:
            await self.redis.set(f"rag:revoked:{jti}", "1", ex=max(ttl_seconds, 1))
        except (RedisError, OSError) as exc:
            self._error("auth", "revoke", exc)

    async def is_token_revoked(self, jti: str) -> bool:
        if self.redis is None:
            return False
        try:
            return bool(await self.redis.exists(f"rag:revoked:{jti}"))
        except (RedisError, OSError) as exc:
            self._error("auth", "check", exc)
            return False

    async def hit_rate_limit(self, bucket: str, limit: int, window_seconds: int = 60) -> bool:
        """Fixed-window rate limiter. Returns True when the limit is exceeded."""
        if self.redis is None:
            return False
        key = f"rag:rl:{bucket}:{int(time.time() // window_seconds)}"
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                count, _ = await pipe.incr(key).expire(key, window_seconds + 1).execute()
            return int(count) > limit
        except (RedisError, OSError) as exc:
            self._error("ratelimit", "incr", exc)
            return False
