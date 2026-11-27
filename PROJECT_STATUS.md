# Project Status

Snapshot: 2026-11-26. The scope was narrowed during the project to **the AI system plus the supporting backend**. A React web frontend (`frontend/`) was added on 2026-11-26. The REST API with Swagger UI remains available.

## ✅ Implemented and verified

Verified means automated tests pass, and for quality claims the measured evaluation was actually executed.

- **Ingestion:** PDF/DOCX/TXT parsing with page and section maps; magic-byte and size validation; SHA-256 duplicate detection; background ingestion with status tracking; atomic re-ingestion; failure handling; crash-resume on start-up.
- **Chunking:** fixed / recursive / sentence strategies; embedding-token-aware limits; overlap; section-aware boundaries; exact offsets; page ranges; stable ids; contextual chunk headers.
- **Embeddings:** MiniLM-L6-v2 (384-d) via an abstraction; batching; normalisation; dimension guards at start-up, per call and in readiness; per-model filtering; Redis query cache.
- **Retrieval:** pgvector HNSW cosine search with iterative scan; PostgreSQL full-text search (OR semantics); RRF hybrid fusion with deterministic tie-breaking; metadata filters; similarity threshold; PRF; LLM multi-query (with a fake LLM); per-stage timings and debug traces.
- **Reranking:** cross-encoder over `top_k × multiplier` candidates, with a configurable cut-off.
- **Context engineering:** dedupe, adjacent-chunk merging, token budget, query-aware compression, injection flagging.
- **Generation:** local extractive answerer with cross-encoder answerability gating; LiteLLM provider (mocked: success, streaming, usage/cost, timeout, errors); SSE streaming.
- **Grounding:** citation parsing and verification; invalid markers removed; support scoring; abstention.
- **Conversation memory:** recent and relevant older turns; follow-up contextualisation; per-user isolation.
- **Caching:** embedding, retrieval (user-scoped, version-invalidated) and semantic answer caches; hit/miss metrics; graceful Redis outage.
- **Security:** bcrypt, JWT with revocation, owner-scoped queries returning 404, rate limiting, model whitelist, safe error envelope, production config guards.
- **Observability:** JSON logs with request and user ids, Prometheus metrics, readiness checks, usage events, analytics endpoints.
- **Evaluation:** metrics, runner, ablations, dev and held-out datasets with validated labels, JSON/CSV reports, abstention calibration sweep. Results in [docs/EVALUATION.md](docs/EVALUATION.md).
- **Database:** SQLAlchemy models, Alembic migration (applied to the app and test databases), indexes and constraints.
- **Docker:** the Compose stack (Postgres + pgvector, Redis, API) builds, starts healthy, runs migrations, and produced evaluation results matching the local run.
- **Web frontend** (React + TypeScript + Tailwind, `frontend/`): `npm run build` passes with strict TypeScript. A scripted browser run (Playwright driving Microsoft Edge) against the live backend verified each step below with no page errors and no 5xx responses:
  - the login redirect, the wrong-password error, and login;
  - upload of a DOCX and a PDF through the UI to "Indexed", and rejection of an `.exe` file;
  - a streamed answer from `ollama/llama3.2` with citation chips, the citation card and the grounding badge;
  - the insufficient-evidence notice;
  - restoring a conversation after a page reload;
  - search with scores and highlighting;
  - the Knowledge Base, Analytics and Settings pages;
  - the backend health indicator;
  - the 390 px mobile layout with no horizontal overflow;
  - logout.

## 🟡 Implemented but not fully verified

- **LLM providers through LiteLLM.**
  - **Ollama** (`ollama/llama3.2`, local and free): real streamed answers were observed through the API and the frontend. One example had 1 citation, `grounded=false` with a grounding score of 0.82, and about 31–35 s latency on CPU. There is no answer-quality benchmark.
  - **OpenAI, Anthropic and Gemini:** tested with mocks only. No real call was made, to avoid charges.
- **Grounded prompt effectiveness** (citation adherence, abstention sentence, injection resistance) with a real LLM: not measured.
- **Timing-equalised login**, **log redaction**, and **SQL-injection safety**: implemented by construction, but not timing-tested or fuzzed.
- **Prometheus metrics content**: the endpoint is tested, but no dashboard has been built on it.

## 🟠 Partially implemented

- **RAGAS:** not integrated, because it requires a paid judge LLM. Deterministic local proxies (lexical faithfulness, embedding answer relevance, evidence-based context and citation precision) are used instead and labelled as proxies.
- **Roles:** `user` and `admin` exist, but admin only gates `/metrics`. There is no admin UI or user management API.
- **Logout:** access-token revocation only; no refresh tokens.

## ⛔ Blocked by external dependencies

- **Benchmarking hosted LLMs** needs an approved, paid API key. `OPENAI_API_KEY` exists in this environment but was intentionally not used without approval. One command runs it: `run_evaluation.py --k 3 --skip-ablation --model gpt-4o-mini`. At this dataset size, expect roughly 100k tokens, likely under $0.05 at gpt-4o-mini rates. That's an estimate, not a measurement.

## ❌ Not implemented

- Frontend gaps:
  - no automated component or E2E test suite in the repo (verification above was a one-off script);
  - no evaluation-run trigger in the UI (results are displayed only);
  - no search filters UI;
  - no light theme;
  - not containerised in docker-compose.
- OCR for scanned PDFs; other formats (PPTX, HTML, XLSX).
- Durable job queue (Celery/arq) and object storage for uploads.
- CI pipeline, dependency/image vulnerability scanning, load testing.
- Row-level security in PostgreSQL, refresh tokens, account lockout, malware scanning.
- Cross-encoder/LLM answerability model for near-miss questions (recommended next step; see [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md) §12).

## Recommended next steps (in priority order)

1. Benchmark one hosted LLM end to end (after cost approval) and compare abstention and citation precision with the local answerer.
2. Replace the local answerability gate with a no-answer-aware model (SQuAD 2.0-style QA or NLI) and re-evaluate on a **new** held-out set.
3. Grow the benchmark with real documents and 200+ questions, so retrieval metrics stop saturating and confidence intervals become meaningful. Then re-decide reranking and PRF defaults.
4. Move ingestion to a durable queue and add CI (tests, Ruff, pip-audit, image build).
