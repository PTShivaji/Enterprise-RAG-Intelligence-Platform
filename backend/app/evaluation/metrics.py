"""RAG evaluation metrics (deterministic, local).

Relevance labelling
-------------------
Each dataset item lists ``evidence`` phrases copied from the source documents.
A retrieved chunk is *relevant* when it contains >= ``EVIDENCE_MATCH`` of an
evidence phrase's content terms. Labels are therefore independent of chunk IDs
and boundaries, so different chunking strategies / models can be compared on the
same dataset without re-labelling.

Retrieval metrics (binary relevance, rank-aware)
  precision@k  = relevant chunks in top-k / k
  recall@k     = evidence phrases covered by top-k / all evidence phrases
  hit@k        = 1 if any relevant chunk in top-k
  MRR          = 1 / rank of first relevant chunk (0 if none)
  nDCG@k       = DCG / ideal DCG with binary gains

Generation metrics (local proxies — clearly not LLM-judged)
  faithfulness       share of factual answer sentences whose content terms are
                     >= 60% contained in the provided context (lexical support)
  answer_relevance   cosine(question, answer) with the embedding model
  context_relevance  share of context sources that are relevant (context precision)
  citation_precision share of cited sources that are relevant
  citation_validity  1 if no invalid citation markers were produced
  answer_term_recall share of expected-answer key terms present in the answer
  abstention         correct abstain on unanswerable / no false abstain on answerable
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence

from app.core.text import containment, content_terms, split_sentences

EVIDENCE_MATCH = 0.8
FAITHFUL_SUPPORT = 0.6


def evidence_hits(chunk_text: str, evidence: Sequence[str]) -> set[int]:
    """Indices of evidence phrases contained in ``chunk_text``."""
    terms = set(content_terms(chunk_text))
    hits = set()
    for i, phrase in enumerate(evidence):
        phrase_terms = content_terms(phrase)
        if phrase_terms and containment(phrase_terms, terms) >= EVIDENCE_MATCH:
            hits.add(i)
    return hits


def is_relevant(chunk_text: str, evidence: Sequence[str]) -> bool:
    return bool(evidence_hits(chunk_text, evidence))


def retrieval_metrics(retrieved: Sequence[str], evidence: Sequence[str], k: int) -> dict[str, float]:
    top = list(retrieved[:k])
    rel = [is_relevant(t, evidence) for t in top]
    covered: set[int] = set()
    for t in top:
        covered |= evidence_hits(t, evidence)
    first = next((i for i, r in enumerate(rel, start=1) if r), None)
    dcg = sum(1.0 / math.log2(i + 1) for i, r in enumerate(rel, start=1) if r)
    ideal_hits = min(k, max(len(evidence), 1))
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return {
        "precision_at_k": sum(rel) / k,
        "recall_at_k": len(covered) / len(evidence) if evidence else 0.0,
        "hit_at_k": 1.0 if first else 0.0,
        "mrr": 1.0 / first if first else 0.0,
        "ndcg_at_k": dcg / idcg if idcg else 0.0,
    }


def faithfulness(answer: str, context_texts: Sequence[str]) -> float | None:
    """Lexical support of answer sentences by the context (None if nothing to judge)."""
    ctx_terms: set[str] = set()
    for t in context_texts:
        ctx_terms |= set(content_terms(t))
    scores = []
    for sentence in split_sentences(answer):
        terms = content_terms(sentence)
        if len(terms) < 3 or sentence.lower().startswith(("based on your documents", "i could not find")):
            continue
        scores.append(1.0 if containment(terms, ctx_terms) >= FAITHFUL_SUPPORT else 0.0)
    return sum(scores) / len(scores) if scores else None


def answer_term_recall(answer: str, expected: str | None) -> float | None:
    if not expected:
        return None
    exp = list(dict.fromkeys(content_terms(expected)))
    return containment(exp, set(content_terms(answer))) if exp else None


def mean(values: Sequence[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def percentile(values: Sequence[float], q: float) -> float | None:
    vals = sorted(values)
    if not vals:
        return None
    if len(vals) == 1:
        return round(vals[0], 2)
    idx = (len(vals) - 1) * q
    lo, hi = math.floor(idx), math.ceil(idx)
    return round(vals[lo] + (vals[hi] - vals[lo]) * (idx - lo), 2)


def latency_summary(values: Sequence[float]) -> dict[str, float | None]:
    return {
        "mean": round(statistics.fmean(values), 2) if values else None,
        "p50": percentile(values, 0.5),
        "p95": percentile(values, 0.95),
    }
