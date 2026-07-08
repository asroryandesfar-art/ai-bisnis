"""
test_knowledge_access_engine.py — Tes untuk Universal Knowledge Access Layer:
Tool Registry, Website Reader (SSRF-safe), Tool Selection, dan Source
Verification / Knowledge Conflict Detection.
"""
import asyncio

import tool_registry as tr
import knowledge_access_engine as kae
from base import BaseAgent
from reasoning_controller import ReasoningController


# ─────────────────────────────────────────────────────────────────
# 1) Tool Registry — katalog
# ─────────────────────────────────────────────────────────────────

def test_available_tools_match_registry_flags():
    available = tr.available_tools()
    for name in available:
        assert tr.TOOL_REGISTRY[name]["available"] is True
    for name, meta in tr.TOOL_REGISTRY.items():
        if not meta.get("available"):
            assert name not in available
            assert meta.get("unavailable_reason"), name


def test_describe_tool_returns_copy():
    desc = tr.describe_tool("website_reader")
    assert desc["category"] == "web_search"
    desc["category"] = "mutated"
    assert tr.TOOL_REGISTRY["website_reader"]["category"] == "web_search"


def test_describe_unknown_tool_returns_empty_dict():
    assert tr.describe_tool("does_not_exist") == {}


def test_knowledge_priority_order():
    assert tr.KNOWLEDGE_PRIORITY[0] == "user_context"
    assert tr.KNOWLEDGE_PRIORITY[-1] == "web_search"
    assert "tenant_knowledge" in tr.KNOWLEDGE_PRIORITY


# ─────────────────────────────────────────────────────────────────
# 2) Website Reader — SSRF validation
# ─────────────────────────────────────────────────────────────────

def test_validate_url_rejects_unsupported_scheme():
    ok, reason = tr._validate_url("ftp://example.com/file")
    assert ok is False
    assert "Skema" in reason


def test_validate_url_rejects_loopback():
    ok, reason = tr._validate_url("http://127.0.0.1/admin")
    assert ok is False
    assert "privat" in reason or "internal" in reason


def test_validate_url_rejects_private_network():
    ok, _reason = tr._validate_url("http://10.0.0.5/")
    assert ok is False


def test_validate_url_rejects_cloud_metadata_endpoint():
    ok, _reason = tr._validate_url("http://169.254.169.254/latest/meta-data/")
    assert ok is False


def test_validate_url_accepts_public_ip_literal():
    ok, reason = tr._validate_url("http://93.184.216.34/page")
    assert ok is True, reason


# ─────────────────────────────────────────────────────────────────
# 3) _TextExtractor — ekstraksi judul + teks dari HTML
# ─────────────────────────────────────────────────────────────────

def test_text_extractor_strips_script_and_style():
    html_doc = (
        "<html><head><title>Judul Halaman</title>"
        "<style>body{color:red}</style></head>"
        "<body><script>alert(1)</script>"
        "<h1>Selamat datang</h1><p>Ini paragraf konten.</p></body></html>"
    )
    extractor = tr._TextExtractor()
    extractor.feed(html_doc)
    assert extractor.get_title() == "Judul Halaman"
    text = extractor.get_text()
    assert "Selamat datang" in text
    assert "Ini paragraf konten." in text
    assert "alert" not in text
    assert "color:red" not in text


# ─────────────────────────────────────────────────────────────────
# 4) read_website — blocked URL & mocked success
# ─────────────────────────────────────────────────────────────────

def test_read_website_blocks_private_url():
    result = asyncio.run(tr.read_website("http://127.0.0.1/secret"))
    assert result["success"] is False
    assert "error" in result


class _FakeStreamResponse:
    def __init__(self, status_code=200, headers=None, body=b"", is_redirect=False, encoding="utf-8"):
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body
        self.is_redirect = is_redirect
        self.encoding = encoding

    async def aiter_bytes(self):
        yield self._body

    async def aclose(self):
        return None


class _FakeRequest:
    def __init__(self, method, url, headers):
        self.method = method
        self.url = url
        self.headers = headers or {}
        self.extensions = {}


class _FakeAsyncClient:
    responses: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def build_request(self, method, url, headers=None):
        return _FakeRequest(method, url, headers)

    async def send(self, req, stream=False):
        return _FakeAsyncClient.responses.pop(0)


def test_read_website_success(monkeypatch):
    body = b"<html><head><title>Contoh</title></head><body><p>Halo dunia</p></body></html>"
    _FakeAsyncClient.responses = [_FakeStreamResponse(status_code=200, headers={"content-type": "text/html"}, body=body)]
    monkeypatch.setattr(tr, "httpx", type("M", (), {"AsyncClient": _FakeAsyncClient, "HTTPError": tr.httpx.HTTPError}))

    result = asyncio.run(tr.read_website("http://93.184.216.34/page"))
    assert result["success"] is True
    assert result["title"] == "Contoh"
    assert "Halo dunia" in result["text"]


def test_read_website_rejects_unsupported_content_type(monkeypatch):
    body = b'{"a": 1}'
    _FakeAsyncClient.responses = [_FakeStreamResponse(status_code=200, headers={"content-type": "application/json"}, body=body)]
    monkeypatch.setattr(tr, "httpx", type("M", (), {"AsyncClient": _FakeAsyncClient, "HTTPError": tr.httpx.HTTPError}))

    result = asyncio.run(tr.read_website("http://93.184.216.34/page"))
    assert result["success"] is False
    assert "Tipe konten" in result["error"]


def test_read_website_rejects_redirect_to_private_target(monkeypatch):
    redirect = _FakeStreamResponse(status_code=302, headers={"location": "http://127.0.0.1/internal"}, is_redirect=True)
    _FakeAsyncClient.responses = [redirect]
    monkeypatch.setattr(tr, "httpx", type("M", (), {"AsyncClient": _FakeAsyncClient, "HTTPError": tr.httpx.HTTPError}))

    result = asyncio.run(tr.read_website("http://93.184.216.34/page"))
    assert result["success"] is False


# ─────────────────────────────────────────────────────────────────
# 5) select_knowledge_sources — Tool Selection
# ─────────────────────────────────────────────────────────────────

def test_select_knowledge_sources_general_question():
    routing = kae.select_knowledge_sources("Bagaimana cara menghubungkan WhatsApp?", [])
    assert "tenant_knowledge" in routing["reasons"]
    assert "memory" not in routing["reasons"]
    assert routing["detected_url"] is None
    assert "web_search:news" not in routing["reasons"]
    assert "web_search:financial" not in routing["reasons"]


def test_select_knowledge_sources_with_history_adds_memory():
    routing = kae.select_knowledge_sources("Terus gimana?", [{"role": "user", "content": "Halo"}])
    assert "memory" in routing["reasons"]


def test_select_knowledge_sources_billing_question():
    routing = kae.select_knowledge_sources("Berapa sisa kuota paket saya?", [])
    assert "self_knowledge" in routing["reasons"]


def test_select_knowledge_sources_news_question():
    routing = kae.select_knowledge_sources("Ada berita terbaru apa hari ini?", [])
    assert "web_search:news" in routing["reasons"]


def test_select_knowledge_sources_finance_question():
    routing = kae.select_knowledge_sources("Berapa harga bitcoin sekarang?", [])
    assert "web_search:financial" in routing["reasons"]


def test_select_knowledge_sources_detects_url():
    routing = kae.select_knowledge_sources("Tolong baca https://example.com/produk dan ringkas.", [])
    assert routing["detected_url"] == "https://example.com/produk"
    assert "web_search:website_reader" in routing["reasons"]


# ─────────────────────────────────────────────────────────────────
# 6) format_website_reading
# ─────────────────────────────────────────────────────────────────

def test_format_website_reading_success():
    result = {"success": True, "url": "https://example.com", "title": "Contoh", "text": "Isi halaman."}
    formatted = kae.format_website_reading(result)
    assert "https://example.com" in formatted
    assert "Contoh" in formatted
    assert "Isi halaman." in formatted


def test_format_website_reading_failure():
    result = {"success": False, "url": "https://example.com", "error": "Gagal mengambil halaman: timeout"}
    formatted = kae.format_website_reading(result)
    assert "Gagal membaca halaman" in formatted
    assert "timeout" in formatted


def test_format_website_reading_empty_text():
    result = {"success": True, "url": "https://example.com", "title": "", "text": ""}
    formatted = kae.format_website_reading(result)
    assert "tidak ada teks yang bisa diekstrak" in formatted


def test_format_website_reading_empty_result():
    assert kae.format_website_reading({}) == ""


# ─────────────────────────────────────────────────────────────────
# 7) ReasoningController — Source Verification & knowledge_routing
# ─────────────────────────────────────────────────────────────────

def test_reasoning_controller_always_includes_source_verification():
    rc = ReasoningController()
    brief = rc.analyze({"user_message": "Bagaimana cara menghubungkan WhatsApp?", "messages": []})
    assert kae.SOURCE_VERIFICATION_BLOCK.splitlines()[0] in brief["style_guidance"]


def test_reasoning_controller_returns_knowledge_routing():
    rc = ReasoningController()
    brief = rc.analyze({"user_message": "Berapa harga bitcoin sekarang?", "messages": []})
    assert "knowledge_routing" in brief
    assert "web_search:financial" in brief["knowledge_routing"]["reasons"]


# ─────────────────────────────────────────────────────────────────
# 8) Supervisor integration — Website Reader path
# ─────────────────────────────────────────────────────────────────

async def _fake_call_llm_json_default(self, messages, temperature=0.2, max_tokens=512, default=None):
    return default or {}


def _build_supervisor():
    from supervisor import SupervisorAgent
    return SupervisorAgent(api_key="test-key")


def test_supervisor_reads_website_when_url_present(monkeypatch):
    captured: dict = {}

    async def fake_call_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        captured["system"] = messages[0]["content"]
        return "Ringkasan halaman."

    async def fake_read_website(url):
        return {
            "success": True,
            "url": url,
            "final_url": url,
            "title": "Halaman Contoh",
            "text": "Konten penting dari halaman contoh.",
        }

    monkeypatch.setattr(BaseAgent, "_call_llm", fake_call_llm)
    monkeypatch.setattr(BaseAgent, "_call_llm_json", _fake_call_llm_json_default)

    import supervisor as sup
    monkeypatch.setattr(sup.tool_registry, "read_website", fake_read_website)

    supervisor = _build_supervisor()
    context = {
        "bot_id": "bot-1",
        "org_id": "org-1",
        "conversation_id": "conv-1",
        "user_message": "Tolong baca https://example.com/produk dan ringkas.",
        "messages": [],
        "knowledge_base_context": "",
        "reasoning_mode": "standard",
    }
    result = asyncio.run(supervisor.process(context))

    assert result.reasoning_brief["knowledge_routing"]["detected_url"] == "https://example.com/produk"
    assert "Konten penting dari halaman contoh." in captured["system"]
    assert "Halaman Contoh" in captured["system"]
