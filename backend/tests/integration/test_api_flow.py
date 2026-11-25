"""End-to-end API tests against PostgreSQL + pgvector (hash embeddings, local LLM mode).

Covers: auth, upload validation, ingestion, vector/keyword/hybrid retrieval,
metadata filters, grounded chat with citations, streaming, conversation memory,
cache invalidation, user isolation, analytics and evaluation.
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest

from tests.conftest import register_and_login
from tests.factories import LEAVE_POLICY_TXT, make_docx, make_pdf

pytestmark = pytest.mark.integration


async def upload(client: httpx.AsyncClient, headers: dict, name: str, data: bytes, ctype: str = "text/plain") -> dict:
    r = await client.post("/documents/upload", headers=headers, files={"file": (name, data, ctype)})
    assert r.status_code == 201, r.text
    return r.json()


async def indexed(client: httpx.AsyncClient, headers: dict, name: str, data: bytes, ctype: str = "text/plain") -> str:
    body = await upload(client, headers, name, data, ctype)
    doc_id = body["document"]["id"]
    status = (await client.get(f"/documents/{doc_id}/status", headers=headers)).json()
    assert status["status"] == "indexed", status  # background task completes within the ASGI call
    return doc_id


# --------------------------------------------------------------------------- auth
class TestAuth:
    async def test_register_login_me_logout(self, client: httpx.AsyncClient) -> None:
        headers = await register_and_login(client, "admin@example.com")
        me = (await client.get("/auth/me", headers=headers)).json()
        assert me["email"] == "admin@example.com" and me["role"] == "admin"
        assert (await client.post("/auth/logout", headers=headers)).status_code == 200
        r = await client.get("/auth/me", headers=headers)
        assert r.status_code == 401 and r.json()["message"] == "Token has been revoked"

    async def test_rejections(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/documents")).status_code == 401
        assert (await client.get("/documents", headers={"Authorization": "Bearer junk"})).status_code == 401
        await register_and_login(client, "bob@example.com")
        dup = await client.post("/auth/register", json={"email": "BOB@example.com", "password": "Passw0rd!x"})
        assert dup.status_code == 409
        bad = await client.post("/auth/login", json={"email": "bob@example.com", "password": "wrong-pass1"})
        assert bad.status_code == 401 and bad.json()["error"] == "unauthorized"
        weak = await client.post("/auth/register", json={"email": "c@example.com", "password": "short"})
        assert weak.status_code == 422

    async def test_swagger_form_login(self, client: httpx.AsyncClient) -> None:
        await register_and_login(client, "form@example.com")
        r = await client.post("/auth/token", data={"username": "form@example.com", "password": "Passw0rd!x"})
        assert r.status_code == 200 and r.json()["token_type"] == "bearer"


# ---------------------------------------------------------------------- documents
class TestDocuments:
    async def test_upload_ingest_all_formats(self, client: httpx.AsyncClient, auth_headers: dict) -> None:
        txt = await indexed(client, auth_headers, "leave_policy.txt", LEAVE_POLICY_TXT.encode())
        pdf = await indexed(client, auth_headers, "inverter.pdf", make_pdf(), "application/pdf")
        docx = await indexed(client, auth_headers, "security.docx", make_docx(),
                             "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        listing = (await client.get("/documents", headers=auth_headers)).json()
        assert listing["total"] == 3
        pdf_doc = (await client.get(f"/documents/{pdf}", headers=auth_headers)).json()
        assert pdf_doc["page_count"] == 2 and pdf_doc["chunk_count"] >= 1
        assert pdf_doc["embedding_model"] == "hash-bow-384"
        chunks = (await client.get(f"/documents/{pdf}/chunks", headers=auth_headers)).json()["items"]
        assert {c["page_number"] for c in chunks} <= {1, 2} and all(c["page_number"] for c in chunks)
        docx_chunks = (await client.get(f"/documents/{docx}/chunks", headers=auth_headers)).json()["items"]
        assert all(c["page_number"] is None for c in docx_chunks)  # never invented
        assert txt

    async def test_duplicate_detection(self, client: httpx.AsyncClient, auth_headers: dict) -> None:
        first = await upload(client, auth_headers, "a.txt", LEAVE_POLICY_TXT.encode())
        second = await upload(client, auth_headers, "renamed.txt", LEAVE_POLICY_TXT.encode())
        assert second["duplicate"] and second["document"]["id"] == first["document"]["id"]
        assert not second["ingestion_queued"]

    async def test_validation_errors(self, client: httpx.AsyncClient, auth_headers: dict, container) -> None:
        r = await client.post("/documents/upload", headers=auth_headers, files={"file": ("x.exe", b"MZ..", "application/octet-stream")})
        assert r.status_code == 415
        r = await client.post("/documents/upload", headers=auth_headers, files={"file": ("x.pdf", b"not a pdf", "application/pdf")})
        assert r.status_code == 415
        r = await client.post("/documents/upload", headers=auth_headers, files={"file": ("e.txt", b"", "text/plain")})
        assert r.status_code == 422
        container.settings.max_upload_size_mb = 1
        try:
            r = await client.post("/documents/upload", headers=auth_headers,
                                  files={"file": ("big.txt", b"a" * (1024 * 1024 + 1), "text/plain")})
            assert r.status_code == 413
        finally:
            container.settings.max_upload_size_mb = 25

    async def test_corrupted_file_marks_document_failed(self, client: httpx.AsyncClient, auth_headers: dict) -> None:
        body = await upload(client, auth_headers, "broken.pdf", b"%PDF-1.4 garbage garbage", "application/pdf")
        status = (await client.get(f"/documents/{body['document']['id']}/status", headers=auth_headers)).json()
        assert status["status"] == "failed" and "corrupted" in status["error_message"]

    async def test_reingest_with_new_chunking_and_delete(self, client: httpx.AsyncClient, auth_headers: dict) -> None:
        doc_id = await indexed(client, auth_headers, "leave.txt", LEAVE_POLICY_TXT.encode())
        before = {c["id"] for c in (await client.get(f"/documents/{doc_id}/chunks", headers=auth_headers)).json()["items"]}
        r = await client.post(f"/documents/{doc_id}/ingest", headers=auth_headers,
                              json={"chunk_strategy": "fixed", "chunk_size_tokens": 32, "chunk_overlap_tokens": 4})
        assert r.status_code == 202
        after = (await client.get(f"/documents/{doc_id}", headers=auth_headers)).json()
        assert after["status"] == "indexed"
        assert after["chunking_config"] == {"strategy": "fixed", "chunk_size": 32, "overlap": 4}
        chunks = (await client.get(f"/documents/{doc_id}/chunks", headers=auth_headers)).json()["items"]
        assert len(chunks) == after["chunk_count"] and all(c["token_count"] <= 32 for c in chunks)
        assert {c["id"] for c in chunks} != before  # old chunks replaced atomically
        assert (await client.delete(f"/documents/{doc_id}", headers=auth_headers)).status_code == 200
        assert (await client.get(f"/documents/{doc_id}", headers=auth_headers)).status_code == 404
        search = await client.post("/search", headers=auth_headers, json={"query": "annual leave"})
        assert search.json()["results"] == []  # chunks were removed with the document


# ---------------------------------------------------------------------- retrieval
class TestSearch:
    @pytest.mark.parametrize("mode", ["vector", "keyword", "hybrid"])
    async def test_modes_find_relevant_chunk(self, client: httpx.AsyncClient, auth_headers: dict, mode: str) -> None:
        await indexed(client, auth_headers, "leave.txt", LEAVE_POLICY_TXT.encode())
        await indexed(client, auth_headers, "inverter.pdf", make_pdf(), "application/pdf")
        r = await client.post("/search", headers=auth_headers,
                              json={"query": "DC terminals torque annual inspection", "search_mode": mode, "top_k": 3})
        body = r.json()
        assert r.status_code == 200 and body["search_mode"] == mode
        top = body["results"][0]
        assert "2.5 Nm" in top["content"] and top["filename"] == "inverter.pdf"
        assert top["page_number"] == 2 and top["page_end"] == 2  # page-local chunk, exact page citation
        if mode == "hybrid":
            assert top["fused_score"] is not None and top["rerank_score"] is not None
        if mode == "keyword":
            assert top["keyword_score"] > 0

    async def test_filters_and_debug_stages(self, client: httpx.AsyncClient, auth_headers: dict) -> None:
        leave = await indexed(client, auth_headers, "leave.txt", LEAVE_POLICY_TXT.encode())
        await indexed(client, auth_headers, "inverter.pdf", make_pdf(), "application/pdf")
        r = await client.post("/search", headers=auth_headers, json={
            "query": "inspection", "filters": {"file_types": ["txt"]}, "debug": True})
        body = r.json()
        assert all(x["file_type"] == "txt" for x in body["results"])
        assert set(body["stages"]) == {"vector", "keyword", "fused", "final"}
        r = await client.post("/search", headers=auth_headers, json={
            "query": "inspection torque", "filters": {"document_ids": [leave]}})
        assert all(x["document_id"] == leave for x in r.json()["results"])
        r = await client.post("/search", headers=auth_headers, json={
            "query": "torque", "filters": {"page_from": 2, "page_to": 2, "file_types": ["pdf"]}})
        results = r.json()["results"]
        assert results and all(x["page_number"] <= 2 <= (x["page_end"] or x["page_number"]) for x in results)

    async def test_retrieval_cache_hit_then_invalidated_by_upload(self, client: httpx.AsyncClient, auth_headers: dict) -> None:
        await indexed(client, auth_headers, "leave.txt", LEAVE_POLICY_TXT.encode())
        q = {"query": "sick leave medical certificate"}
        assert (await client.post("/search", headers=auth_headers, json=q)).json()["cache_hit"] is False
        assert (await client.post("/search", headers=auth_headers, json=q)).json()["cache_hit"] is True
        await indexed(client, auth_headers, "inverter.pdf", make_pdf(), "application/pdf")
        assert (await client.post("/search", headers=auth_headers, json=q)).json()["cache_hit"] is False
        history = (await client.get("/search/history", headers=auth_headers)).json()
        assert len(history) == 3 and history[0]["query"] == q["query"]


# ---------------------------------------------------------------------------- chat
class TestChat:
    async def test_grounded_answer_with_verified_citations(self, client: httpx.AsyncClient, auth_headers: dict) -> None:
        doc_id = await indexed(client, auth_headers, "inverter.pdf", make_pdf(), "application/pdf")
        await indexed(client, auth_headers, "leave.txt", LEAVE_POLICY_TXT.encode())
        r = await client.post("/chat", headers=auth_headers,
                              json={"message": "What torque should the DC terminals be tightened to?"})
        body = r.json()
        assert r.status_code == 200, body
        assert "2.5 Nm" in body["answer"] and not body["insufficient_evidence"]
        cite = next(c for c in body["citations"] if "2.5 Nm" in c["text"])
        assert cite["document_id"] == doc_id and cite["filename"] == "inverter.pdf" and cite["page_number"] == 2
        assert cite["chunk_id"] and cite["retrieval_score"] is not None
        assert body["verification"]["invalid_markers_removed"] == []
        assert body["provider"] == "local-extractive" and body["usage"]["cost_usd"] == 0.0

    async def test_insufficient_evidence(self, client: httpx.AsyncClient, auth_headers: dict, container) -> None:
        r = await client.post("/chat", headers=auth_headers, json={"message": "What is the CEO's favourite colour?"})
        assert r.json()["insufficient_evidence"] and r.json()["citations"] == []  # no documents at all
        await indexed(client, auth_headers, "leave.txt", LEAVE_POLICY_TXT.encode())
        container.retriever.settings  # noqa: B018
        r = await client.post("/chat", headers=auth_headers,
                              json={"message": "Which volcano erupted near Reykjavik in 2024?"})
        assert r.json()["insufficient_evidence"]

    async def test_semantic_cache_reuses_answer(self, client: httpx.AsyncClient, auth_headers: dict) -> None:
        await indexed(client, auth_headers, "inverter.pdf", make_pdf(), "application/pdf")
        q = "What torque should the DC terminals be tightened to?"
        first = (await client.post("/chat", headers=auth_headers, json={"message": q})).json()
        second = (await client.post("/chat", headers=auth_headers, json={"message": q})).json()
        assert not first["semantic_cache_hit"] and second["semantic_cache_hit"]
        assert second["answer"] == first["answer"] and second["citations"] == first["citations"]

    async def test_streaming_events(self, client: httpx.AsyncClient, auth_headers: dict) -> None:
        await indexed(client, auth_headers, "inverter.pdf", make_pdf(), "application/pdf")
        events: list[tuple[str, dict]] = []
        async with client.stream("POST", "/chat/stream", headers=auth_headers,
                                 json={"message": "How often should the air filters be cleaned?"}) as r:
            assert r.headers["content-type"].startswith("text/event-stream")
            event = None
            async for line in r.aiter_lines():
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: "):
                    events.append((event, json.loads(line[6:])))
        kinds = [e for e, _ in events]
        assert kinds[0] == "conversation" and kinds[1] == "sources" and kinds[-1] == "done"
        assert "token" in kinds
        streamed = "".join(d["text"] for e, d in events if e == "token")
        done = events[-1][1]
        assert "six months" in done["answer"] and streamed.strip() == done["answer"].strip()
        conv = (await client.get(f"/conversations/{done['conversation_id']}", headers=auth_headers)).json()
        assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]
        assert conv["messages"][1]["citations"]

    async def test_conversation_memory_followup(self, client: httpx.AsyncClient, auth_headers: dict) -> None:
        await indexed(client, auth_headers, "leave.txt", LEAVE_POLICY_TXT.encode())
        first = (await client.post("/chat", headers=auth_headers, json={"message": "What is the sick leave policy?"})).json()
        follow = (await client.post("/chat", headers=auth_headers, json={
            "message": "What about a medical certificate?", "conversation_id": first["conversation_id"]})).json()
        assert follow["conversation_id"] == first["conversation_id"]
        assert follow["retrieval_query"].startswith("What is the sick leave policy?")  # contextualised
        assert "certificate" in follow["answer"]
        convs = (await client.get("/conversations", headers=auth_headers)).json()
        assert len(convs) == 1 and convs[0]["title"].startswith("What is the sick leave")
        assert (await client.delete(f"/conversations/{first['conversation_id']}", headers=auth_headers)).status_code == 200
        assert (await client.get("/conversations", headers=auth_headers)).json() == []

    async def test_disallowed_model_rejected(self, client: httpx.AsyncClient, auth_headers: dict) -> None:
        r = await client.post("/chat", headers=auth_headers, json={"message": "hi", "model": "evil/expensive-model"})
        assert r.status_code == 422


# -------------------------------------------------------------------- isolation
async def test_user_isolation_across_documents_search_chat_and_conversations(client: httpx.AsyncClient) -> None:
    alice = await register_and_login(client, "alice@example.com")
    bob = await register_and_login(client, "bob2@example.com")
    doc = await indexed(client, alice, "inverter.pdf", make_pdf(), "application/pdf")
    chat = (await client.post("/chat", headers=alice, json={"message": "What torque for the DC terminals?"})).json()

    assert (await client.get(f"/documents/{doc}", headers=bob)).status_code == 404
    assert (await client.get(f"/documents/{doc}/chunks", headers=bob)).status_code == 404
    assert (await client.delete(f"/documents/{doc}", headers=bob)).status_code == 404
    assert (await client.post(f"/documents/{doc}/ingest", headers=bob)).status_code == 404
    assert (await client.get("/documents", headers=bob)).json()["total"] == 0
    for mode in ("vector", "keyword", "hybrid"):
        r = await client.post("/search", headers=bob, json={"query": "DC terminals torque", "search_mode": mode,
                                                            "filters": {"document_ids": [doc]}})
        assert r.json()["results"] == []
    bob_chat = (await client.post("/chat", headers=bob, json={"message": "What torque for the DC terminals?"})).json()
    assert bob_chat["insufficient_evidence"] and not bob_chat["semantic_cache_hit"]  # never Alice's cached answer
    assert (await client.get(f"/conversations/{chat['conversation_id']}", headers=bob)).status_code == 404
    r = await client.post("/chat", headers=bob, json={"message": "continue", "conversation_id": chat["conversation_id"]})
    assert r.status_code == 404
    overview = (await client.get("/analytics/overview", headers=bob)).json()
    assert overview["total_documents"] == 0 and overview["total_chunks"] == 0


# ----------------------------------------------------- settings, analytics, eval, health
async def test_settings_validation_and_effect(client: httpx.AsyncClient, auth_headers: dict, container, monkeypatch) -> None:
    monkeypatch.setattr(container.embeddings.model, "max_seq_length", 256)  # MiniLM's window
    s = (await client.get("/settings", headers=auth_headers)).json()
    assert s["search_mode"] == "hybrid"
    r = await client.put("/settings", headers=auth_headers, json={"top_k": 2, "search_mode": "keyword"})
    assert r.status_code == 200 and r.json()["top_k"] == 2
    assert (await client.put("/settings", headers=auth_headers, json={"llm_model": "not-allowed"})).status_code == 422
    assert (await client.put("/settings", headers=auth_headers, json={"chunk_size_tokens": 1000})).status_code == 422
    assert (await client.put("/settings", headers=auth_headers,
                             json={"chunk_size_tokens": 100, "chunk_overlap_tokens": 100})).status_code == 422
    await indexed(client, auth_headers, "leave.txt", LEAVE_POLICY_TXT.encode())
    body = (await client.post("/search", headers=auth_headers, json={"query": "annual leave days"})).json()
    assert body["search_mode"] == "keyword" and len(body["results"]) <= 2
    models = (await client.get("/models", headers=auth_headers)).json()
    assert models["embedding_dimension"] == 384 and "local" in models["llm_allowed_models"]


async def test_analytics_and_metrics(client: httpx.AsyncClient) -> None:
    admin = await register_and_login(client, "admin@example.com")
    await indexed(client, admin, "leave.txt", LEAVE_POLICY_TXT.encode())
    await client.post("/chat", headers=admin, json={"message": "How many sick leave days?"})
    await client.post("/search", headers=admin, json={"query": "carry over"})
    overview = (await client.get("/analytics/overview", headers=admin)).json()
    assert overview["total_documents"] == 1 and overview["total_queries"] == 2
    assert overview["avg_latency_ms"] > 0 and overview["recent_activity"]
    usage = (await client.get("/analytics/usage?days=7", headers=admin)).json()
    assert {s["event_type"] for s in usage["series"]} >= {"chat", "search", "ingest"}
    metrics = await client.get("/metrics", headers=admin)
    assert metrics.status_code == 200 and "rag_retrieval_seconds" in metrics.text
    user = await register_and_login(client)
    assert (await client.get("/metrics", headers=user)).status_code == 403


async def test_evaluation_run(client: httpx.AsyncClient, auth_headers: dict) -> None:
    await indexed(client, auth_headers, "leave.txt", LEAVE_POLICY_TXT.encode())
    await indexed(client, auth_headers, "inverter.pdf", make_pdf(), "application/pdf")
    dataset = [
        {"id": "q1", "question": "How many days of annual leave after three years of service?",
         "evidence": ["two to five years of service receive 22 days"], "expected_answer": "22 days",
         "expected_documents": ["leave.txt"]},
        {"id": "q2", "question": "What torque for the DC terminals?", "evidence": ["Torque the DC terminals to 2.5 Nm"],
         "expected_answer": "2.5 Nm"},
        {"id": "q3", "question": "Which volcano erupted near Reykjavik?", "answerable": False},
    ]
    r = await client.post("/evaluation/run", headers=auth_headers, json={
        "name": "it", "dataset": dataset, "k": 3,
        "configurations": [{"search_mode": "vector", "rerank": False}, {"search_mode": "hybrid"}]})
    assert r.status_code == 202
    run_id = r.json()["id"]
    run = (await client.get(f"/evaluation/results/{run_id}", headers=auth_headers)).json()
    assert run["status"] == "completed", run["error_message"]
    configs = run["metrics"]["configurations"]
    assert [c["name"] for c in configs] == ["vector", "hybrid+rerank"]  # PRF is opt-in by default
    for c in configs:
        assert c["errors"] == 0
        assert 0 <= c["metrics"]["retrieval"]["recall_at_k"] <= 1
        assert c["metrics"]["generation"]["abstention_accuracy_on_unanswerable"] == 1.0
    assert (await client.get("/evaluation/results", headers=auth_headers)).json()[0]["id"] == run_id


async def test_health_endpoints(client: httpx.AsyncClient) -> None:
    assert (await client.get("/health")).json()["status"] == "ok"
    ready = await client.get("/health/ready")
    body = ready.json()
    assert ready.status_code == 200 and body["status"] == "ready", body
    assert body["checks"]["vector_dimension"]["ok"] and body["checks"]["pgvector"]["version"]


async def test_request_id_and_safe_errors(client: httpx.AsyncClient, auth_headers: dict) -> None:
    r = await client.get(f"/documents/{uuid.uuid4()}", headers={**auth_headers, "X-Request-ID": "trace-12345678"})
    assert r.status_code == 404 and r.headers["X-Request-ID"] == "trace-12345678"
    assert r.json() == {"error": "not_found", "message": "Document not found", "request_id": "trace-12345678"}
    r = await client.get("/documents/not-a-uuid", headers=auth_headers)
    assert r.status_code == 422 and "Traceback" not in r.text
