"""Embedding validation, RRF fusion, reranker ordering and query transformation."""

from __future__ import annotations

import numpy as np
import pytest

from app.core.config import Settings
from app.core.exceptions import EmbeddingDimensionError
from app.embeddings.base import EmbeddingModel
from app.embeddings.hash_embedding import HashEmbedding
from app.embeddings.service import EmbeddingService
from app.retrieval.hybrid_search import reciprocal_rank_fusion
from app.retrieval.query_processing import (
    contextualize_query,
    is_followup,
    parse_query_variants,
    preprocess_query,
    prf_expansion_terms,
)
from app.retrieval.reranker import LexicalOverlapReranker
from app.retrieval.types import RetrievedChunk


def chunk(cid: str, content: str = "text", **scores) -> RetrievedChunk:
    return RetrievedChunk(chunk_id=cid, document_id="d", filename="f.txt", file_type="txt", content=content,
                          chunk_index=0, char_start=0, char_end=len(content), **scores)


class BrokenModel(EmbeddingModel):
    name, dimension, max_seq_length = "broken", 384, 256

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def _encode(self, texts, *, batch_size, is_query):  # noqa: ANN001
        return np.ones((len(texts), 128), dtype=np.float32)  # wrong dimension


class TestEmbeddings:
    def test_vectors_are_unit_normalised_with_expected_shape(self) -> None:
        vecs = HashEmbedding(384).embed(["annual leave policy", "solar inverter"])
        assert vecs.shape == (2, 384)
        assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0)

    def test_wrong_output_dimension_is_rejected(self) -> None:
        with pytest.raises(EmbeddingDimensionError):
            BrokenModel().embed(["x"])

    def test_service_refuses_model_column_dimension_mismatch(self) -> None:
        with pytest.raises(EmbeddingDimensionError):
            EmbeddingService(HashEmbedding(768), Settings(embedding_dimension=384))

    def test_service_refuses_chunks_larger_than_model_window(self) -> None:
        model = HashEmbedding(384)
        model.max_seq_length = 128
        with pytest.raises(ValueError, match="max_seq_length"):
            EmbeddingService(model, Settings(embedding_dimension=384, chunk_size_tokens=200, chunk_overlap_tokens=10))

    def test_empty_batch(self) -> None:
        assert HashEmbedding(384).embed([]).shape == (0, 384)


class TestRRF:
    def test_documents_in_both_lists_rank_first(self) -> None:
        vector = [chunk("a", vector_score=0.9), chunk("b", vector_score=0.8), chunk("c", vector_score=0.7)]
        keyword = [chunk("c", keyword_score=0.5), chunk("d", keyword_score=0.4), chunk("a", keyword_score=0.1)]
        fused = reciprocal_rank_fusion([vector, keyword], k=60)
        assert [c.chunk_id for c in fused][:2] == ["a", "c"]
        a = fused[0]
        assert a.fused_score == pytest.approx(1 / 61 + 1 / 63, abs=1e-6)
        assert a.vector_score == 0.9 and a.keyword_score == 0.1  # evidence from both stages preserved

    def test_weights_and_limit(self) -> None:
        fused = reciprocal_rank_fusion([[chunk("a")], [chunk("b")]], weights=[1.0, 2.0], limit=1)
        assert [c.chunk_id for c in fused] == ["b"]

    def test_weight_length_mismatch(self) -> None:
        with pytest.raises(ValueError):
            reciprocal_rank_fusion([[chunk("a")]], weights=[1, 2])


async def test_reranker_orders_and_filters() -> None:
    candidates = [chunk("x", "inverter fan cleaning schedule"), chunk("y", "annual leave days for employees")]
    ranked = await LexicalOverlapReranker().rerank("how many annual leave days", candidates, top_k=5, min_score=-4)
    assert [c.chunk_id for c in ranked] == ["y"]
    assert ranked[0].rerank_score is not None


class TestQueryProcessing:
    def test_preprocess(self) -> None:
        assert preprocess_query("  what\x00 is\n\tthis  ") == "what is this"
        assert len(preprocess_query("a" * 5000)) == 1000

    @pytest.mark.parametrize(("q", "expected"), [
        ("What about managers?", True),
        ("Does it apply to contractors?", True),
        ("And for part-time staff?", True),
        ("How many days of annual leave do employees with two years of service receive?", False),
    ])
    def test_followup_detection(self, q: str, expected: bool) -> None:
        assert is_followup(q) is expected

    def test_contextualize_only_followups(self) -> None:
        prev = ["What is the sick leave policy?"]
        assert contextualize_query("What about contractors?", prev) == "What is the sick leave policy? What about contractors?"
        standalone = "What torque is required for the inverter DC terminals?"
        assert contextualize_query(standalone, prev) == standalone

    def test_prf_mines_shared_terms_not_query_terms(self) -> None:
        feedback = [
            chunk("1", "Annual leave entitlement: employees accrue vacation days monthly.", vector_score=0.8),
            chunk("2", "Vacation days and annual leave must be requested through the HR portal.", vector_score=0.7),
            chunk("3", "Unused vacation days expire on March 31.", vector_score=0.6),
        ]
        terms = prf_expansion_terms("how much time off do I get", feedback)
        assert "vacation" in terms
        assert "time" not in terms

    def test_parse_query_variants(self) -> None:
        text = "1. annual leave entitlement\n- vacation days allowance\n\nannual leave entitlement\nWhat is the leave policy?"
        assert parse_query_variants(text, "What is the leave policy?", 3) == [
            "annual leave entitlement", "vacation days allowance"]
