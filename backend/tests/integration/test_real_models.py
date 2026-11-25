"""Behavioural tests with the REAL models (MiniLM bi-encoder + ms-marco cross-encoder).

Opt-in because they load ~180 MB of weights:  set RUN_MODEL_TESTS=1
(PowerShell:  $env:RUN_MODEL_TESTS="1"; python -m pytest -m models)
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from app.core.config import Settings
from app.retrieval.types import RetrievedChunk

pytestmark = [
    pytest.mark.models,
    pytest.mark.skipif(os.environ.get("RUN_MODEL_TESTS") != "1", reason="set RUN_MODEL_TESTS=1 to load real models"),
]

PASSAGES = [
    "Employees with two to five years of service receive 22 days of paid annual leave per year.",
    "Tighten all DC terminals to a torque of 2.5 Nm using a calibrated torque wrench.",
    "Expense claims must be submitted within 30 days of the end of the trip.",
    "Contractors do not accrue paid annual leave, sick leave or parental leave.",
]


@pytest.fixture(scope="module")
def embedder():
    from app.embeddings.sentence_transformer import SentenceTransformerEmbedding

    return SentenceTransformerEmbedding("sentence-transformers/all-MiniLM-L6-v2")


@pytest.fixture(scope="module")
def cross_encoder():
    from app.retrieval.reranker import CrossEncoderReranker

    return CrossEncoderReranker("cross-encoder/ms-marco-MiniLM-L-6-v2")


def test_model_contract(embedder) -> None:
    assert embedder.dimension == 384 and embedder.max_seq_length == 256
    vecs = embedder.embed(PASSAGES)
    assert vecs.shape == (4, 384) and np.allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-5)
    assert embedder.count_tokens("annual leave") >= 2


@pytest.mark.parametrize(("query", "expected"), [
    ("How much vacation do I get after three years?", 0),  # paraphrase: vacation ~ annual leave
    ("inverter terminal tightening specification", 1),
    ("deadline for filing travel reimbursements", 2),
])
def test_semantic_retrieval_handles_paraphrase(embedder, query: str, expected: int) -> None:
    sims = embedder.embed(PASSAGES) @ embedder.embed([query], is_query=True)[0]
    assert int(np.argmax(sims)) == expected


async def test_cross_encoder_prefers_answering_passage(cross_encoder) -> None:
    chunks = [RetrievedChunk(chunk_id=str(i), document_id="d", filename="f", file_type="txt", content=p,
                             chunk_index=i, char_start=0, char_end=len(p)) for i, p in enumerate(PASSAGES)]
    ranked = await cross_encoder.rerank("Do contractors get paid annual leave?", chunks, top_k=2)
    assert ranked[0].chunk_id == "3"  # the contractor rule, not the employee entitlement
    assert ranked[0].rerank_score > ranked[1].rerank_score


async def test_local_answerer_with_cross_encoder(embedder, cross_encoder) -> None:
    from app.embeddings.service import EmbeddingService
    from app.rag.generation import LocalExtractiveProvider
    from app.rag.types import INSUFFICIENT_EVIDENCE, ContextSource, GenerationRequest

    provider = LocalExtractiveProvider(EmbeddingService(embedder, Settings()), sentence_scorer=cross_encoder,
                                       min_answer_logit=1.0)
    sources = [ContextSource(index=i + 1, chunk_id=str(i), chunk_ids=[str(i)], document_id="d", filename="f",
                             content=p, page_number=None, page_end=None, section=None, token_count=20)
               for i, p in enumerate(PASSAGES)]

    def req(q: str) -> GenerationRequest:
        return GenerationRequest(question=q, sources=sources, messages=[], model="local")

    answer = await provider.generate(req("What torque should the DC terminals be tightened to?"))
    assert "2.5 Nm" in answer.text and "[2]" in answer.text
    assert answer.diagnostics["scorer"] == "cross-encoder" and answer.diagnostics["answerability"] > 1.0
    refusal = await provider.generate(req("What is the dress code for the office?"))
    assert refusal.text == INSUFFICIENT_EVIDENCE
