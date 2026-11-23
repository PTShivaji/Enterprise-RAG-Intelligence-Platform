"""Prometheus metrics for the RAG pipeline (exposed at ``/api/v1/metrics``)."""

from __future__ import annotations

from prometheus_client import Counter, Histogram

_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60)

HTTP_REQUESTS = Counter(
    "rag_http_requests_total", "HTTP requests", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "rag_http_request_seconds", "HTTP request latency", ["method", "route"], buckets=_LATENCY_BUCKETS
)
EMBEDDING_LATENCY = Histogram(
    "rag_embedding_seconds", "Embedding latency", ["kind"], buckets=_LATENCY_BUCKETS
)
RETRIEVAL_LATENCY = Histogram(
    "rag_retrieval_seconds", "Retrieval stage latency", ["stage"], buckets=_LATENCY_BUCKETS
)
LLM_LATENCY = Histogram(
    "rag_llm_seconds", "LLM generation latency", ["model", "outcome"], buckets=_LATENCY_BUCKETS
)
LLM_TOKENS = Counter("rag_llm_tokens_total", "LLM tokens", ["model", "kind"])
LLM_ERRORS = Counter("rag_llm_errors_total", "LLM provider errors", ["model", "error"])
CACHE_EVENTS = Counter("rag_cache_events_total", "Cache lookups", ["cache", "result"])
INGESTION_DOCS = Counter("rag_ingested_documents_total", "Ingestion outcomes", ["status", "file_type"])
INGESTION_CHUNKS = Counter("rag_ingested_chunks_total", "Chunks indexed")
INGESTION_LATENCY = Histogram(
    "rag_ingestion_seconds", "Document ingestion latency", buckets=_LATENCY_BUCKETS
)
ANSWERS = Counter("rag_answers_total", "Answer outcomes", ["outcome"])
