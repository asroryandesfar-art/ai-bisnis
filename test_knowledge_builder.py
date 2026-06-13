"""Tests untuk Auto Knowledge Builder: KnowledgeBuilderAgent, parser
CSV/Markdown, pipeline background, dan router bn_platform/knowledge_builder.py.

Mengikuti pola mock _call_llm_json (test_reasoning_pipeline.py) dan
FakePool/FakeConnection (test_feedback_learning.py) — tidak ada panggilan
Groq atau database sungguhan.
"""
import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from base import BaseAgent
from knowledge_builder_agent import KnowledgeBuilderAgent
from bn_platform.knowledge_builder import (
    FaqUpdateRequest,
    SopUpdateRequest,
    build_knowledge_builder_router,
)


# ─── Helpers ────────────────────────────────────────────────────

class AsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _route(router, path, method):
    for r in router.routes:
        if r.path.endswith(path) and method in r.methods:
            return r.endpoint
    raise AssertionError(f"route not found: {method} {path}")


# ─── KnowledgeBuilderAgent ──────────────────────────────────────

def test_agent_classify_summarize_faq_sop_quality(monkeypatch):
    canned = {
        "classify": {"categories": ["Pengiriman", "x" * 50], "tags": ["resi", "ongkir"], "suggested_intents": ["cek_resi"]},
        "summarize": {"summary": "  Ringkasan dokumen pengiriman.  "},
        "faqs": {"faqs": [
            {"question": "Bagaimana cek resi?", "answer": "Buka menu Lacak Pesanan.", "category": "Pengiriman"},
            {"question": "", "answer": "abaikan"},
        ]},
        "sops": {"sops": [
            {"title": "Cara Refund", "steps": ["Hubungi CS", "Isi formulir", "Tunggu 3 hari"], "category": "Refund"},
            {"title": "Tanpa langkah", "steps": []},
        ]},
        "quality": {
            "completeness_score": 150, "redundancy_score": -10,
            "coverage_score": 70, "overall_score": 80,
            "missing_topics": ["Kebijakan Garansi"], "duplicate_groups": [],
        },
    }

    async def fake_call_llm_json(self, messages, temperature=0.2, max_tokens=512, default=None):
        text = messages[-1]["content"]
        if "suggested_intents" in text:
            return canned["classify"]
        if '"summary"' in text:
            return canned["summarize"]
        if '"faqs"' in text:
            return canned["faqs"]
        if '"sops"' in text:
            return canned["sops"]
        return canned["quality"]

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_call_llm_json)
    agent = KnowledgeBuilderAgent(api_key="test-key")

    classification = asyncio.run(agent.classify(title="Panduan", text="Isi dokumen"))
    assert classification["categories"][0] == "Pengiriman"
    assert len(classification["tags"]) == 2

    summary = asyncio.run(agent.summarize(title="Panduan", text="Isi dokumen"))
    assert summary["summary"] == "Ringkasan dokumen pengiriman."

    faqs = asyncio.run(agent.generate_faqs(title="Panduan", text="Isi dokumen"))
    assert len(faqs["faqs"]) == 1
    assert faqs["faqs"][0]["category"] == "Pengiriman"

    sops = asyncio.run(agent.generate_sops(title="Panduan", text="Isi dokumen"))
    assert len(sops["sops"]) == 1
    assert sops["sops"][0]["steps"] == ["Hubungi CS", "Isi formulir", "Tunggu 3 hari"]

    quality = asyncio.run(agent.assess_quality(
        title="Panduan", text="Isi dokumen", faq_count=1, sop_count=1,
        existing_categories=["Pengiriman"],
    ))
    assert quality["completeness_score"] == 100  # clamped
    assert quality["redundancy_score"] == 0  # clamped
    assert quality["missing_topics"] == ["Kebijakan Garansi"]


def test_agent_run_returns_combined_output(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.2, max_tokens=512, default=None):
        return dict(default or {})

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_call_llm_json)
    agent = KnowledgeBuilderAgent(api_key="test-key")
    result = asyncio.run(agent.run({"title": "Panduan", "text": "Isi dokumen"}))
    assert result.success is True
    assert "quality" in result.output
    assert result.output["faqs"] == []
    assert result.output["sops"] == []


def test_agent_marks_llm_unavailable_on_failure(monkeypatch):
    async def fake_call_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        raise RuntimeError("429 quota")

    monkeypatch.setattr(BaseAgent, "_call_llm", fake_call_llm)
    agent = KnowledgeBuilderAgent(api_key="test-key")
    result = asyncio.run(agent.summarize(title="Panduan", text="Isi dokumen"))
    assert result.get("_llm_unavailable") is True


# ─── Parsers: CSV & Markdown ────────────────────────────────────

def test_csv_to_text_detects_qa_pairs():
    import main
    csv_text = "question,answer,category\nBagaimana cara refund?,Hubungi CS,Refund\nBerapa lama proses?,3 hari kerja,Refund\n"
    text = main._csv_to_text(csv_text)
    assert "Q: Bagaimana cara refund?" in text
    assert "A: Hubungi CS" in text
    assert "Q: Berapa lama proses?" in text


def test_csv_to_text_falls_back_to_columns():
    import main
    csv_text = "produk,harga\nKopi,15000\nTeh,10000\n"
    text = main._csv_to_text(csv_text)
    assert "produk: Kopi" in text
    assert "harga: 15000" in text


def test_clean_markdown_text_strips_syntax():
    import main
    md = "# Judul\n\nIni **penting** dan _miring_ serta [link](https://x.com).\n- item satu\n> catatan"
    cleaned = main._clean_markdown_text(md)
    assert "#" not in cleaned
    assert "**" not in cleaned
    assert "[link]" not in cleaned
    assert "link" in cleaned
    assert "- item satu" in cleaned
    assert cleaned.startswith("Judul")


# ─── Background pipeline ────────────────────────────────────────

class PipelineFakeConnection:
    def __init__(self, pool):
        self.pool = pool

    def transaction(self):
        return AsyncContext(self)

    async def execute(self, sql, *args):
        self.pool.calls.append(("execute", sql, args))
        return "OK"


class PipelineFakePool:
    def __init__(self, doc, chunks):
        self.doc = doc
        self.chunks = chunks
        self.calls = []
        self.connection = PipelineFakeConnection(self)

    def acquire(self):
        return AsyncContext(self.connection)

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        if "FROM documents WHERE id=" in " ".join(sql.split()):
            return self.doc
        return None

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return self.chunks

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return "OK"


def _patch_agent_methods(monkeypatch):
    async def fake_classify(self, *, title, text):
        return {"categories": ["Pengiriman"], "tags": ["resi"], "suggested_intents": ["cek_resi"]}

    async def fake_summarize(self, *, title, text):
        return {"summary": "Ringkasan dokumen."}

    async def fake_generate_faqs(self, *, title, text, max_items=8):
        return {"faqs": [{"question": "Bagaimana cek resi?", "answer": "Buka menu Lacak Pesanan.", "category": "Pengiriman"}]}

    async def fake_generate_sops(self, *, title, text, max_items=5):
        return {"sops": [{"title": "Cara Refund", "steps": ["Hubungi CS", "Tunggu 3 hari"], "category": "Refund"}]}

    async def fake_assess_quality(self, *, title, text, faq_count, sop_count, existing_categories=None):
        return {
            "completeness_score": 80, "redundancy_score": 90, "coverage_score": 70,
            "overall_score": 80, "missing_topics": ["Kebijakan Garansi"], "duplicate_groups": [],
        }

    monkeypatch.setattr(KnowledgeBuilderAgent, "classify", fake_classify)
    monkeypatch.setattr(KnowledgeBuilderAgent, "summarize", fake_summarize)
    monkeypatch.setattr(KnowledgeBuilderAgent, "generate_faqs", fake_generate_faqs)
    monkeypatch.setattr(KnowledgeBuilderAgent, "generate_sops", fake_generate_sops)
    monkeypatch.setattr(KnowledgeBuilderAgent, "assess_quality", fake_assess_quality)


def test_pipeline_persists_generated_knowledge(monkeypatch):
    import main

    doc = {"id": "doc-1", "org_id": "org-1", "bot_id": "bot-1", "filename": "Panduan.pdf", "status": "ready"}
    chunks = [{"content": "Isi dokumen tentang pengiriman dan refund."}]
    pool = PipelineFakePool(doc, chunks)

    async def fake_get_pool_safe(timeout=None):
        return pool

    monkeypatch.setattr(main, "get_pool_safe", fake_get_pool_safe)
    monkeypatch.setattr(main.cfg, "groq_api_key", "test-key")
    _patch_agent_methods(monkeypatch)
    main._knowledge_builder_agent = None

    asyncio.run(main._run_knowledge_builder_pipeline("doc-1"))

    executes = [c for c in pool.calls if c[0] == "execute"]
    assert any("kb_status='processing'" in c[1] for c in executes)
    conn_executes = [c for c in pool.connection.pool.calls if c[0] == "execute"]
    update_doc = next(c for c in conn_executes if "UPDATE documents" in c[1] and "summary=" in c[1])
    assert update_doc[2][0] == "Ringkasan dokumen."
    assert json.loads(update_doc[2][1]) == ["Pengiriman"]
    assert any("INSERT INTO kb_generated_faqs" in c[1] for c in conn_executes)
    assert any("INSERT INTO kb_generated_sops" in c[1] for c in conn_executes)
    quality_insert = next(c for c in conn_executes if "INSERT INTO kb_quality_reports" in c[1])
    assert quality_insert[2][7] == 80  # overall_score


def test_pipeline_skips_when_groq_not_configured(monkeypatch):
    import main

    doc = {"id": "doc-2", "org_id": "org-1", "bot_id": "bot-1", "filename": "Panduan.pdf", "status": "ready"}
    chunks = [{"content": "Isi dokumen."}]
    pool = PipelineFakePool(doc, chunks)

    async def fake_get_pool_safe(timeout=None):
        return pool

    monkeypatch.setattr(main, "get_pool_safe", fake_get_pool_safe)
    monkeypatch.setattr(main.cfg, "groq_api_key", "")

    asyncio.run(main._run_knowledge_builder_pipeline("doc-2"))

    executes = [c for c in pool.calls if c[0] == "execute"]
    assert any("kb_status='skipped'" in c[1] for c in executes)


# ─── Router: bn_platform/knowledge_builder ──────────────────────

class RouterFakeConnection:
    def __init__(self, pool):
        self.pool = pool

    def transaction(self):
        return AsyncContext(self)

    async def execute(self, sql, *args):
        self.pool.calls.append(("execute", sql, args))
        return "OK"

    async def fetchrow(self, sql, *args):
        self.pool.calls.append(("conn_fetchrow", sql, args))
        return self.pool.conn_fetchrow(sql, *args)


class RouterFakePool:
    def __init__(self, *, bot=None, documents=None, faq_counts=None, sop_counts=None,
                 quality_rows=None, faqs=None, sops=None, faq=None, sop=None):
        self.bot = bot
        self.documents = documents or []
        self.faq_counts = faq_counts or {"suggested": 0, "approved": 0, "rejected": 0}
        self.sop_counts = sop_counts or {"suggested": 0, "approved": 0, "rejected": 0}
        self.quality_rows = quality_rows or []
        self.faqs = faqs or []
        self.sops = sops or []
        self.faq = faq
        self.sop = sop
        self.calls = []
        self.connection = RouterFakeConnection(self)

    def acquire(self):
        return AsyncContext(self.connection)

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        q = " ".join(sql.split())
        if "FROM documents WHERE bot_id=" in q:
            return self.documents
        if "FROM kb_quality_reports" in q:
            return self.quality_rows
        if "FROM kb_generated_faqs WHERE" in q:
            return self.faqs
        if "FROM kb_generated_sops WHERE" in q:
            return self.sops
        return []

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        q = " ".join(sql.split())
        if "FROM bots WHERE id=" in q:
            return self.bot
        if "FROM kb_generated_faqs WHERE bot_id=" in q:
            return self.faq_counts
        if "FROM kb_generated_sops WHERE bot_id=" in q:
            return self.sop_counts
        if "FROM kb_generated_faqs WHERE id=" in q:
            return self.faq
        if "FROM kb_generated_sops WHERE id=" in q:
            return self.sop
        if "FROM documents WHERE id=" in q:
            return self.documents[0] if self.documents else None
        return None

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return "OK"

    def conn_fetchrow(self, sql, *args):
        q = " ".join(sql.split())
        if "UPDATE kb_generated_faqs" in q and "RETURNING" in q:
            updated = {**self.faq, "question": args[0], "answer": args[1], "category": args[2], "status": args[3]}
            self.faq = updated
            return updated
        if "UPDATE kb_generated_sops" in q and "RETURNING" in q:
            updated = {**self.sop, "title": args[0], "steps": args[1], "category": args[2], "status": args[3]}
            self.sop = updated
            return updated
        return None


def _build_router(pool, *, run_pipeline=None, store_chunk_embeddings=None):
    async def get_pool():
        return pool

    async def get_current_user():
        return {"org_id": "org-1"}

    async def default_run_pipeline(doc_id):
        return None

    async def default_store_chunk_embeddings(conn, org_id, chunk_rows):
        return None

    return build_knowledge_builder_router(
        get_pool=get_pool,
        get_current_user=get_current_user,
        run_pipeline=run_pipeline or default_run_pipeline,
        store_chunk_embeddings=store_chunk_embeddings or default_store_chunk_embeddings,
    )


def test_overview_aggregates_quality_and_missing_topics():
    documents = [{
        "id": "doc-1", "filename": "Panduan.pdf", "status": "ready", "kb_status": "ready",
        "kb_error": None, "chunk_count": 3, "source_type": "upload", "source_url": None,
        "summary": "Ringkasan", "categories": json.dumps(["Pengiriman"]),
        "tags": json.dumps(["resi"]), "suggested_intents": json.dumps(["cek_resi"]),
        "created_at": "now", "processed_at": "now",
    }]
    quality_rows = [{
        "document_id": "doc-1", "completeness_score": 80, "redundancy_score": 90,
        "coverage_score": 70, "overall_score": 80,
        "missing_topics": json.dumps(["Kebijakan Garansi", "Cara Pembayaran"]),
        "duplicate_groups": json.dumps([]), "created_at": "now",
    }]
    pool = RouterFakePool(
        bot={"id": "bot-1", "name": "Agent"}, documents=documents,
        faq_counts={"suggested": 2, "approved": 1, "rejected": 0},
        sop_counts={"suggested": 1, "approved": 0, "rejected": 0},
        quality_rows=quality_rows,
    )
    router = _build_router(pool)
    handler = _route(router, "/bots/{bot_id}/overview", "GET")

    result = asyncio.run(handler(bot_id="bot-1", user={"org_id": "org-1"}, pool=pool))

    assert result["documents"][0]["categories"] == ["Pengiriman"]
    assert result["quality"]["overall_score"] == 80
    assert result["quality"]["documents_scored"] == 1
    assert {"topic": "Kebijakan Garansi", "document_count": 1} in result["missing_topics"]
    assert result["faqs"]["suggested"] == 2
    assert result["sops"]["approved"] == 0


def test_list_faqs_rejects_invalid_status():
    pool = RouterFakePool(bot={"id": "bot-1", "name": "Agent"})
    router = _build_router(pool)
    handler = _route(router, "/bots/{bot_id}/faqs", "GET")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(bot_id="bot-1", user={"org_id": "org-1"}, pool=pool, status="bogus"))
    assert exc.value.status_code == 422


def test_update_faq_approve_publishes_to_kb():
    faq = {
        "id": "faq-1", "org_id": "org-1", "bot_id": "bot-1", "document_id": "doc-1",
        "question": "Q?", "answer": "A.", "category": "General", "status": "suggested",
        "source": "ai", "chunk_id": None, "created_at": "now", "updated_at": "now",
    }
    pool = RouterFakePool(faq=faq)
    published = []

    async def fake_store(conn, org_id, chunk_rows):
        published.append((org_id, chunk_rows))

    router = _build_router(pool, store_chunk_embeddings=fake_store)
    handler = _route(router, "/faqs/{faq_id}", "PATCH")

    result = asyncio.run(handler(
        faq_id="faq-1", body=FaqUpdateRequest(status="approved"),
        user={"org_id": "org-1", "id": "user-1"}, pool=pool,
    ))

    assert result["faq"]["status"] == "approved"
    assert result["faq"]["chunk_id"]
    assert published and published[0][1][0][1] == "Q: Q?\nA: A."
    assert any("INSERT INTO doc_chunks" in c[1] for c in pool.calls if c[0] == "execute")
    assert any(
        "UPDATE kb_generated_faqs SET chunk_id=" in c[1]
        for c in pool.calls if c[0] == "execute"
    )


def test_update_faq_reject_unpublishes_from_kb():
    faq = {
        "id": "faq-1", "org_id": "org-1", "bot_id": "bot-1", "document_id": "doc-1",
        "question": "Q?", "answer": "A.", "category": "General", "status": "approved",
        "source": "ai", "chunk_id": "chunk-9", "created_at": "now", "updated_at": "now",
    }
    pool = RouterFakePool(faq=faq)
    router = _build_router(pool)
    handler = _route(router, "/faqs/{faq_id}", "PATCH")

    result = asyncio.run(handler(
        faq_id="faq-1", body=FaqUpdateRequest(status="rejected"),
        user={"org_id": "org-1", "id": "user-1"}, pool=pool,
    ))

    assert result["faq"]["status"] == "rejected"
    assert result["faq"]["chunk_id"] is None
    deletes = [c for c in pool.calls if c[0] == "execute" and "DELETE FROM doc_chunks" in c[1]]
    assert deletes and deletes[0][2] == ("chunk-9",)


def test_update_faq_not_found_raises_404():
    pool = RouterFakePool(faq=None)
    router = _build_router(pool)
    handler = _route(router, "/faqs/{faq_id}", "PATCH")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(
            faq_id="missing", body=FaqUpdateRequest(status="approved"),
            user={"org_id": "org-1"}, pool=pool,
        ))
    assert exc.value.status_code == 404


def test_update_sop_approve_publishes_numbered_steps():
    sop = {
        "id": "sop-1", "org_id": "org-1", "bot_id": "bot-1", "document_id": "doc-1",
        "title": "Cara Refund", "steps": json.dumps(["Hubungi CS", "Isi formulir"]),
        "category": "Refund", "status": "suggested", "chunk_id": None,
        "created_at": "now", "updated_at": "now",
    }
    pool = RouterFakePool(sop=sop)
    published = []

    async def fake_store(conn, org_id, chunk_rows):
        published.append((org_id, chunk_rows))

    router = _build_router(pool, store_chunk_embeddings=fake_store)
    handler = _route(router, "/sops/{sop_id}", "PATCH")

    result = asyncio.run(handler(
        sop_id="sop-1", body=SopUpdateRequest(status="approved"),
        user={"org_id": "org-1", "id": "user-1"}, pool=pool,
    ))

    assert result["sop"]["status"] == "approved"
    assert result["sop"]["chunk_id"]
    content = published[0][1][0][1]
    assert content.startswith("SOP: Cara Refund\n1. Hubungi CS\n2. Isi formulir")


def test_update_sop_rejects_empty_steps():
    sop = {
        "id": "sop-1", "org_id": "org-1", "bot_id": "bot-1", "document_id": "doc-1",
        "title": "Cara Refund", "steps": json.dumps(["Hubungi CS"]),
        "category": "Refund", "status": "suggested", "chunk_id": None,
        "created_at": "now", "updated_at": "now",
    }
    pool = RouterFakePool(sop=sop)
    router = _build_router(pool)
    handler = _route(router, "/sops/{sop_id}", "PATCH")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(
            sop_id="sop-1", body=SopUpdateRequest(status="approved", steps=["   ", ""]),
            user={"org_id": "org-1"}, pool=pool,
        ))
    assert exc.value.status_code == 422


def test_regenerate_requires_ready_document():
    documents = [{"id": "doc-1", "status": "processing"}]
    pool = RouterFakePool(bot={"id": "bot-1", "name": "Agent"}, documents=documents)
    router = _build_router(pool)
    handler = _route(router, "/bots/{bot_id}/documents/{doc_id}/generate", "POST")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(bot_id="bot-1", doc_id="doc-1", user={"org_id": "org-1"}, pool=pool))
    assert exc.value.status_code == 409


def test_regenerate_schedules_pipeline_for_ready_document():
    documents = [{"id": "doc-1", "status": "ready"}]
    pool = RouterFakePool(bot={"id": "bot-1", "name": "Agent"}, documents=documents)

    async def fake_run_pipeline(doc_id):
        return None

    router = _build_router(pool, run_pipeline=fake_run_pipeline)
    handler = _route(router, "/bots/{bot_id}/documents/{doc_id}/generate", "POST")

    result = asyncio.run(handler(bot_id="bot-1", doc_id="doc-1", user={"org_id": "org-1"}, pool=pool))

    assert result["doc_id"] == "doc-1"
    assert any("kb_status='pending'" in c[1] for c in pool.calls if c[0] == "execute")


# ─── Schema / routes / UI presence ──────────────────────────────

def test_knowledge_builder_routes_schema_and_ui_are_present():
    import main

    paths = {getattr(route, "path", "") for route in main.app.routes}
    assert "/api/knowledge-builder/bots/{bot_id}/overview" in paths
    assert "/api/knowledge-builder/bots/{bot_id}/documents/{doc_id}/generate" in paths
    assert "/api/knowledge-builder/bots/{bot_id}/faqs" in paths
    assert "/api/knowledge-builder/faqs/{faq_id}" in paths
    assert "/api/knowledge-builder/bots/{bot_id}/sops" in paths
    assert "/api/knowledge-builder/sops/{sop_id}" in paths
    assert "/api/knowledge-builder/bots/{bot_id}/quality" in paths
    assert "/bots/{bot_id}/documents/faq-import" in paths

    schema = (Path(__file__).resolve().parent / "schema.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS kb_generated_faqs" in schema
    assert "CREATE TABLE IF NOT EXISTS kb_generated_sops" in schema
    assert "CREATE TABLE IF NOT EXISTS kb_quality_reports" in schema
    assert "kb_status" in schema and "kb_error" in schema

    platform_schema = (Path(__file__).resolve().parent / "bn_platform/schema_platform.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS kb_generated_faqs" in platform_schema

    frontend = (Path(__file__).resolve().parent / "frontend/app.js").read_text()
    assert "renderKnowledgeBuilder" in frontend
    assert "kb-builder" in frontend

    api_client = (Path(__file__).resolve().parent / "frontend/api-client.js").read_text()
    assert "kbOverview" in api_client
    assert "importFaqCsv" in api_client

    components = (Path(__file__).resolve().parent / "frontend/components.js").read_text()
    assert "kb-builder" in components
