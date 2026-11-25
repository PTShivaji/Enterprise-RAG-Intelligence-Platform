# Test Report

**Result: 120 passed, 0 failed · line coverage 94 % · Ruff: all checks passed** (run on 2026-11-25).

Environment: Windows 11, Python 3.13.7, PostgreSQL 16.16 + pgvector 0.8.7 and Redis 7.4 from `docker compose`, real models from the local Hugging Face cache.

```powershell
# in .\backend, with `docker compose up -d postgres redis` running
.\.venv\Scripts\python.exe -m pytest                                    # 114 tests (real-model tests skipped)
$env:RUN_MODEL_TESTS="1"; .\.venv\Scripts\python.exe -m pytest --cov=app --cov-report=term   # all 120
.\.venv\Scripts\ruff.exe check app tests alembic
```

## Test design

- **No SQLite substitution.** Integration tests run on a real PostgreSQL + pgvector database (`rag_test`, migrated with the same Alembic migration) and real Redis (isolated DB 15, flushed per test). Tests skip with an explicit reason if either is unavailable.
- **Deterministic doubles for speed, real models separately.** Most tests use a hashed bag-of-words embedding (same interface, 384-d) and a lexical-overlap reranker. The `models` tests load the real MiniLM bi-encoder and cross-encoder and check behaviour such as paraphrase retrieval, contractor vs. employee discrimination and abstention.
- **External services mocked at the boundary.** LiteLLM is mocked at `litellm.acompletion` for success, streaming, usage/cost, hard timeout, auth failure and generic provider errors. No paid API calls are made.
- **The same container wiring as production.** Integration tests build `AppContainer` through the same constructor as the app and drive it through `httpx.ASGITransport`.

## Inventory

| File | Tests | Covers |
|---|---:|---|
| `unit/test_parsers.py` | 14 | magic-byte validation and spoofed extensions; PDF pages, headings and offset→page mapping; DOCX headings and tables (no invented pages); TXT encodings and heading detection; corrupted/empty files; text normalisation |
| `unit/test_chunking.py` | 17 | token limits and exact offsets for all 3 strategies; overlap; sentence integrity; paragraph preference; page ranges across page breaks; section-aware boundaries; heading handling; stable ids; hard-splitting oversized tokens; config validation; contextual headers |
| `unit/test_embeddings_and_retrieval_logic.py` | 18 | normalisation and shape; wrong output dimension; model/column dimension mismatch; chunk size vs model window; RRF maths, weights and **evidence-based tie-breaking**; reranker ordering/filtering; query preprocessing; follow-up detection; contextualisation; PRF; multi-query parsing |
| `unit/test_context_and_citations.py` | 16 | exact/near-duplicate removal; adjacent-chunk merging without duplication; no cross-document merging; budget and query-aware compression; injection flagging; source-tag escaping; history vs. sources separation; citation extraction with metadata; **invented citations removed**; weak support; uncited claims; marker-after-period regression; abstention detection |
| `unit/test_generation_cache_security.py` | 18 | LiteLLM error classification and safe messages; hard timeout; usage and cost; streaming deltas + final usage; local extractive answering and abstention; embedding cache and hit/miss metrics; **user-scoped retrieval cache and invalidation**; semantic cache threshold and isolation; Redis outage → cache miss; rate limiter; bcrypt; JWT tamper/expiry/`alg=none`; production config guards; retrieval and generation metric maths |
| `unit/test_eval_dataset.py` | 3 | dataset integrity; every evidence phrase found in its document (dev and held-out); no dev/held-out overlap |
| `integration/test_api_flow.py` | 25 | auth (register/login/me/logout revocation, rejections, OAuth2 form); upload + ingestion of PDF/DOCX/TXT; duplicates; 415/413/422 validation; corrupted file → `failed`; re-ingestion with new chunking + deletion cleanup; vector/keyword/hybrid search; filters and debug stages; retrieval cache hit → invalidation on upload; search history; grounded chat with verified citations; insufficient evidence; semantic cache reuse; **SSE streaming**; conversation memory follow-up; model whitelist; **cross-user isolation** (documents, chunks, search in all modes, chat, semantic cache, conversations, analytics); settings validation; analytics; admin-only metrics; evaluation run with ablation; health/readiness; request ids and safe errors |
| `integration/test_query_expansion.py` | 3 | multi-query expansion through pgvector with a fake LLM; degradation to PRF when the LLM fails or is local; option overrides |
| `integration/test_real_models.py` | 6 | real model contract (384-d, 256 window, normalised); paraphrase retrieval (3 cases); cross-encoder prefers the answering passage; local answerer answers and abstains with the real cross-encoder |

## Coverage by module (line coverage)

| Module | Coverage |
|---|---:|
| `rag/` (citations, prompt, types 100 %; pipeline 97 %; generation 94 %; context builder 92 %) | 92–100 % |
| `retrieval/` (hybrid 100 %, retriever 99 %, vector/keyword/query processing 97 %) | 89–100 % |
| `ingestion/` (chunking 96 %, parsers 90–97 %, pipeline 92 %) | 90–97 % |
| `embeddings/` | 90–96 % |
| `evaluation/` | 95–96 % |
| `services/` | 88–100 % |
| `api/` | 92–93 % (routes exercised end to end) |
| `cache/redis_cache.py` | 79 % — the uncovered lines are mostly per-method Redis-error branches; the outage path is tested once through a failing client |
| `core/logging.py`, `core/tokens.py` | 77–79 % — JSON formatter details and the offline tiktoken fallback |
| **Total** | **94 %** |

Coverage is measured with `concurrency = ["greenlet", "thread"]`. Without it, code running after SQLAlchemy async awaits (for example the whole ingestion pipeline) executes but isn't recorded, which earlier showed a false 52 % for `ingestion/pipeline.py`.

## Defects found by testing and evaluation (all fixed)

| Defect | Found by | Fix |
|---|---|---|
| Route module `settings` shadowed by the `settings` variable in `create_app`, so the settings router was silently dropped | lint autofix removing the import, confirmed by import check | renamed import |
| Untracked `asyncio.create_task` for resumed ingestions (could be garbage-collected) | Ruff RUF006 | tasks held in a set on `app.state` |
| Server defaults outside per-user schema bounds caused 500s at request time | integration test | same bounds on server config, failing at start-up |
| Recursive chunking of a short document produced one unit, so section boundaries were ignored | new section-aware unit test | split into section spans before building units |
| Citation marker after a period split into its own "sentence": false "uncited" count and whole-chunk excerpts | real API response inspection | splitter never starts a sentence at `[digit`; regression test |
| RRF ties broken by UUID-derived ids made benchmark results non-deterministic | two identical evaluation runs disagreeing | evidence-based tie-breaking; unit test |
| fakeredis 2.40 incompatible with redis-py 8.2 (`__init__.__closure__`) | test fixture errors | tests use the real Redis service; fakeredis removed |

## Not covered by automated tests

- Real hosted-LLM calls (OpenAI/Anthropic/Gemini/Ollama). These are mocked only.
- Load and concurrency testing, and HNSW recall at large scale.
- The Docker image is verified manually: it built, became healthy, and produced held-out evaluation results identical to the local run. There's no CI pipeline in this repository.
- Fuzzing of upload parsers and of the API.
