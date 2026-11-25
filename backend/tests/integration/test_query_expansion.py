"""Multi-query expansion and PRF through the real retriever + pgvector (fake LLM)."""

from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import LLMProviderError
from app.ingestion.chunking import ChunkingConfig
from app.ingestion.pipeline import ingest_document
from app.models.document import Document
from app.models.user import User
from tests.factories import LEAVE_POLICY_TXT

pytestmark = pytest.mark.integration


class FakeProvider:
    def __init__(self, text: str | None = None, fail: bool = False) -> None:
        self.text, self.fail, self.prompts = text, fail, []

    async def complete_text(self, prompt: str, *, model: str, max_tokens: int = 200) -> str:
        self.prompts.append(prompt)
        if self.fail:
            raise LLMProviderError("provider down")
        return self.text or ""


class FakeRouter:
    def __init__(self, provider: FakeProvider) -> None:
        self.provider = provider

    def is_local(self, model: str) -> bool:
        return model == "local"

    def for_model(self, model: str) -> FakeProvider:
        return self.provider


async def _seed(container) -> uuid.UUID:
    async with container.db.session_factory() as s:
        user = User(email=f"{uuid.uuid4().hex[:6]}@x.com", hashed_password="x")
        s.add(user)
        await s.flush()
        path = container.settings.storage_dir / f"{uuid.uuid4()}.txt"
        path.write_bytes(LEAVE_POLICY_TXT.encode())
        doc = Document(owner_id=user.id, filename="leave.txt", file_type="txt", content_type="text/plain",
                       size_bytes=1, sha256=uuid.uuid4().hex, storage_path=str(path))
        s.add(doc)
        await s.commit()
        doc_id, user_id = doc.id, user.id
    await ingest_document(container, doc_id, ChunkingConfig("recursive", 40, 8))
    return user_id


async def test_multi_query_fuses_llm_variants(container) -> None:
    user_id = await _seed(container)
    provider = FakeProvider("1. vacation days entitlement\n- paid annual leave per year\nHow much time off?")
    container.retriever.llm_router = FakeRouter(provider)
    opts = container.retriever.default_options(query_expansion="multi_query", mode="hybrid", use_cache=False)
    async with container.db.session_factory() as s:
        result = await container.retriever.retrieve(s, owner_id=user_id, query="How much time off?",
                                                    options=opts, llm_model="gpt-4o-mini")
    assert result.query_variants == ["vacation days entitlement", "paid annual leave per year"]
    assert "multi_query" in result.timings_ms
    assert result.expanded_terms == []  # PRF is skipped when LLM variants exist
    assert any("annual leave" in c.content for c in result.chunks)
    assert "How much time off?" in provider.prompts[0]


async def test_multi_query_degrades_to_prf_when_llm_fails_or_local(container) -> None:
    user_id = await _seed(container)
    container.retriever.llm_router = FakeRouter(FakeProvider(fail=True))
    opts = container.retriever.default_options(query_expansion="multi_query", mode="hybrid", use_cache=False)
    async with container.db.session_factory() as s:
        failed = await container.retriever.retrieve(s, owner_id=user_id, query="sick leave certificate",
                                                    options=opts, llm_model="gpt-4o-mini")
        local = await container.retriever.retrieve(s, owner_id=user_id, query="sick leave certificate",
                                                   options=opts, llm_model="local")
    for result in (failed, local):
        assert result.query_variants == [] and result.chunks  # retrieval still succeeds
    assert failed.expanded_terms == local.expanded_terms  # PRF fallback applied identically


async def test_default_options_respect_overrides(container) -> None:
    opts = container.retriever.default_options(top_k=7, mode=None)
    assert opts.top_k == 7 and opts.mode == container.settings.search_mode
    assert opts.candidate_k == 7 * opts.candidate_multiplier
