"""test_tool_executor.py — tool_executor.py: skema valid + eksekutor nyata
dengan pool/dependency palsu (no network/DB sungguhan di test)."""
import asyncio

import tool_executor as te


def test_all_seven_required_tools_have_schema_and_executor():
    required = {"knowledge_search", "memory_lookup", "file_reader", "database_query",
                "web_search", "browser_open", "browser_extract"}
    assert required <= set(te.TOOL_SCHEMAS)
    assert required <= set(te._EXECUTORS)
    for name in required:
        schema = te.TOOL_SCHEMAS[name]
        assert schema["type"] == "function"
        assert schema["function"]["name"] == name
        assert "parameters" in schema["function"]


def test_available_tool_schemas_filters_by_name():
    schemas = te.available_tool_schemas(["knowledge_search", "not_a_real_tool"])
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "knowledge_search"


def test_execute_tool_unknown_name_returns_honest_error():
    result = asyncio.run(te.execute_tool("does_not_exist", {}, ctx={}))
    assert result["success"] is False
    assert "tidak dikenal" in result["error"]


def test_execute_tool_catches_exception_as_honest_error():
    async def _boom(args, ctx):
        raise RuntimeError("simulated failure")
    te._EXECUTORS["_test_boom"] = _boom
    try:
        result = asyncio.run(te.execute_tool("_test_boom", {}, ctx={}))
        assert result == {"success": False, "error": "simulated failure"}
    finally:
        del te._EXECUTORS["_test_boom"]


def test_database_query_rejects_table_outside_allowlist():
    class FakePool:
        async def fetch(self, *a, **k):
            raise AssertionError("tidak boleh sampai query -- harus ditolak sebelum itu")
    result = asyncio.run(te.execute_tool(
        "database_query", {"table": "users"}, ctx={"pool": FakePool(), "org_id": "org-1"}
    ))
    assert result["success"] is False
    assert "tidak diizinkan" in result["error"]


def test_database_query_always_scopes_by_org_id_from_ctx_not_args():
    captured = {}

    class FakePool:
        async def fetch(self, sql, *args):
            captured["sql"] = sql
            captured["args"] = args
            return [{"id": "row-1", "status": "paid"}]

    result = asyncio.run(te.execute_tool(
        "database_query",
        {"table": "finance_invoices", "filter_value": "paid", "org_id": "attacker-org"},
        ctx={"pool": FakePool(), "org_id": "real-org-from-ctx"},
    ))
    assert result["success"] is True
    assert captured["args"][0] == "real-org-from-ctx"
    assert "WHERE org_id=$1" in captured["sql"]


def test_file_reader_returns_honest_error_when_document_not_found():
    class FakePool:
        async def fetchrow(self, *a, **k):
            return None
    result = asyncio.run(te.execute_tool(
        "file_reader", {"document_id": "missing"}, ctx={"pool": FakePool(), "org_id": "org-1"}
    ))
    assert result["success"] is False
    assert "tidak ditemukan" in result["error"]


def test_parse_tool_call_args_never_raises_on_bad_json():
    assert te.parse_tool_call_args("not json") == {}
    assert te.parse_tool_call_args('{"a": 1}') == {"a": 1}
    assert te.parse_tool_call_args("") == {}


# ─── Phase 5: financial_data / news_search / document_generator ──

def test_financial_data_combines_crypto_and_stock_quotes(monkeypatch):
    import finance_fetcher as ff

    async def fake_crypto(query, timeout_s=15.0):
        return [ff.CryptoQuote(coin_id="bitcoin", symbol="BTC", usd=65000.0, idr=1_000_000_000.0,
                                usd_24h_change=1.2, idr_24h_change=1.2, fetched_at="2026-06-25T00:00:00Z")]

    async def fake_stock(query, timeout_s=15.0):
        return []

    monkeypatch.setattr(ff, "fetch_crypto_quotes", fake_crypto)
    monkeypatch.setattr(ff, "fetch_stock_quotes", fake_stock)

    result = asyncio.run(te.execute_tool("financial_data", {"query": "harga bitcoin"}, ctx={}))
    assert result["success"] is True
    assert "BTC" in result["summary"]
    assert len(result["crypto"]) == 1
    assert result["stocks"] == []


def test_financial_data_returns_honest_error_when_nothing_recognized(monkeypatch):
    import finance_fetcher as ff

    async def empty(query, timeout_s=15.0):
        return []

    monkeypatch.setattr(ff, "fetch_crypto_quotes", empty)
    monkeypatch.setattr(ff, "fetch_stock_quotes", empty)

    result = asyncio.run(te.execute_tool("financial_data", {"query": "halo apa kabar"}, ctx={}))
    assert result["success"] is False
    assert "error" in result


def test_news_search_returns_result_list(monkeypatch):
    import news_fetcher

    async def fake_search(query, limit=6, rss_urls=None):
        return [news_fetcher.NewsItem(title="Judul Berita", link="https://example.com/a",
                                       source="Test Source", published="2026-06-25", summary="Ringkasan")]

    monkeypatch.setattr(news_fetcher, "search_news", fake_search)

    result = asyncio.run(te.execute_tool("news_search", {"query": "ekonomi indonesia"}, ctx={}))
    assert result["success"] is True
    assert result["results"][0]["title"] == "Judul Berita"


def test_document_generator_executor_saves_file_and_inserts_row(monkeypatch):
    import document_generator as dg
    import storage_backend

    monkeypatch.setattr(dg, "generate_document", lambda fmt, spec: (b"PDFDATA", "application/pdf"))
    monkeypatch.setattr(storage_backend, "save_bytes", lambda subdir, data, ext="", filename=None: (None, "/media/agent-task-documents/x.pdf"))

    class FakePool:
        def __init__(self):
            self.calls = []

        async def execute(self, sql, *args):
            self.calls.append((sql, args))
            return "OK"

    pool = FakePool()
    result = asyncio.run(te.execute_tool(
        "document_generator",
        {"format": "pdf", "title": "Laporan Uji", "sections": [{"heading": "A", "body": "B"}]},
        ctx={"pool": pool, "org_id": "org-1", "bot_id": None},
    ))
    assert result["success"] is True
    assert result["file_url"] == "/media/agent-task-documents/x.pdf"
    assert result["title"] == "Laporan Uji"
    assert any("INSERT INTO generated_documents" in c[0] for c in pool.calls)


def test_document_generator_executor_works_without_pool(monkeypatch):
    import document_generator as dg
    import storage_backend

    monkeypatch.setattr(dg, "generate_document", lambda fmt, spec: (b"PDFDATA", "application/pdf"))
    monkeypatch.setattr(storage_backend, "save_bytes", lambda subdir, data, ext="", filename=None: (None, "/media/x.pdf"))

    result = asyncio.run(te.execute_tool(
        "document_generator", {"format": "pdf", "title": "Tanpa Pool"}, ctx={"org_id": "org-1"},
    ))
    assert result["success"] is True


# ─── Phase 6: email_reader ────────────────────────────────────────

def test_email_reader_returns_honest_error_when_gmail_not_connected(monkeypatch):
    import main as m

    async def fake_integ(pool, org_id):
        return {"gmail": {}}

    monkeypatch.setattr(m, "_get_integrations_auto", fake_integ)

    result = asyncio.run(te.execute_tool(
        "email_reader", {}, ctx={"pool": object(), "org_id": "org-1"},
    ))
    assert result["success"] is False
    assert "belum terhubung" in result["error"]


def test_email_reader_returns_unread_emails_when_connected(monkeypatch):
    import main as m

    async def fake_integ(pool, org_id):
        return {"gmail": {"access_token": "tok", "refresh_token": ""}}

    async def fake_get_token(access_token, refresh_token):
        return access_token

    async def fake_list_unread(token, max_results=5):
        return ["msg-1"]

    async def fake_get_message(token, message_id):
        return {"payload": {"headers": [
            {"name": "Subject", "value": "Pertanyaan produk"},
            {"name": "From", "value": "calon@pelanggan.com"},
        ]}, "snippet": "Halo, saya mau tanya..."}

    monkeypatch.setattr(m, "_get_integrations_auto", fake_integ)
    monkeypatch.setattr(m, "_gmail_get_access_token", fake_get_token)
    monkeypatch.setattr(m, "_gmail_list_unread", fake_list_unread)
    monkeypatch.setattr(m, "_gmail_get_message", fake_get_message)

    result = asyncio.run(te.execute_tool(
        "email_reader", {"max_results": 3}, ctx={"pool": object(), "org_id": "org-1"},
    ))
    assert result["success"] is True
    assert result["unread_count"] == 1
    assert result["emails"][0]["subject"] == "Pertanyaan produk"
    assert result["emails"][0]["from"] == "calon@pelanggan.com"
