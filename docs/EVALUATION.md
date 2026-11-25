# Evaluation: methodology, results and iteration history

Every number in this document was produced by `evaluation/scripts/run_evaluation.py` against the running API. The raw JSON/CSV reports behind the final results are committed in [`evaluation/benchmarks/2026-11-25/`](../evaluation/benchmarks/2026-11-25/) (new runs write to the git-ignored `evaluation/results/`). Nothing here is estimated.

## 1. What is measured and how

### Datasets

| File | Purpose | Items |
|---|---|---|
| `evaluation/datasets/sample_corpus/` | 7 synthetic documents for a fictional company: 1 PDF (4 pages), 1 DOCX, 5 TXT. Includes **distractors**: a contractor handbook next to the employee leave policy, a battery-safety guide next to the inverter manual. | 44 chunks (default settings) |
| `sample_qa.json` (dev) | Labelled questions in 5 categories: `direct` (14), `paraphrase` (10, vocabulary mismatch), `distractor` (4), `multi` (3, two facts), `unanswerable` (3) | 34 |
| `sample_qa_holdout.json` (held-out) | Written **after** the abstention threshold was chosen and **before** any of its scores were seen; mostly "near-miss" unanswerables (entity present, fact absent) | 11 (4 answerable, 7 unanswerable) |

Each answerable item lists **evidence phrases copied from the source**. A retrieved chunk is *relevant* when it contains ≥ 80 % of an evidence phrase's content terms. Labels are therefore independent of chunk ids and boundaries, so chunking strategies can be compared without re-labelling. A unit test (`tests/unit/test_eval_dataset.py`) verifies that every evidence phrase is found in its expected document under exactly this rule, and that the held-out set does not overlap the dev set.

### Metrics (`backend/app/evaluation/metrics.py`)

| Metric | Definition |
|---|---|
| Precision@k | relevant chunks in top-k / k |
| Recall@k | evidence phrases covered by top-k / all evidence phrases |
| Hit@k | 1 if any relevant chunk is in the top-k |
| MRR | 1 / rank of the first relevant chunk |
| nDCG@k | binary-gain DCG / ideal DCG |
| Faithfulness | share of factual answer sentences whose content terms are ≥ 60 % contained in the supplied context (**lexical proxy**) |
| Answer relevance | cosine(question, answer) with the embedding model (**embedding proxy**) |
| Context relevance | share of context sources that are relevant (context precision) |
| Citation precision | share of cited sources that are relevant |
| Citation validity | 1 if the generator produced no citation marker pointing at a non-existent source |
| Answer term recall | share of the expected answer's key terms present in the answer |
| Answer rate / abstention accuracy | answered on answerable items / abstained on unanswerable items |
| Latency | p50 / p95 of retrieval and end-to-end, measured inside the evaluation runner |
| Tokens / cost | prompt + completion tokens and USD cost reported by the provider (0 in local mode) |

The runner bypasses the retrieval cache and the semantic cache so latency and quality reflect real computation.

**Scope note.** Faithfulness and the relevance metrics are deterministic *proxies*. They are not LLM-judged and are not RAGAS scores; RAGAS was not run because it needs a paid judge LLM. Faithfulness = 1.000 for the local answerer is expected by construction (it only emits verbatim source sentences); the metric becomes informative with an abstractive LLM.

## 2. Final results

Environment: API in Docker Desktop (Linux container, WSL2) on an Intel Core i5-1135G7 laptop with 16 GB RAM, CPU only; PostgreSQL 16.16 + pgvector 0.8.7; models `all-MiniLM-L6-v2` (embeddings) and `ms-marco-MiniLM-L-6-v2` (cross-encoder). k = 3. Reports `20261125T063318Z`, `20261125T063427Z` (two identical-quality dev runs) and `20261125T063439Z_sample_qa_holdout`.

### Retrieval ablation (dev set, 31 answerable questions)

| Configuration | MRR | nDCG@3 | Paraphrase (10) | Direct (14) | Multi (3) | Distractor (4) | p50 | p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| keyword | 0.930 | 0.894 | 0.783 | 1.000 | 1.000 | 1.000 | 6 ms | 9 ms |
| vector | 0.952 | 0.910 | 0.900 | 0.964 | 1.000 | 1.000 | 6 ms | 9 ms |
| **hybrid (RRF)** | **1.000** | **0.945** | **1.000** | **1.000** | **1.000** | **1.000** | 11 ms | 13 ms |
| hybrid + PRF | 0.930 | 0.894 | 0.950 | 0.917 | 0.833 | 1.000 | 9 ms | 12 ms |
| vector + rerank | 0.984 | 0.933 | 0.950 | 1.000 | 1.000 | 1.000 | 287 ms | 636 ms |
| hybrid + rerank | 0.984 | 0.933 | 0.950 | 1.000 | 1.000 | 1.000 | 297 ms | 559 ms |
| hybrid + PRF + rerank | 0.984 | 0.933 | 0.950 | 1.000 | 1.000 | 1.000 | 333 ms | 571 ms |

Hit@3 = Recall@3 = 1.000 and Precision@3 = 0.333 for every configuration: with 44 chunks and usually one relevant chunk per question, k = 3 saturates them. **MRR and nDCG are the discriminating metrics on this corpus.**

### End-to-end (hybrid + rerank, local extractive answerer)

| Metric | Dev (31 + 3) | Held-out (4 + 7) |
|---|---:|---:|
| Faithfulness | 1.000 | 1.000 |
| Answer relevance | 0.697 | 0.784 |
| Context relevance | 0.354 | 0.583 |
| Citation precision | 0.799 | 1.000 |
| Citation validity | 1.000 | 1.000 |
| Answer term recall (answered items) | 0.904 | 1.000 |
| Answer rate on answerable | 0.774 (24/31) | 0.750 (3/4) |
| Abstention accuracy on unanswerable | 1.000 (3/3) | 0.714 (5/7) |
| Retrieval latency p50 / p95 | 278 / 590 ms | 114 / 321 ms |
| End-to-end latency p50 / p95 | 583 / 826 ms | 250 / 607 ms |
| Average context size | 193 tokens | 98 tokens |
| LLM tokens / cost | 0 / $0 | 0 / $0 |

Context relevance is low by design: the context holds top_k = 5 sources and most questions have exactly one relevant chunk.

## 3. Findings

1. **Hybrid fusion is the single most valuable retrieval technique here.** The retrievers fail on different questions: keyword search is perfect on direct wording but drops to 0.783 MRR on paraphrases; vector search handles paraphrases (0.900) but misranks one direct question. RRF needs no score calibration and got every question's relevant chunk to rank 1.
2. **The cross-encoder did not improve ranking on this corpus.** Its only change was demoting one paraphrase, `leave-02` ("I've been at the company for three years. How much vacation time do I get?"), where relevance requires inferring 3 ∈ "two to five years" and vacation = annual leave — beyond a 22 M-parameter MiniLM cross-encoder. It also costs ~290 ms per query on CPU. It remains enabled by default (its sentence scores drive the local abstention gate, and rerankers usually help more with deeper candidate pools on larger corpora), but **this should be re-measured on the target corpus.**
3. **Pseudo-relevance feedback hurt** (MRR 0.930 vs 1.000): with section-coherent chunks, expansion terms mined from the top hits drift toward neighbouring sections and promote them in the keyword list. It is opt-in (`QUERY_EXPANSION=prf`).
4. **Local abstention is the weakest component.** On the held-out set, both errors are *near-misses*: "BESS-200 terminal torque" and "BESS-200 noise level" were answered with the generic product sentence "The BESS-200 is a 200 kWh … cabinet" (logits 1.96 and 2.39 ≥ threshold 1.0). The ms-marco cross-encoder rewards entity overlap; it does not model whether the requested attribute is present. The false abstention (`ho-ans-03`, "sign up for health cover" vs "enrol in the health insurance plan", logit −1.43) is a paraphrase miss.

### Abstention calibration (dev set)

The local answerer abstains when the best sentence-level cross-encoder logit is below `LOCAL_ANSWER_MIN_LOGIT`. Sweep from the dev run:

| Threshold | Answer rate | Abstention accuracy | Balanced |
|---:|---:|---:|---:|
| −2.0 | 0.903 | 0.333 | 0.618 |
| 0.0 | 0.839 | 0.667 | 0.753 |
| **1.0** | **0.774** | **1.000** | **0.887** |
| 2.0 | 0.774 | 1.000 | 0.887 |
| 3.0 | 0.710 | 1.000 | 0.855 |

1.0 was chosen (best balanced accuracy, lowest threshold among ties, deliberately favouring abstention because a wrong policy answer costs more than "not found"). With only 3 unanswerable dev items this choice is statistically weak, which is why the held-out set exists. On held-out data the same threshold gives 0.714 abstention accuracy; the held-out sweep shows 3.0 would have been better there — it was **not** re-tuned, since that would contaminate the held-out estimate.

## 4. Iteration history (what changed and why)

| # | Change | Evidence that motivated it | Effect (measured) |
|---|---|---|---|
| 1 | Chunk size from 300 → 200 tokens, measured with the **embedding model's tokenizer**; start-up guard | MiniLM `max_seq_length` = 256: 300-token chunks would be silently truncated when embedded | Guard caught a stale `.env` (300) at start-up instead of silently truncating |
| 2 | **Section-aware chunking** (sections chunked independently; title folded into first section) | First benchmark: recursive packing merged several policy sections into one 200-token chunk (14 chunks total). The cross-encoder scored these mixed chunks low for paraphrases; Hit@5 with rerank fell to 0.871 (vs 1.000 without) | Rerank Hit@k 0.871 (k=5) → 0.968 (k=3); citation precision 0.702 → 0.814; corpus 14 → 44 chunks. k was lowered at the same time — a smaller k can only lower Hit@k, so the improvement is conservative |
| 3 | Local answerer: exclude heading fragments; score sentences with the **cross-encoder** instead of bi-encoder + lexical overlap | Unanswerable questions were "answered" with headings ("SI-5000 Solar Inverter Maintenance Manual [1]"); abstention 1/3 | Abstention 0.333 → 0.667 |
| 4 | `RERANK_MIN_SCORE` −6 → −10 (retrieval maximises recall; answerability is decided at the answer stage) | Remaining rerank miss: relevant chunk at logit −6.49 just below the cut-off | Rerank Hit@3 0.968 → 1.000 |
| 5 | `QUERY_EXPANSION` default prf → none | Without reranking, PRF lowered MRR on 5 items (3 of them direct-wording questions): 0.914–0.946 vs 0.984–1.000 without PRF across runs | With reranking enabled, PRF made no difference (0.984 either way); without reranking it is a pure loss here, so it became opt-in |
| 6 | Abstention threshold 0.0 → 1.0, from a threshold sweep; held-out set added | 5 false abstentions and 1 false answer at 0.0 | Dev abstention 1.000; held-out 0.714 (reported, not re-tuned) |
| 7 | Sentence splitter: `"sentence. [1]"` no longer splits the marker off | Real response showed `uncited_sentences: 1` and a whole-chunk citation excerpt for a correctly cited answer | Citation excerpts are the exact supporting sentence; uncited count correct (regression test added) |
| 8 | RRF tie-breaking by best single-list rank, then cosine (not chunk id) | Identical runs gave hybrid MRR 0.984 vs 1.000: exact RRF ties broken by chunk ids that embed random document UUIDs | Deterministic: two consecutive runs give identical quality metrics; hybrid MRR 1.000 |

Earlier iterations used k = 5; from iteration 2 onward k = 3 (more discriminating for this corpus size). Intermediate reports were kept locally in the git-ignored `evaluation/results/`; only the final reports are committed.

## 5. Limitations of this evaluation

- **Small, synthetic corpus.** 44 chunks, written to be clean; real enterprise documents (scans, tables, boilerplate, versions) are harder. Retrieval metrics saturate at k = 3. Expect lower numbers on real data.
- **Small question sets.** 31 + 4 answerable, 3 + 7 unanswerable — one question moves MRR by ~0.016 and abstention accuracy by 14–33 points. No confidence intervals are reported because they would be very wide.
- **Same author for corpus and questions**, which tends to inflate lexical overlap.
- **Proxy generation metrics**, not human or LLM judgement.
- **Hosted LLMs were not evaluated** (no paid API calls were made). The LiteLLM path is covered by mocked unit tests for success, streaming, timeouts and provider errors only.
- Latency is from a single laptop with other applications running; treat it as relative, not absolute.

## 6. Reproducing

```powershell
# repo root; API running on :8001 (local uvicorn or `docker compose up -d`)
backend\.venv\Scripts\python.exe evaluation\scripts\run_evaluation.py --k 3
backend\.venv\Scripts\python.exe evaluation\scripts\run_evaluation.py --k 3 --skip-ablation --dataset evaluation\datasets\sample_qa_holdout.json
# with a hosted LLM (paid):
backend\.venv\Scripts\python.exe evaluation\scripts\run_evaluation.py --k 3 --skip-ablation --model gpt-4o-mini
```
