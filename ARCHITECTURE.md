# Architecture

This document describes how the platform is put together and why. For measured behaviour see [docs/EVALUATION.md](docs/EVALUATION.md); for the AI design rationale see [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md).

## 1. Layers

```
┌───────────────────────────────────────────────────────────────────────────┐
│ API layer (FastAPI)          app/api                                       │
│   routes · JWT dependencies · rate limiting · request-id middleware ·      │
│   safe error envelope · SSE streaming · OpenAPI docs                       │
├───────────────────────────────────────────────────────────────────────────┤
│ Services                     app/services                                  │
│   auth · documents · settings · conversation memory · analytics ·          │
│   AppContainer (dependency wiring, built once in the lifespan)             │
├──────────────┬──────────────┬───────────────┬──────────────┬──────────────┤
│ Ingestion    │ Embeddings   │ Retrieval     │ RAG          │ Evaluation   │
│ parsers      │ model ABC    │ vector (HNSW) │ context      │ metrics      │
│ cleaning     │ ST / hash    │ keyword (FTS) │ prompt       │ runner       │
│ chunking     │ service      │ RRF fusion    │ generation   │ datasets     │
│ metadata     │ (cache,      │ rerank        │ citations    │              │
│ pipeline     │  guards)     │ query proc.   │ pipeline     │              │
├──────────────┴──────────────┴───────────────┴──────────────┴──────────────┤
│ Infrastructure: PostgreSQL 16 + pgvector 0.8 · Redis 7 · Prometheus client │
└───────────────────────────────────────────────────────────────────────────┘
```

Dependencies point downward only. The RAG core (`retrieval/`, `rag/`) knows nothing about HTTP or persistence of conversations; the API and services layers compose it. `AppContainer` is built once at start-up and injected via `Depends`, and tests build the same container with lightweight components (hash embeddings, lexical reranker), so production wiring is exercised by the test suite.

## 2. Request flows

### Ingestion (`POST /documents/upload`)

1. Stream the upload with a hard size limit; reject empty files.
2. **Validate type by extension *and* magic bytes** (`%PDF-`, `PK\x03\x04`); a renamed executable is rejected with 415.
3. SHA-256 the bytes; an identical upload by the same user returns the existing document (`duplicate: true`).
4. Store the file under `storage/<owner>/<doc_id>.<ext>` (never the client filename) and create the `documents` row (`uploaded`).
5. Background task (`ingestion/pipeline.py`):
   parse → normalise → chunk (embedding-model tokens) → contextual chunk headers → batch embed → **delete old chunks + insert new chunks in one transaction** → `indexed` → invalidate the user's caches. Any failure sets `failed` with a safe message, removes partial chunks and is logged with the exception.
6. On start-up, documents left in `processing` by a crash are re-queued.

### Question answering (`POST /chat`, `/chat/stream`)

```
question
  → preprocess (control chars, whitespace, 1000-char cap)
  → contextualise follow-ups ("what about managers?" + previous question → retrieval query)
  → semantic answer cache (stateless questions only)
  → retrieve:
       embed query (Redis cache) → vector top-K' (HNSW, owner filter)
       → keyword top-K' (FTS, OR-query) [optional PRF / multi-query expansion]
       → RRF fusion → exact cosine for keyword-only hits → similarity threshold
       → cross-encoder rerank → top_k            (result cached per user + corpus version)
  → no chunks? → abstain without calling the LLM
  → context: dedupe → merge adjacent → budget → query-aware compression → injection flags
  → grounded prompt: system rules + prior turns + <source id=n …> blocks + question
  → LLM (LiteLLM) or local extractive answerer
  → citation verification (remove invalid markers, score support, count uncited claims)
  → persist messages + usage event → response with answer, citations, verification, usage, timings
```

The streaming endpoint emits `conversation`, `sources`, `token`* and `done` SSE events; `done` carries the *verified* answer (invalid markers removed), which clients should display in place of the raw token stream.

## 3. Data model

| Table | Purpose | Key constraints / indexes |
|---|---|---|
| `users` | accounts, bcrypt hash, role | unique email |
| `user_settings` | per-user RAG settings (validated JSONB) | PK = user_id, FK cascade |
| `documents` | uploaded files, status, metadata, chunking config | FK owner → users (cascade); **unique (owner_id, sha256)**; index (owner_id, created_at), status |
| `document_chunks` | text, offsets, page range, section, `vector(384)`, generated `tsvector` | PK stable hash id; FK document (cascade) and owner; unique (document_id, chunk_index); **HNSW (vector_cosine_ops, m=16, ef_construction=64)**; **GIN (content_tsv)**; (owner_id, embedding_model) |
| `conversations`, `messages` | chat threads; citations stored as JSONB on assistant turns | FK cascade; (user_id, updated_at), (conversation_id, created_at) |
| `evaluation_runs` | config, aggregated metrics, per-item results | (user_id, created_at) |
| `usage_events` | search/chat/ingest/eval latency, tokens, cost, cache hit | (user_id, created_at), (event_type, created_at) |

`owner_id` is denormalised onto `document_chunks` so every retrieval query filters on it directly (isolation + index efficiency). Chunks also store `embedding_model`, and queries filter on the current model, so vectors from different models are never compared.

### Embedding dimension safety

The vector column dimension is fixed by the migration (`EMBEDDING_DIMENSION`). At start-up `EmbeddingService` refuses to run if the configured model's dimension differs, and `/health/ready` compares the live column's `atttypmod` with the model. Changing models therefore requires an explicit migration + re-index — it can never silently corrupt the index.

## 4. Caching

| Cache | Key | Isolation | Invalidation |
|---|---|---|---|
| Query embedding | `rag:emb:<model>:<sha256(text)>` | content-addressed: a hit returns exactly what the caller would compute | TTL (24 h) |
| Retrieval results | `rag:ret:<user>:v<corpus_version>:<params hash>` | user id in key | `INCR rag:ver:<user>` on upload/ingest/delete/settings change (O(1)); TTL |
| Semantic answers | `rag:sem:<user>:v<version>:<config hash>` hash of question vectors | user id in key; only stateless questions; only grounded answers stored | same version counter; TTL; bounded size |

Redis failures degrade to cache misses: they are logged, counted (`rag_cache_events_total{result="error"}`) and never fail a request. `/health/ready` reports `degraded` when Redis is down.

## 5. Security model

- Authentication: bcrypt (cost 12, SHA-256 pre-hash > 72 bytes), HS256 JWT with `jti`; logout deny-lists the `jti` in Redis until expiry.
- Authorisation: every document/conversation/evaluation query includes `owner_id = current_user`; other users' resources return **404** (not 403) to avoid revealing existence. `/metrics` requires the admin role (`ADMIN_EMAILS`).
- Rate limiting: per-user (authenticated routes) and per-IP (auth routes) fixed windows in Redis.
- Input safety: Pydantic validation on every body; bound SQL parameters everywhere (no string-built SQL except a validated integer for `SET LOCAL hnsw.ef_search`); `plainto_tsquery` for user text; escaped `LIKE` patterns.
- Prompt injection: sources are wrapped in tags the document cannot close; the system prompt treats them as untrusted data; instruction-like text is flagged in `context.suspicious_sources`.
- Errors: a uniform `{error, message, request_id}` envelope; stack traces only in logs. Log records redact keys containing password/token/secret/api_key.

See [SECURITY_CHECKLIST.md](SECURITY_CHECKLIST.md) for status and production gaps.

## 6. Observability

- **Structured logs**: JSON (or console) with `request_id` and `user_id` from context variables; one access-log line per request with route template, status and latency.
- **Prometheus** (`/api/v1/metrics`, admin): HTTP requests/latency by route, embedding latency, retrieval latency per stage (embed, vector, keyword, fusion, rerank, multi-query), LLM latency/tokens/errors by model, cache hit/miss/error per cache, ingestion outcomes/chunks/latency, answer outcomes (grounded / ungrounded / insufficient / no_evidence / semantic_cache).
- **Per-response timings and usage** in every chat/search response, and persisted `usage_events` powering `/analytics/*`.

## 7. Deployment

`docker-compose.yml` runs PostgreSQL (pgvector image, init script creates the extension and the test database), Redis (AOF persistence, LRU cap) and the API (non-root user, migrations on start, health check, model cache volume). Host ports 5442 / 6380 / 8001 avoid clashes with other local stacks.

Production checklist (not provided by this repository): TLS termination, a secret manager for `JWT_SECRET_KEY` and provider keys, a durable job queue for ingestion, object storage for uploads, Postgres backups and HNSW parameter tuning for the real corpus size, horizontal API replicas (each loads its own models, ~400 MB RAM), and an authorization policy review.
