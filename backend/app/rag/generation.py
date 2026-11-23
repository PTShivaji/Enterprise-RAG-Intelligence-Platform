"""LLM providers: LiteLLM (OpenAI / Anthropic / Gemini / Ollama ...) and a local extractive mode.

``LLMProvider`` is the only interface the RAG pipeline depends on.

* ``LiteLLMProvider``  — any model string LiteLLM understands. Hard timeout,
  provider-side retries (``num_retries``) for transient errors, streaming with
  usage reporting, cost estimation from LiteLLM's pricing table.
* ``LocalExtractiveProvider`` — the zero-cost, no-API-key default. It is NOT an
  LLM: it selects the most query-relevant *verbatim* sentences from the context
  using the embedding model (cosine) blended with lexical overlap, de-duplicates
  them with Maximal Marginal Relevance, and cites each one. Answers are therefore
  faithful by construction but not fluent/abstractive.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

import numpy as np

from app.core.config import Settings
from app.core.exceptions import LLMProviderError
from app.core.logging import get_logger
from app.core.text import containment, content_terms, split_sentences
from app.core.tokens import get_token_counter
from app.embeddings.service import EmbeddingService
from app.observability.metrics import LLM_ERRORS, LLM_LATENCY, LLM_TOKENS
from app.rag.types import INSUFFICIENT_EVIDENCE, GenerationRequest, GenerationResult, StreamDelta

logger = get_logger(__name__)

LOCAL_MODEL = "local"


class LLMProvider(ABC):
    provider_name: str

    @abstractmethod
    async def generate(self, request: GenerationRequest) -> GenerationResult: ...

    @abstractmethod
    def stream(self, request: GenerationRequest) -> AsyncIterator[StreamDelta]: ...

    async def complete_text(self, prompt: str, *, model: str, max_tokens: int = 200) -> str:
        """Plain completion for auxiliary tasks (query rewriting). Optional."""
        raise LLMProviderError("This provider does not support auxiliary completions")


# --------------------------------------------------------------------------- LiteLLM
def _classify_litellm_error(exc: Exception) -> str:
    name = type(exc).__name__
    for marker, label in (
        ("Timeout", "timeout"),
        ("Authentication", "auth"),
        ("RateLimit", "rate_limit"),
        ("NotFound", "model_not_found"),
        ("BadRequest", "bad_request"),
        ("ContextWindow", "context_window"),
        ("APIConnection", "connection"),
        ("ServiceUnavailable", "unavailable"),
    ):
        if marker in name:
            return label
    return "provider_error"


_USER_MESSAGES = {
    "timeout": "The language model did not respond in time. Please retry.",
    "auth": "The language model provider rejected the credentials. Check the API key configuration.",
    "rate_limit": "The language model provider is rate limiting requests. Please retry shortly.",
    "model_not_found": "The configured language model was not found at the provider.",
    "context_window": "The prompt exceeded the model's context window.",
    "connection": "Could not connect to the language model provider.",
    "unavailable": "The language model provider is temporarily unavailable.",
}


class LiteLLMProvider(LLMProvider):
    provider_name = "litellm"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.counter = get_token_counter()

    def _cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
        try:
            import litellm

            p, c = litellm.cost_per_token(model=model, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
            return round(float(p) + float(c), 8)
        except Exception:  # unknown model in pricing table (e.g. local Ollama)
            return None

    def _fail(self, model: str, exc: Exception, kind: str | None = None) -> LLMProviderError:
        kind = kind or _classify_litellm_error(exc)
        LLM_ERRORS.labels(model=model, error=kind).inc()
        logger.error("LLM call failed", extra={"model": model, "error_kind": kind, "error_type": type(exc).__name__})
        return LLMProviderError(_USER_MESSAGES.get(kind, "The language model request failed."), details={"kind": kind})

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        import litellm

        start = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                litellm.acompletion(
                    model=request.model,
                    messages=request.messages,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    timeout=self.settings.llm_timeout_seconds,
                    num_retries=self.settings.llm_max_retries,
                ),
                # Hard ceiling covering all retries.
                timeout=self.settings.llm_timeout_seconds * (self.settings.llm_max_retries + 1) + 5,
            )
        except TimeoutError as exc:
            LLM_LATENCY.labels(model=request.model, outcome="error").observe(time.perf_counter() - start)
            raise self._fail(request.model, exc, kind="timeout") from exc
        except Exception as exc:
            LLM_LATENCY.labels(model=request.model, outcome="error").observe(time.perf_counter() - start)
            raise self._fail(request.model, exc) from exc
        elapsed = time.perf_counter() - start
        LLM_LATENCY.labels(model=request.model, outcome="ok").observe(elapsed)
        text = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0) or sum(self.counter.count(m["content"]) for m in request.messages)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0) or self.counter.count(text)
        LLM_TOKENS.labels(model=request.model, kind="prompt").inc(prompt_tokens)
        LLM_TOKENS.labels(model=request.model, kind="completion").inc(completion_tokens)
        return GenerationResult(
            text=text,
            model=request.model,
            provider=self.provider_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=self._cost(request.model, prompt_tokens, completion_tokens),
            latency_ms=round(elapsed * 1000, 2),
        )

    async def stream(self, request: GenerationRequest) -> AsyncIterator[StreamDelta]:
        import litellm

        start = time.perf_counter()
        parts: list[str] = []
        usage = None
        try:
            response = await litellm.acompletion(
                model=request.model,
                messages=request.messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                timeout=self.settings.llm_timeout_seconds,
                num_retries=self.settings.llm_max_retries,
                stream=True,
                stream_options={"include_usage": True},
            )
            async for chunk in response:
                if getattr(chunk, "usage", None):
                    usage = chunk.usage
                if chunk.choices:
                    delta = chunk.choices[0].delta.content or ""
                    if delta:
                        parts.append(delta)
                        yield StreamDelta(text=delta)
        except Exception as exc:
            LLM_LATENCY.labels(model=request.model, outcome="error").observe(time.perf_counter() - start)
            raise self._fail(request.model, exc) from exc
        elapsed = time.perf_counter() - start
        LLM_LATENCY.labels(model=request.model, outcome="ok").observe(elapsed)
        text = "".join(parts)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0) or sum(self.counter.count(m["content"]) for m in request.messages)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0) or self.counter.count(text)
        LLM_TOKENS.labels(model=request.model, kind="prompt").inc(prompt_tokens)
        LLM_TOKENS.labels(model=request.model, kind="completion").inc(completion_tokens)
        yield StreamDelta(
            final=GenerationResult(
                text=text,
                model=request.model,
                provider=self.provider_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=self._cost(request.model, prompt_tokens, completion_tokens),
                latency_ms=round(elapsed * 1000, 2),
            )
        )

    async def complete_text(self, prompt: str, *, model: str, max_tokens: int = 200) -> str:
        result = await self.generate(
            GenerationRequest(question=prompt, sources=[], messages=[{"role": "user", "content": prompt}],
                              model=model, temperature=0.3, max_tokens=max_tokens)
        )
        return result.text


# ------------------------------------------------------------------ local extractive
class LocalExtractiveProvider(LLMProvider):
    """Extractive answerer used when no LLM is configured (see module docstring)."""

    provider_name = "local-extractive"

    def __init__(
        self,
        embeddings: EmbeddingService,
        *,
        max_sentences: int = 4,
        min_relevance: float = 0.35,
        mmr_lambda: float = 0.7,
    ) -> None:
        self.embeddings = embeddings
        self.max_sentences = max_sentences
        self.min_relevance = min_relevance
        self.mmr_lambda = mmr_lambda

    async def _compose(self, request: GenerationRequest) -> str:
        candidates: list[tuple[int, str]] = []  # (source index, sentence)
        for source in request.sources:
            for sentence in split_sentences(source.content):
                if 4 <= len(sentence.split()) <= 80:
                    candidates.append((source.index, sentence))
        if not candidates:
            return INSUFFICIENT_EVIDENCE

        texts = [request.question] + [s for _, s in candidates]
        vectors = await self.embeddings.embed_queries(texts)
        q_vec, s_vecs = vectors[0], vectors[1:]
        semantic = s_vecs @ q_vec
        q_terms = content_terms(request.question)
        lexical = np.array([containment(q_terms, set(content_terms(s))) for _, s in candidates])
        relevance = 0.75 * semantic + 0.25 * lexical

        if float(relevance.max()) < self.min_relevance:
            return INSUFFICIENT_EVIDENCE

        # Maximal Marginal Relevance: relevant AND non-redundant sentences.
        selected: list[int] = []
        remaining = set(range(len(candidates)))
        while remaining and len(selected) < self.max_sentences:
            best, best_score = None, -1e9
            for i in remaining:
                redundancy = max((float(s_vecs[i] @ s_vecs[j]) for j in selected), default=0.0)
                score = self.mmr_lambda * relevance[i] - (1 - self.mmr_lambda) * redundancy
                if score > best_score:
                    best, best_score = i, score
            assert best is not None
            if relevance[best] < self.min_relevance * 0.85 and selected:
                break
            selected.append(best)
            remaining.discard(best)

        # Present in source order (source rank, then position) for readability.
        selected.sort()
        lines = [f"- {candidates[i][1]} [{candidates[i][0]}]" for i in selected]
        return "Based on your documents:\n\n" + "\n".join(lines)

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        start = time.perf_counter()
        text = await self._compose(request)
        elapsed = time.perf_counter() - start
        LLM_LATENCY.labels(model=LOCAL_MODEL, outcome="ok").observe(elapsed)
        return GenerationResult(
            text=text, model=LOCAL_MODEL, provider=self.provider_name,
            prompt_tokens=0, completion_tokens=0, cost_usd=0.0, latency_ms=round(elapsed * 1000, 2),
        )

    async def stream(self, request: GenerationRequest) -> AsyncIterator[StreamDelta]:
        result = await self.generate(request)
        # The answer is computed in one step; it is streamed word-by-word so the
        # client exercises the same streaming protocol as with a real LLM.
        words = result.text.split(" ")
        for i, word in enumerate(words):
            yield StreamDelta(text=word if i == 0 else " " + word)
            await asyncio.sleep(0)
        yield StreamDelta(final=result)


class ProviderRouter:
    """Selects the provider for a model string ("local" -> extractive, else LiteLLM)."""

    def __init__(self, settings: Settings, embeddings: EmbeddingService) -> None:
        self.settings = settings
        self.local = LocalExtractiveProvider(embeddings)
        self.litellm = LiteLLMProvider(settings)

    def for_model(self, model: str) -> LLMProvider:
        return self.local if model == LOCAL_MODEL else self.litellm

    def is_local(self, model: str) -> bool:
        return model == LOCAL_MODEL
