"""Evaluation runner: executes retrieval (+ optional generation) for each dataset
item under each configuration and aggregates the metrics defined in ``metrics.py``.

Caches are bypassed (retrieval cache off, semantic cache off) so latencies and
quality reflect real computation, not cache hits.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.evaluation import metrics as m
from app.rag.pipeline import RAGOptions
from app.retrieval.types import RetrievalOptions
from app.schemas.rag import EvalItem, RAGSettings, RAGSettingsUpdate
from app.services.container import AppContainer
from app.services.settings_service import rag_options, retrieval_options

logger = get_logger(__name__)
SAMPLE_DATASET = Path(__file__).resolve().parents[3] / "evaluation" / "datasets" / "sample_qa.json"


def load_sample_dataset() -> list[EvalItem]:
    data = json.loads(SAMPLE_DATASET.read_text(encoding="utf-8"))
    return [EvalItem.model_validate(i) for i in data["items"]]


def describe(cfg: RAGSettings, rerank_available: bool) -> str:
    parts = [cfg.search_mode]
    if cfg.search_mode == "hybrid" and cfg.query_expansion != "none":
        parts.append(cfg.query_expansion)
    if cfg.rerank and rerank_available:
        parts.append("rerank")
    return "+".join(parts)


async def _evaluate_item(
    container: AppContainer, session: AsyncSession, user_id: uuid.UUID, item: EvalItem,
    r_opts: RetrievalOptions, g_opts: RAGOptions | None, k: int,
) -> dict[str, Any]:
    t = time.perf_counter()
    retrieval = await container.retriever.retrieve(
        session, owner_id=user_id, query=item.question, options=r_opts, llm_model=g_opts.model if g_opts else None
    )
    retrieval_ms = (time.perf_counter() - t) * 1000
    texts = [c.content for c in retrieval.chunks]
    row: dict[str, Any] = {
        "id": item.id,
        "question": item.question,
        "answerable": item.answerable,
        "retrieval_ms": round(retrieval_ms, 2),
        "retrieved": [
            {"filename": c.filename, "page": c.page_number, "chunk_id": c.chunk_id,
             "relevant": m.is_relevant(c.content, item.evidence) if item.evidence else None,
             "vector_score": c.vector_score, "rerank_score": c.rerank_score}
            for c in retrieval.chunks
        ],
    }
    if item.answerable and item.evidence:
        row.update(m.retrieval_metrics(texts, item.evidence, k))
        if item.expected_documents:
            row["expected_document_in_top_k"] = float(any(
                c.filename in item.expected_documents for c in retrieval.chunks[:k]))

    if g_opts is not None:
        t = time.perf_counter()
        answer = await container.pipeline.answer(session, owner_id=user_id, question=item.question, options=g_opts)
        row["e2e_ms"] = round((time.perf_counter() - t) * 1000, 2)
        row["answer"] = answer.answer
        row["insufficient_evidence"] = answer.insufficient_evidence
        row["prompt_tokens"] = answer.usage.get("prompt_tokens", 0)
        row["completion_tokens"] = answer.usage.get("completion_tokens", 0)
        row["cost_usd"] = answer.usage.get("cost_usd")
        row["context_tokens"] = answer.usage.get("context_tokens", 0)
        row["citation_validity"] = 0.0 if answer.verification.get("invalid_markers_removed") else 1.0
        row["grounding_score"] = answer.verification.get("grounding_score")
        if item.answerable:
            row["abstention_correct"] = 0.0 if answer.insufficient_evidence else 1.0
            if not answer.insufficient_evidence:
                ctx = [s["content"] for s in answer.sources]
                row["faithfulness"] = m.faithfulness(answer.answer, ctx)
                vecs = await container.embeddings.embed_queries([item.question, answer.answer])
                row["answer_relevance"] = round(float(np.dot(vecs[0], vecs[1])), 4)
                row["answer_term_recall"] = m.answer_term_recall(answer.answer, item.expected_answer)
                if item.evidence:
                    row["context_relevance"] = (
                        sum(m.is_relevant(t, item.evidence) for t in ctx) / len(ctx) if ctx else 0.0)
                    cited = [c["index"] for c in answer.citations]
                    by_idx = {s["index"]: s for s in answer.sources}
                    row["citation_precision"] = (
                        sum(m.is_relevant(by_idx[i]["content"], item.evidence) for i in cited) / len(cited)
                        if cited else 0.0)
                    row["cited_documents"] = sorted({c["filename"] for c in answer.citations})
        else:
            row["abstention_correct"] = 1.0 if answer.insufficient_evidence else 0.0
    return row


def _aggregate(rows: list[dict[str, Any]], k: int) -> dict[str, Any]:
    answerable = [r for r in rows if r["answerable"]]
    unanswerable = [r for r in rows if not r["answerable"]]
    agg: dict[str, Any] = {
        "items": len(rows),
        "answerable_items": len(answerable),
        "unanswerable_items": len(unanswerable),
        "k": k,
        "retrieval": {
            key: m.mean([r.get(key) for r in answerable])
            for key in ("precision_at_k", "recall_at_k", "hit_at_k", "mrr", "ndcg_at_k", "expected_document_in_top_k")
        },
        "latency_ms": {"retrieval": m.latency_summary([r["retrieval_ms"] for r in rows])},
    }
    if any("answer" in r for r in rows):
        agg["generation"] = {
            "faithfulness": m.mean([r.get("faithfulness") for r in answerable]),
            "answer_relevance": m.mean([r.get("answer_relevance") for r in answerable]),
            "context_relevance": m.mean([r.get("context_relevance") for r in answerable]),
            "citation_precision": m.mean([r.get("citation_precision") for r in answerable]),
            "citation_validity": m.mean([r.get("citation_validity") for r in rows]),
            "answer_term_recall": m.mean([r.get("answer_term_recall") for r in answerable]),
            "grounding_score": m.mean([r.get("grounding_score") for r in answerable]),
            "answer_rate_on_answerable": m.mean([r.get("abstention_correct") for r in answerable]),
            "abstention_accuracy_on_unanswerable": m.mean([r.get("abstention_correct") for r in unanswerable]),
        }
        agg["latency_ms"]["end_to_end"] = m.latency_summary([r["e2e_ms"] for r in rows if "e2e_ms" in r])
        agg["tokens"] = {
            "prompt_total": sum(int(r.get("prompt_tokens") or 0) for r in rows),
            "completion_total": sum(int(r.get("completion_tokens") or 0) for r in rows),
            "context_avg": m.mean([r.get("context_tokens") for r in rows]),
            "cost_usd_total": round(sum(float(r.get("cost_usd") or 0) for r in rows), 6),
        }
    return agg


async def run_evaluation(
    container: AppContainer,
    session: AsyncSession,
    user_id: uuid.UUID,
    base: RAGSettings,
    dataset: list[EvalItem],
    configurations: list[RAGSettingsUpdate] | None,
    *,
    k: int,
    generate_answers: bool,
) -> dict[str, Any]:
    """Run every configuration over the dataset; returns metrics + per-item rows."""
    configs = configurations or [RAGSettingsUpdate()]
    rerank_available = container.reranker is not None
    report: dict[str, Any] = {"configurations": [], "environment": {
        "embedding_model": container.embeddings.model_name,
        "reranker": container.reranker.name if container.reranker else None,
        "pgvector": container.pgvector_version,
    }}
    for update in configs:
        cfg = RAGSettings.model_validate(base.model_dump() | update.model_dump(exclude_none=True))
        cfg = cfg.model_copy(update={"top_k": max(cfg.top_k, k), "semantic_cache": False})
        r_opts = retrieval_options(cfg, rerank_available=rerank_available)
        r_opts.use_cache = False
        g_opts = None
        if generate_answers:
            g_opts = rag_options(cfg, retrieval_options(cfg, rerank_available=rerank_available))
            g_opts.retrieval.use_cache = False
            g_opts.retrieval.top_k = base.top_k if update.top_k is None else update.top_k
            g_opts.use_semantic_cache = False
        name = describe(cfg, rerank_available)
        logger.info("Evaluating configuration", extra={"config": name, "items": len(dataset)})
        rows = []
        for item in dataset:
            try:
                rows.append(await _evaluate_item(container, session, user_id, item, r_opts, g_opts, k))
            except Exception as exc:  # record the failure for this item; never hide it
                logger.exception("Evaluation item failed", extra={"item": item.id})
                rows.append({"id": item.id, "question": item.question, "answerable": item.answerable,
                             "retrieval_ms": 0.0, "error": f"{type(exc).__name__}: {exc}"[:300]})
        report["configurations"].append({
            "name": name,
            "settings": cfg.model_dump(),
            "metrics": _aggregate([r for r in rows if "error" not in r], k),
            "errors": sum(1 for r in rows if "error" in r),
            "results": rows,
        })
    return report
