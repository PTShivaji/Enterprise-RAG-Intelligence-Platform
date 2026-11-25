# AI Engineering Report

Enterprise RAG Intelligence Platform — design decisions, algorithms, measured results and limitations of the AI system. Companion documents: [ARCHITECTURE.md](ARCHITECTURE.md) (system structure), [docs/EVALUATION.md](docs/EVALUATION.md) (full evaluation), [PROJECT_STATUS.md](PROJECT_STATUS.md) (what is verified).

---

## 1. RAG architecture

A two-stage retrieve-then-read pipeline with explicit grounding controls at both ends:

```
query → preprocess → contextualise follow-ups → [semantic cache]
      → recall stage:  vector (HNSW) ∥ keyword (FTS)  → RRF fusion → similarity threshold
      → precision stage: cross-encoder rerank → top_k
      → [no evidence → abstain without an LLM call]
      → context engineering: dedupe → merge adjacent → token budget → query-aware compression
      → grounded prompt (untrusted <source> blocks, citation contract, abstention sentence)
      → generator: LiteLLM (any provider) | local extractive answerer
      → citation verification → answer + citations + verification report
```

Design principles:

- **Each stage has one job.** Retrieval maximises recall, the reranker orders, the context builder spends a token budget, the generator answers, the verifier checks. Measured consequence: moving the abstention decision out of retrieval (a hard rerank cut-off) into the answer stage removed the last retrieval miss (iteration 4).
- **Persistence-agnostic core.** `rag/pipeline.py` and `retrieval/` depend only on interfaces (`EmbeddingModel`, `Reranker`, `LLMProvider`, `CacheService`); the blocking and streaming paths share `_prepare`/`_finalize`, so they cannot drift apart.
- **Everything observable.** Each response carries per-stage timings, token usage, cost, retrieval metadata (cache hits, expansion terms, candidates considered) and the citation verification report.

## 2. Document ingestion and chunking

**Parsing.** PDF via PyMuPDF `get_text("dict")`: blocks are re-joined into paragraphs, and headings are detected from font size (≥ 1.15 × the median body size) or bold short lines. DOCX via python-docx in document order, including tables (`cell | cell`), with `Heading*`/`Title` styles as sections. TXT/Markdown with encoding detection and Markdown, numbered and ALL-CAPS headings. All parsers emit one normalised text string with **page and section offset maps** (`ParsedDocument`). DOCX has no fixed pages, so its chunks get `page_number = None` — never an invented page.

**Chunking** (`ingestion/chunking.py`). Every strategy reduces text to *units* (character spans that each fit the budget), and one packer merges adjacent units into windows of at most `chunk_size` tokens with `overlap` tokens of trailing context:

| Strategy | Units | Property |
|---|---|---|
| fixed | words | classic sliding token window |
| sentence | sentences (abbreviation-aware splitter) | never cuts a sentence |
| recursive (default) | largest structural piece that fits: paragraph → line → sentence → word | keeps paragraphs intact |

Key decisions:

1. **Token-aware in the embedding model's own tokens.** `all-MiniLM-L6-v2` truncates at 256 word-pieces; counting with tiktoken (or words) would silently produce chunks whose tails are never embedded. The service refuses to start if `CHUNK_SIZE_TOKENS > max_seq_length − 2`.
2. **Section-aware boundaries.** Each section is chunked independently; overlap never crosses a section. This was the largest measured improvement (iteration 2 in the evaluation): mixed-section chunks scored poorly with the cross-encoder and diluted embeddings.
3. **Exact offsets.** Chunk content is exactly `text[char_start:char_end]`, so page ranges (`page_number`–`page_end`) and sections are derived precisely, and adjacent chunks can later be merged without duplicating text.
4. **Stable ids.** `sha256(document_id : index : sha256(content))` — re-ingesting an unchanged document reproduces the same ids.
5. **Contextual chunk headers.** The text *embedded* is `"<title> > <section>\n<chunk>"`; the stored/displayed content is unchanged. This gives the vector global context (a chunk saying "receive 22 days" is otherwise ambiguous about *what* the days are).

## 3. Embedding model

`sentence-transformers/all-MiniLM-L6-v2`: 384 dimensions, 22 M parameters, ~6 ms per query on a laptop CPU in this setup — chosen because the requirement was free, local, CPU-only operation. Vectors are L2-normalised so cosine similarity equals the dot product.

Safety mechanisms:

- The pgvector column dimension is fixed by the migration; `EmbeddingService` raises on start-up if the model's dimension differs, every encode call validates the output shape and finiteness, and `/health/ready` compares the live column type with the model.
- Each chunk stores `embedding_model`, and retrieval filters on the current model — vectors from different models are never compared.
- The abstraction (`EmbeddingModel`) supports asymmetric query/passage prefixes (E5, BGE), so swapping models is configuration plus a re-index.
- Query embeddings are cached in Redis, content-addressed by model and text.

## 4. Retrieval algorithms

**Vector search.** `ORDER BY embedding <=> :q` with an HNSW index (`vector_cosine_ops`, m = 16, ef_construction = 64). Two details that matter with per-user filtering: `hnsw.ef_search` is raised to 4 × K per query, and on pgvector ≥ 0.8 `hnsw.iterative_scan = relaxed_order` keeps scanning until K rows *that pass the owner filter* are found (plain HNSW post-filtering can return fewer than K). Rows are re-sorted exactly afterwards.

**Keyword search.** PostgreSQL full-text search on a generated `tsvector` column with a GIN index. `plainto_tsquery` safely parses arbitrary user text but AND-s all terms — far too strict for questions — so the query is rewritten to OR semantics (`replace(plainto_tsquery(...)::text, '&', '|')::tsquery`) and ranked with `ts_rank` normalised by document length. PostgreSQL has no native BM25; this is the standard built-in approximation.

**Hybrid fusion — Reciprocal Rank Fusion.** `score(d) = Σ 1 / (60 + rank_i(d))`. RRF was chosen over a weighted score sum because cosine similarity (~0.2–0.8) and `ts_rank` (~0–0.1, unbounded) are incomparable and shift per query; RRF uses ranks only and needs no calibration. Exact ties are common (vector #1 + keyword #2 vs the reverse); they are broken by best single-list rank, then cosine — tie-breaking by id made results non-deterministic between runs (iteration 8).

**Post-fusion.** Keyword-only candidates get their exact cosine computed so one similarity threshold applies uniformly; metadata filters (document ids, file types, filename, page range) are applied in SQL together with the owner filter.

**Query transformation.** Normalisation (control characters, whitespace, length cap); follow-up contextualisation (a heuristic detects anaphoric/short follow-ups and prepends the previous user question to the *retrieval* query only); pseudo-relevance feedback (RM3-style term mining from the top semantic hits, IDF-weighted within the feedback set, requiring the term in ≥ 2 feedback docs); and LLM multi-query expansion (paraphrases searched separately and fused with RRF, falling back to PRF if the LLM is local or fails). PRF and multi-query are opt-in — PRF measurably hurt on the sample corpus.

## 5. Reranking strategy

Two-stage retrieval: the recall stage returns `top_k × 4` candidates; `cross-encoder/ms-marco-MiniLM-L-6-v2` scores each `(query, chunk)` pair with full cross-attention; the top `top_k` are kept. The cut-off `RERANK_MIN_SCORE = −10` is deliberately liberal — retrieval should not decide answerability.

Measured honestly: on the sample corpus the reranker **did not improve** MRR (hybrid 1.000 → hybrid + rerank 0.984) and adds ~290 ms p50 on CPU. Its one change was demoting a paraphrase that requires arithmetic-style reasoning ("three years" ∈ "two to five years"). It stays on by default because (a) its sentence-level scores power the local answerer's abstention gate and (b) cross-encoders typically pay off with deeper candidate pools on larger, noisier corpora — a claim this small benchmark cannot confirm, so the recommendation is to re-measure on the target corpus.

## 6. Context construction

`rag/context_builder.py`, in order:

1. **De-duplication** — exact (normalised hash) and near-duplicate (Jaccard ≥ 0.8 over word 3-shingles).
2. **Adjacent-chunk merging** — selected chunks of the same document whose spans overlap or touch are stitched using their offsets; the stitch is verified textually and refused if offsets and text disagree. This removes duplicated overlap tokens and gives the model a coherent passage; merged sources keep all chunk ids and the union of page ranges.
3. **Token budget** (`CONTEXT_MAX_TOKENS`, tiktoken `cl100k_base` as a provider-neutral estimate) with a per-source cap.
4. **Query-aware compression** — a source that does not fit is reduced to its most query-relevant sentences (overlap normalised by √length, slight positional prior), kept in original order with "…" gap markers, rather than being dropped or blindly truncated.
5. **Injection screening** — instruction-like patterns ("ignore previous instructions", "reveal your system prompt") are flagged per source.

Average context in the evaluation: 193 tokens (dev) for top_k = 5 — section-coherent chunks are compact.

## 7. LLM integration

`rag/generation.py` defines `LLMProvider` with `generate` and `stream`.

**LiteLLM provider** — any LiteLLM model string (OpenAI, Anthropic, Gemini, Ollama, …), whitelisted by `LLM_ALLOWED_MODELS`. Per-call `timeout` plus provider retries (`num_retries`) for transient errors, wrapped in a hard `asyncio.wait_for` ceiling covering all retries. Provider exceptions are classified (timeout, auth, rate limit, model not found, context window, connection, unavailable) and mapped to safe client messages; internals are logged, never returned. Streaming requests usage via `stream_options.include_usage` and falls back to tiktoken counts. Cost comes from LiteLLM's pricing table (`None` for unknown/local models). Prometheus records latency, tokens and errors per model.

**Local extractive provider** — the zero-key default and an honest baseline, not a mock. It splits the context into sentences (excluding heading fragments), scores each against the question with the cross-encoder, abstains if the best logit is below `LOCAL_ANSWER_MIN_LOGIT` (calibrated, §9), otherwise selects up to four sentences by **Maximal Marginal Relevance** (relevance vs. redundancy on sentence embeddings) and emits them verbatim with their `[n]` citations. Answers are faithful by construction but extractive, not synthesised. It streams word by word so clients exercise the same SSE protocol.

**Prompt engineering** (`rag/prompt_builder.py`): sources in `<source id="n" document=… pages=… section=…>` tags (tags inside documents are escaped so a document cannot close its own block); rules: use only sources, cite every factual sentence with existing numbers only, a fixed abstention sentence, report conflicts, treat source text as untrusted, history is not a source of facts. Conversation history is passed as prior turns with old `[n]` markers stripped (they referred to previous source lists).

**Cost/latency controls:** no LLM call at all when retrieval finds nothing; semantic answer cache for repeated questions; compact section-coherent context; history turns truncated to 300 tokens; at most 4 recent + 2 relevant older turns.

## 8. Citation verification

`rag/citations.py` runs after every generation:

1. Parse `[n]`, `[n, m]` and `[n][m]` markers (a marker after the full stop stays with its sentence — a splitter bug here was found from a real response and fixed with a regression test).
2. **Remove** markers that reference non-existent sources and report them (`invalid_markers_removed`); never remap or invent.
3. For each cited sentence compute *support* = share of its content terms present in the cited source(s); count weakly supported sentences (< 0.5) and uncited factual sentences.
4. Return one `Citation` per referenced source with document id, filename, chunk id(s), page range, section, the best supporting sentence as the excerpt, and the retrieval / rerank / vector scores.

`verification.grounded` is true only for an abstention, or for an answer that has citations and no weakly supported sentences; only grounded answers enter the semantic cache. Citations are returned separately from the answer text, and the streaming `done` event carries the verified answer.

## 9. Evaluation methodology

Details in [docs/EVALUATION.md](docs/EVALUATION.md). In short: a 7-document synthetic corpus with deliberate distractors; a 34-question dev set in five categories; an 11-question held-out set written before its scores were seen; relevance labels via verbatim evidence phrases (chunking-independent; validated by a unit test); deterministic retrieval metrics (P/R/Hit@k, MRR, nDCG), generation proxies (lexical faithfulness, embedding answer relevance, context and citation precision, abstention) and latency/token accounting; a 7-configuration retrieval ablation; an abstention-threshold sweep; caches bypassed during evaluation; two-run determinism check.

## 10. Benchmark results (measured)

Retrieval (dev, k = 3, MRR / p50):

| keyword | vector | **hybrid** | hybrid + PRF | hybrid + rerank |
|---|---|---|---|---|
| 0.930 / 6 ms | 0.952 / 6 ms | **1.000 / 11 ms** | 0.930 / 9 ms | 0.984 / 297 ms |

Paraphrase questions: keyword 0.783 → vector 0.900 → hybrid 1.000.

End-to-end, local answerer (dev | held-out): faithfulness 1.000 | 1.000; citation precision 0.799 | 1.000; citation validity 1.000 | 1.000; answer rate 0.774 | 0.750; abstention accuracy 1.000 (3/3) | **0.714 (5/7)**; latency p50 583 | 250 ms; tokens and cost 0.

## 11. Latency and token optimisation

| Technique | Where | Measured / expected effect |
|---|---|---|
| HNSW + GIN indexes, owner/model composite index | DB | vector and keyword retrieval 6 ms p50 each; hybrid 11 ms |
| `ef_search` tuning + iterative scan | vector search | full K results under selective owner filters |
| Query embedding cache | Redis | skips the encoder on repeated queries |
| Retrieval result cache with O(1) invalidation | Redis | repeated searches skip embedding + SQL + rerank (verified hit/miss in tests) |
| Semantic answer cache (cosine ≥ 0.95) | Redis | near-duplicate questions skip retrieval and generation entirely (verified in tests) |
| Abstain before calling the LLM when retrieval is empty | pipeline | zero tokens for out-of-scope questions |
| Section-aware chunks, dedupe, adjacent merging, compression | context | ~193 context tokens average for 5 sources |
| Batch embedding at ingestion; models loaded once; CPU work in threads | ingestion / runtime | event loop never blocked; 7-document corpus ingests in 0.3–1.2 s per document |
| Cross-encoder is the dominant cost | rerank | ~290 ms p50 for 20 candidates on CPU — the first thing to move to GPU, shrink (`candidate_multiplier`) or disable per user |

## 12. Known limitations

1. **Local abstention on near-miss questions** (entity present, attribute absent): 5/7 on held-out. The ms-marco cross-encoder measures topical relevance, not answerability. Remedies: a hosted LLM with the grounded prompt, or a no-answer-aware model (SQuAD 2.0-style extractive QA or an NLI entailment check between question-derived hypothesis and the candidate sentence).
2. **Extractive local answers** cannot synthesise across sources or rephrase.
3. **Hosted LLM paths are not benchmarked** — only covered by mocked tests (success, streaming, usage, cost, timeout, provider errors). No paid API calls were made.
4. **Generation metrics are proxies**; RAGAS / LLM-as-judge is not integrated.
5. **Benchmark scale**: 44 chunks, 45 questions, synthetic documents written by the same author as the questions; retrieval metrics saturate; no confidence intervals. Numbers will be lower on real enterprise data.
6. **Follow-up detection is heuristic**; an LLM query rewriter would be more robust when a hosted model is configured.
7. **Keyword ranking is `ts_rank`, not BM25**; a BM25 extension (e.g. ParadeDB/pg_search) could improve lexical precision.
8. **Operational**: in-process background ingestion (no durable queue), no OCR, single-process model loading (~800 MB RAM per API container), English-only full-text configuration.

## 13. Interview talking points

- Why RRF over score fusion; why hybrid wins (complementary failure modes, shown per category).
- Why chunk size is measured in the embedding model's tokens (silent truncation at 256 word-pieces).
- Section-aware chunking as the highest-leverage change, found from a failing ablation, not assumed.
- Separation of concerns between recall (retrieval), ordering (rerank) and answerability (generation) — and the measured consequence of violating it.
- Calibrating an abstention threshold on dev data, validating on held-out data, and reporting the drop instead of re-tuning.
- Finding non-determinism in an evaluation (RRF ties broken by UUID-derived ids) and fixing it with evidence-based tie-breaking.
- Why a cross-encoder can lose to plain hybrid on a small clean corpus, and when it should win.
- User isolation that holds across SQL filters, HNSW post-filtering, three cache layers and the semantic cache.
