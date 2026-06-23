"""
test_realtime_knowledge.py — Real-Time Knowledge Layer:
freshness detection (knowledge_access_engine), WebSearchAgent
(web_search_agent), dan wiring ke ReasoningController & SupervisorAgent.
"""
import asyncio

import knowledge_access_engine as kae
import web_search_agent as wsa
import news_fetcher
import main
from base import BaseAgent
from reasoning_controller import ReasoningController


# ─────────────────────────────────────────────────────────────────
# 1) is_freshness_query
# ─────────────────────────────────────────────────────────────────

def test_is_freshness_query_detects_keywords():
    assert kae.is_freshness_query("Apa kabar terbaru tentang AI sekarang?")
    assert kae.is_freshness_query("Apa rencana bulan ini?")
    assert kae.is_freshness_query("Ada breaking news apa?")


def test_is_freshness_query_false_for_generic_question():
    assert not kae.is_freshness_query("Bagaimana cara menghubungkan WhatsApp?")


# ── Regression: pertanyaan "siapa pemegang jabatan X" inheren bisa berubah
# (pemilu/reshuffle/pergantian CEO) walau tidak mengandung kata
# "terbaru"/"sekarang" secara harfiah. Bug nyata: "Siapa presiden Indonesia?"
# dijawab pakai data training tanpa disclaimer freshness sama sekali. ──────

def test_is_freshness_query_detects_officeholder_questions():
    assert kae.is_freshness_query("Siapa presiden Indonesia?")
    assert kae.is_freshness_query("Siapa gubernur DKI Jakarta?")
    assert kae.is_freshness_query("Siapa CEO Tesla sekarang?")
    assert kae.is_freshness_query("Siapa menteri keuangan saat ini?")


def test_is_freshness_query_does_not_flag_unrelated_science_question():
    # "hukum" Newton sama sekali tidak menyentuh pola officeholder.
    assert not kae.is_freshness_query("Jelaskan hukum Newton")


def test_select_knowledge_sources_flags_officeholder_question_as_needs_fresh_data():
    routing = kae.select_knowledge_sources("Siapa presiden Indonesia?", [])
    assert routing["needs_fresh_data"] is True
    assert "web_search:general" in routing["reasons"]


def test_reasoning_controller_adds_realtime_block_for_officeholder_question():
    from reasoning_controller import ReasoningController
    rc = ReasoningController()
    brief = rc.analyze({"user_message": "Siapa presiden Indonesia?", "messages": []})
    assert kae.REALTIME_KNOWLEDGE_BLOCK.splitlines()[0] in brief["style_guidance"]


# ─────────────────────────────────────────────────────────────────
# 2) select_knowledge_sources — needs_fresh_data & web_search:general
# ─────────────────────────────────────────────────────────────────

def test_select_knowledge_sources_general_freshness_question():
    routing = kae.select_knowledge_sources("Apa perkembangan teknologi AI terbaru sekarang?", [])
    assert "web_search:general" in routing["reasons"]
    assert routing["needs_fresh_data"] is True


def test_select_knowledge_sources_freshness_already_covered_by_news():
    # "hari ini" termasuk _NEWS_HINTS -> sudah tercakup web_search:news,
    # jangan tambah web_search:general lagi.
    routing = kae.select_knowledge_sources("Ada berita terbaru apa hari ini?", [])
    assert "web_search:news" in routing["reasons"]
    assert "web_search:general" not in routing["reasons"]
    assert routing["needs_fresh_data"] is True


def test_select_knowledge_sources_freshness_already_covered_by_finance():
    routing = kae.select_knowledge_sources("Berapa harga bitcoin sekarang?", [])
    assert "web_search:financial" in routing["reasons"]
    assert "web_search:general" not in routing["reasons"]
    assert routing["needs_fresh_data"] is True


def test_select_knowledge_sources_no_fresh_data_for_generic_question():
    routing = kae.select_knowledge_sources("Bagaimana cara menghubungkan WhatsApp?", [])
    assert routing["needs_fresh_data"] is False
    assert "web_search:general" not in routing["reasons"]


def test_main_news_detection_matches_natural_freshness_phrases():
    queries = [
        "Apa kabar terbaru tentang ekonomi Indonesia?",
        "Apa yang terjadi di Timur Tengah sekarang?",
        "Topik AI yang viral minggu ini",
        "Ada breaking update soal kebijakan baru?",
    ]
    for query in queries:
        assert main._looks_like_news_query(query), query


def test_main_news_detection_ignores_generic_question():
    assert not main._looks_like_news_query("Bagaimana cara menghubungkan WhatsApp?")


def test_news_search_phrase_keeps_topic_and_removes_freshness_words():
    assert news_fetcher._search_phrase(
        "Apa kabar terbaru tentang ekonomi Indonesia sekarang?"
    ) == "ekonomi indonesia"
    assert news_fetcher._search_phrase(
        "Apa yang terjadi di Timur Tengah saat ini?"
    ) == "timur tengah"


# ─────────────────────────────────────────────────────────────────
# 3) ReasoningController — REALTIME_KNOWLEDGE_BLOCK
# ─────────────────────────────────────────────────────────────────

def test_reasoning_controller_adds_realtime_block_for_freshness_question():
    rc = ReasoningController()
    brief = rc.analyze({"user_message": "Apa perkembangan teknologi AI terbaru sekarang?", "messages": []})
    assert kae.REALTIME_KNOWLEDGE_BLOCK.splitlines()[0] in brief["style_guidance"]
    assert brief["knowledge_routing"]["needs_fresh_data"] is True


def test_reasoning_controller_omits_realtime_block_for_generic_question():
    rc = ReasoningController()
    brief = rc.analyze({"user_message": "Bagaimana cara menghubungkan WhatsApp?", "messages": []})
    assert kae.REALTIME_KNOWLEDGE_BLOCK.splitlines()[0] not in brief["style_guidance"]


# ─────────────────────────────────────────────────────────────────
# 4) web_search_agent.search — SearXNG utama, Tavily cadangan
# ─────────────────────────────────────────────────────────────────

def test_search_skipped_without_any_provider():
    result = asyncio.run(wsa.search("AI terbaru"))
    assert result["success"] is False
    assert result["skipped"] is True


class _FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text

    def json(self):
        return self._json_data


class _FakeAsyncClient:
    def __init__(self, get_response=None, post_response=None, captured=None):
        self._get_response = get_response
        self._post_response = post_response
        self._captured = captured if captured is not None else []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None):
        self._captured.append(("get", url, params))
        if self._get_response is None:
            raise RuntimeError("unexpected GET in test")
        return self._get_response

    async def post(self, url, json=None, headers=None):
        self._captured.append(("post", url, json))
        if self._post_response is None:
            raise RuntimeError("unexpected POST in test")
        return self._post_response


def _patch_client(monkeypatch, get_response=None, post_response=None):
    captured = []
    monkeypatch.setattr(wsa, "httpx", type("M", (), {
        "AsyncClient": lambda timeout=None: _FakeAsyncClient(get_response, post_response, captured),
        "HTTPError": wsa.httpx.HTTPError,
    }))
    return captured


def test_search_searxng_success_is_primary_and_skips_tavily(monkeypatch):
    response = _FakeResponse(200, {
        "results": [
            {"title": "Artikel A", "url": "https://a.com/x", "content": "Isi A", "score": 0.5, "publishedDate": "2026-06-10"},
            {"title": "Artikel B", "url": "https://b.com/y", "content": "Isi B", "score": 0.9, "publishedDate": "2026-06-12"},
        ]
    })
    captured = _patch_client(monkeypatch, get_response=response)

    result = asyncio.run(wsa.search("AI terbaru", searxng_url="http://localhost:8080", tavily_api_key="test-key"))
    assert result["success"] is True
    assert result["provider"] == "searxng"
    assert len(result["results"]) == 2
    assert captured[0][0] == "get"
    assert captured[0][2]["q"] == "AI terbaru"
    assert len(captured) == 1  # Tavily tidak pernah dipanggil karena SearXNG sukses


def test_search_falls_back_to_tavily_when_searxng_fails(monkeypatch):
    get_response = _FakeResponse(500, {}, text="searxng down")
    post_response = _FakeResponse(200, {
        "results": [
            {"title": "Artikel A", "url": "https://a.com/x", "content": "Isi A", "score": 0.5, "published_date": "2026-06-10"},
        ]
    })
    captured = _patch_client(monkeypatch, get_response=get_response, post_response=post_response)

    result = asyncio.run(wsa.search("AI terbaru", searxng_url="http://localhost:8080", tavily_api_key="test-key"))
    assert result["success"] is True
    assert result["provider"] == "tavily"
    assert result["fallback_from"] == "searxng"
    assert captured[0][0] == "get"
    assert captured[1][0] == "post"
    assert captured[1][2]["api_key"] == "test-key"


def test_search_tavily_only_success_when_searxng_not_configured(monkeypatch):
    response = _FakeResponse(200, {
        "results": [
            {"title": "Artikel A", "url": "https://a.com/x", "content": "Isi A", "score": 0.5, "published_date": "2026-06-10"},
            {"title": "Artikel B", "url": "https://b.com/y", "content": "Isi B", "score": 0.9, "published_date": "2026-06-12"},
        ]
    })
    captured = _patch_client(monkeypatch, post_response=response)

    result = asyncio.run(wsa.search("AI terbaru", tavily_api_key="test-key"))
    assert result["success"] is True
    assert result["provider"] == "tavily"
    assert len(result["results"]) == 2
    assert captured[0][2]["api_key"] == "test-key"
    assert captured[0][2]["query"] == "AI terbaru"


def test_search_http_error_with_no_fallback_left(monkeypatch):
    response = _FakeResponse(500, {}, text="server error")
    _patch_client(monkeypatch, post_response=response)

    result = asyncio.run(wsa.search("AI terbaru", tavily_api_key="test-key"))
    assert result["success"] is False
    assert "error" in result


# ─────────────────────────────────────────────────────────────────
# 5) rank_sources — sort by score, dedupe per domain
# ─────────────────────────────────────────────────────────────────

def test_rank_sources_sorts_by_score_desc_and_dedupes_domain():
    results = [
        {"title": "A", "url": "https://a.com/1", "score": 0.4},
        {"title": "B", "url": "https://b.com/1", "score": 0.9},
        {"title": "A2", "url": "https://a.com/2", "score": 0.95},
    ]
    ranked = wsa.rank_sources(results)
    assert [r["title"] for r in ranked] == ["A2", "B"]


def test_rank_sources_empty():
    assert wsa.rank_sources([]) == []


# ─────────────────────────────────────────────────────────────────
# 6) format_web_search_context
# ─────────────────────────────────────────────────────────────────

def test_format_web_search_context_includes_sources():
    result = {
        "success": True,
        "results": [
            {"title": "Artikel A", "url": "https://a.com/x", "snippet": "Isi A", "score": 0.9, "published_date": "2026-06-12"},
        ],
    }
    formatted = wsa.format_web_search_context(result, "AI terbaru")
    assert "Artikel A" in formatted
    assert "https://a.com/x" in formatted
    assert "2026-06-12" in formatted


def test_format_web_search_context_empty_when_no_results():
    assert wsa.format_web_search_context({"success": True, "results": []}, "x") == ""
    assert wsa.format_web_search_context({"success": False}, "x") == ""


# ─────────────────────────────────────────────────────────────────
# 7) Supervisor integration
# ─────────────────────────────────────────────────────────────────

async def _fake_call_llm_json_default(self, messages, temperature=0.2, max_tokens=512, default=None):
    return default or {}


def _build_supervisor():
    from supervisor import SupervisorAgent
    return SupervisorAgent(api_key="test-key")


def _base_context(**overrides):
    context = {
        "bot_id": "bot-1",
        "org_id": "org-1",
        "conversation_id": "conv-1",
        "user_message": "Apa perkembangan teknologi AI terbaru sekarang?",
        "messages": [],
        "knowledge_base_context": "",
        "reasoning_mode": "standard",
    }
    context.update(overrides)
    return context


def test_supervisor_uses_web_search_when_api_key_configured(monkeypatch):
    captured: dict = {}

    async def fake_call_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        captured["system"] = messages[0]["content"]
        return "Jawaban dengan sumber."

    async def fake_search(query, *, searxng_url="", tavily_api_key="", max_results=5):
        return {
            "success": True,
            "provider": "tavily",
            "query": query,
            "results": [
                {"title": "Artikel AI", "url": "https://news.example.com/ai", "snippet": "Berita AI terbaru.", "score": 0.9, "published_date": "2026-06-13"},
            ],
        }

    monkeypatch.setattr(BaseAgent, "_call_llm", fake_call_llm)
    monkeypatch.setattr(BaseAgent, "_call_llm_json", _fake_call_llm_json_default)

    import supervisor as sup
    monkeypatch.setattr(sup.web_search_agent, "search", fake_search)

    supervisor = _build_supervisor()
    context = _base_context(_search_api_key="tavily-key", _searxng_url="")
    result = asyncio.run(supervisor.process(context))

    assert result.web_search_used is True
    assert len(result.web_search_results) == 1
    assert "Artikel AI" in captured["system"]
    assert "https://news.example.com/ai" in captured["system"]


def test_supervisor_skips_web_search_without_api_key(monkeypatch):
    captured: dict = {}

    async def fake_call_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        captured["system"] = messages[0]["content"]
        return "Jawaban tanpa pencarian web."

    monkeypatch.setattr(BaseAgent, "_call_llm", fake_call_llm)
    monkeypatch.setattr(BaseAgent, "_call_llm_json", _fake_call_llm_json_default)

    supervisor = _build_supervisor()
    context = _base_context()
    result = asyncio.run(supervisor.process(context))

    assert result.web_search_used is False
    assert result.web_search_results == []
    # REALTIME_KNOWLEDGE_BLOCK tetap disisipkan walau web search tidak aktif.
    assert kae.REALTIME_KNOWLEDGE_BLOCK.splitlines()[0] in captured["system"]


# ── Regression: safeguard deterministik OFFICEHOLDER_DISCLAIMER -- LLM tidak
# selalu menaati instruksi REALTIME_KNOWLEDGE_BLOCK untuk fakta yang kuat
# tertanam di training data (mis. "siapa presiden Indonesia" dijawab pakai
# data lama tanpa disclaimer apapun). Disclaimer ini ditambahkan secara paksa
# di supervisor.py, bukan cuma berharap LLM patuh ke instruksi prompt. ─────

def test_officeholder_disclaimer_appended_when_no_web_search_used(monkeypatch):
    async def fake_call_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        return "Presiden Indonesia saat ini adalah Joko Widodo."

    monkeypatch.setattr(BaseAgent, "_call_llm", fake_call_llm)
    monkeypatch.setattr(BaseAgent, "_call_llm_json", _fake_call_llm_json_default)

    supervisor = _build_supervisor()
    context = _base_context(user_message="Siapa presiden Indonesia?")
    result = asyncio.run(supervisor.process(context))

    assert result.web_search_used is False
    assert kae.OFFICEHOLDER_DISCLAIMER in result.final_answer


def test_officeholder_disclaimer_not_appended_when_web_search_used(monkeypatch):
    async def fake_call_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        return "Berdasarkan hasil pencarian, presiden Indonesia saat ini adalah X."

    async def fake_search(query, *, searxng_url="", tavily_api_key="", max_results=5):
        return {
            "success": True,
            "provider": "tavily",
            "query": query,
            "results": [
                {"title": "Profil Presiden", "url": "https://example.com/presiden", "snippet": "Info resmi.", "score": 0.9, "published_date": "2026-06-20"},
            ],
        }

    monkeypatch.setattr(BaseAgent, "_call_llm", fake_call_llm)
    monkeypatch.setattr(BaseAgent, "_call_llm_json", _fake_call_llm_json_default)

    import supervisor as sup
    monkeypatch.setattr(sup.web_search_agent, "search", fake_search)

    supervisor = _build_supervisor()
    context = _base_context(
        user_message="Siapa presiden Indonesia sekarang?",
        _search_api_key="tavily-key", _searxng_url="",
    )
    result = asyncio.run(supervisor.process(context))

    assert result.web_search_used is True
    assert kae.OFFICEHOLDER_DISCLAIMER not in result.final_answer


def test_officeholder_disclaimer_not_appended_for_unrelated_question(monkeypatch):
    async def fake_call_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        return "Hukum Newton menjelaskan gerak benda."

    monkeypatch.setattr(BaseAgent, "_call_llm", fake_call_llm)
    monkeypatch.setattr(BaseAgent, "_call_llm_json", _fake_call_llm_json_default)

    supervisor = _build_supervisor()
    context = _base_context(user_message="Jelaskan hukum Newton")
    result = asyncio.run(supervisor.process(context))

    assert kae.OFFICEHOLDER_DISCLAIMER not in result.final_answer
