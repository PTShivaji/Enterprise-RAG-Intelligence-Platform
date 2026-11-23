"""Hybrid retrieval via Reciprocal Rank Fusion (RRF).

Why RRF instead of a weighted sum of scores? Cosine similarity (~0.2-0.8) and
``ts_rank`` (~0.0-0.1, unbounded) live on incomparable scales, and their
distributions shift per query. RRF uses only *ranks*:

    RRF(d) = sum_i  w_i / (k + rank_i(d))

so no score calibration is needed, and documents ranked well by *both* lists
rise to the top. ``k`` (default 60, from Cormack et al. 2009) damps the
influence of top ranks so one list cannot dominate.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.retrieval.types import RetrievedChunk


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[RetrievedChunk]],
    *,
    k: int = 60,
    weights: Sequence[float] | None = None,
    limit: int | None = None,
) -> list[RetrievedChunk]:
    """Fuse several ranked lists into one, merging per-stage scores per chunk."""
    if weights is None:
        weights = [1.0] * len(ranked_lists)
    if len(weights) != len(ranked_lists):
        raise ValueError("weights must match the number of ranked lists")

    merged: dict[str, RetrievedChunk] = {}
    scores: dict[str, float] = {}
    for weight, ranked in zip(weights, ranked_lists, strict=True):
        for rank, chunk in enumerate(ranked, start=1):
            existing = merged.get(chunk.chunk_id)
            if existing is None:
                existing = RetrievedChunk.from_dict(chunk.to_dict())
                merged[chunk.chunk_id] = existing
            else:  # keep the best per-stage evidence from every list
                if chunk.vector_score is not None and (
                    existing.vector_score is None or chunk.vector_score > existing.vector_score
                ):
                    existing.vector_score, existing.vector_rank = chunk.vector_score, chunk.vector_rank
                if chunk.keyword_score is not None and existing.keyword_score is None:
                    existing.keyword_score, existing.keyword_rank = chunk.keyword_score, chunk.keyword_rank
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + weight / (k + rank)

    fused = sorted(merged.values(), key=lambda c: (-scores[c.chunk_id], c.chunk_id))
    for chunk in fused:
        chunk.fused_score = round(scores[chunk.chunk_id], 6)
    return fused[:limit] if limit is not None else fused
