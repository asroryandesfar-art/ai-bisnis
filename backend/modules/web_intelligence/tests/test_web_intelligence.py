"""Web Intelligence — unit + integration tests (network mocked)."""
import asyncio

import pytest

from backend.modules.web_intelligence.security import validator, sanitizer
from backend.modules.web_intelligence.cache.cache import TTLCache
from backend.modules.web_intelligence.parser import html as phtml, markdown as pmd, metadata as pmeta, tables as ptab, pdf as ppdf
from backend.modules.web_intelligence.cleaner.readability import extract_main_content, readability_available
from backend.modules.web_intelligence.cleaner.trafilatura import trafilatura_available, extract_with_trafilatura
from backend.modules.web_intelligence.verifier import citation as vcit, confidence as vconf
from backend.modules.web_intelligence.knowledge.chunker import chunk_text
from backend.modules.web_intelligence.knowledge.vector import save_to_knowledge_base
from backend.modules.web_intelligence.crawler import crawl as ccrawl
from backend.modules.web_intelligence.services import reader as rdr

SAMPLE = '''<html lang="en"><head><title>T</title><meta name="description" content="D">
<meta property="og:site_name" content="S"><link rel="canonical" href="/canon"></head><body>
<nav class="menu">NAV</nav><script>bad()</script>
<article><h1>Head</h1><p>Body <strong>bold</strong> <a href="/x">link</a></p>
<ul><li>one</li></ul><table><tr><th>H</th></tr><tr><td>v</td></tr></table>
<img src="/a.png" alt="pic"></article><footer class="social">F</footer></body></html>'''


# ── security: validator ─────────────────────────────────────────────────────
@pytest.mark.parametrize("url", [
    "http://localhost/x", "http://127.0.0.1", "http://10.0.0.1", "http://192.168.1.1",
    "file:///etc/passwd", "ftp://host/f", "javascript:alert(1)", "data:text/html,x",
    "vbscript:x", "ws://host", "", "   ", "http://", "notaurl",
])
def test_validator_blocks_unsafe(url):
    assert validator.validate_url(url)[0] is False

def test_validator_allows_public():
    assert validator.validate_url("https://example.com/page")[0] is True
    assert validator.is_valid_url("https://example.com") is True

def test_validator_too_long():
    assert validator.validate_url("https://x.com/" + "a" * 3000)[0] is False

def test_validator_control_chars():
    assert validator.validate_url("https://x.com/\nadmin")[0] is False


# ── security: sanitizer ─────────────────────────────────────────────────────
def test_sanitize_url_input():
    assert sanitizer.sanitize_url_input("  https://x.com\x00  ") == "https://x.com"
    assert sanitizer.sanitize_url_input(None) == ""

def test_sanitize_text_collapses_ws():
    assert sanitizer.sanitize_text("a\x00b   c\n\n\n\nd") == "ab c\n\nd"

def test_is_dangerous_link():
    assert sanitizer.is_dangerous_link("javascript:x") is True
    assert sanitizer.is_dangerous_link("https://x.com") is False


# ── cache ───────────────────────────────────────────────────────────────────
def test_cache_hit_miss_and_stats():
    c = TTLCache(ttl_seconds=100, max_entries=2)
    k = TTLCache.key_for("u")
    assert c.get(k) is None
    c.set(k, {"v": 1})
    assert c.get(k) == {"v": 1}
    s = c.stats()
    assert s["hits"] == 1 and s["misses"] == 1 and s["entries"] == 1

def test_cache_lru_eviction():
    c = TTLCache(max_entries=2)
    for i in range(3):
        c.set(TTLCache.key_for(str(i)), i)
    assert len(c._store) == 2   # oldest evicted

def test_cache_ttl_expiry(monkeypatch):
    import backend.modules.web_intelligence.cache.cache as cache_mod
    c = TTLCache(ttl_seconds=10)
    k = TTLCache.key_for("u")
    c.set(k, 1)
    monkeypatch.setattr(cache_mod.time, "time", lambda: 1e18)
    assert c.get(k) is None


# ── parsers ─────────────────────────────────────────────────────────────────
def test_html_clean_removes_script_and_boilerplate():
    txt = phtml.html_to_text(SAMPLE)
    assert "bad()" not in txt and "NAV" not in txt and "Head" in txt

def test_markdown_conversion():
    md = pmd.html_to_markdown(SAMPLE, base_url="https://s.com/p")
    assert "# Head" in md and "**bold**" in md and "- one" in md and "[link](https://s.com/x)" in md

def test_metadata_extraction():
    m = pmeta.extract_metadata(SAMPLE, base_url="https://s.com/p")
    assert m["title"] == "T" and m["description"] == "D" and m["language"] == "en"
    assert m["site_name"] == "S" and m["canonical_url"].endswith("/canon")

def test_links_and_images():
    assert pmeta.extract_links(SAMPLE, base_url="https://s.com/p") == ["https://s.com/x"]
    imgs = pmeta.extract_images(SAMPLE, base_url="https://s.com/p")
    assert imgs[0]["src"].endswith("/a.png") and imgs[0]["alt"] == "pic"

def test_tables_extraction():
    t = ptab.extract_tables(SAMPLE)
    assert t and t[0]["headers"] == ["H"] and "| H |" in t[0]["markdown"]

def test_pdf_unavailable_or_ok():
    r = ppdf.extract_pdf_text(b"%PDF-1.4 not-a-real-pdf")
    assert "available" in r  # never raises; degrades honestly


# ── cleaner ─────────────────────────────────────────────────────────────────
def test_extract_main_content_fallback():
    m = extract_main_content(SAMPLE)
    assert m["method"] in ("trafilatura", "readability-lxml", "bs4-heuristic")
    assert "Head" in m["text"] and "NAV" not in m["text"]

def test_trafilatura_degrades():
    if not trafilatura_available():
        assert extract_with_trafilatura(SAMPLE) is None


# ── verifier ────────────────────────────────────────────────────────────────
def test_citation():
    c = vcit.build_citation("https://s.com/p", {"title": "T", "author": "A"})
    assert c["domain"] == "s.com" and c["title"] == "T" and c["accessed_at"]
    assert "s.com" in vcit.format_citation(c)

def test_confidence_levels():
    hi = vconf.score_source(url="https://s.com", text="x" * 3000,
                            metadata={"title": "t", "description": "d", "author": "a",
                                      "published_at": "2026", "canonical_url": "c"},
                            method="trafilatura")
    lo = vconf.score_source(url="http://a.xyz", text="", metadata={}, method="bs4-heuristic")
    assert hi["score"] > lo["score"] and hi["level"] == "high" and lo["level"] == "low"


# ── chunker ─────────────────────────────────────────────────────────────────
def test_chunker():
    assert chunk_text("") == []
    chunks = chunk_text("para one.\n\n" + "word " * 400, max_chars=500, overlap=50)
    assert len(chunks) >= 2 and all(len(c) <= 600 for c in chunks)


# ── crawler helpers ─────────────────────────────────────────────────────────
def test_rate_limiter():
    rl = ccrawl.RateLimiter(0.05)
    import time
    async def go():
        t = time.monotonic()
        await rl.acquire("h"); await rl.acquire("h")
        return time.monotonic() - t
    assert asyncio.run(go()) >= 0.05

def test_retry_reraises():
    import httpx
    calls = {"n": 0}
    async def boom():
        calls["n"] += 1
        raise httpx.ConnectError("x")
    with pytest.raises(httpx.ConnectError):
        asyncio.run(ccrawl.retry_async(boom, attempts=3, base_delay=0.001))
    assert calls["n"] == 3


# ── knowledge/vector (no real DB) ───────────────────────────────────────────
def test_save_to_kb_no_pool():
    r = asyncio.run(save_to_knowledge_base(None, org_id="o", bot_id="b", url="u", title="t", chunks=["a"]))
    assert r["stored"] is False


# ── services/reader (network mocked) ────────────────────────────────────────
def test_read_url_blocks_unsafe():
    r = asyncio.run(rdr.read_url("http://localhost/x"))
    assert r["success"] is False and r["monitoring"]["status"] == "blocked"

def test_read_url_full_pipeline(monkeypatch):
    async def fake_fetch(url, **k):
        return {"success": True, "url": url, "final_url": url, "status": 200,
                "content_type": "text/html", "content": SAMPLE.encode(),
                "bytes": len(SAMPLE), "from_cache": False}
    async def allow(url, **k):
        return True
    async def no_render(url, **k):
        return {"available": True, "success": False}
    monkeypatch.setattr(rdr, "validate_url", lambda u: (True, ""))
    monkeypatch.setattr(rdr, "fetch_url", fake_fetch)
    monkeypatch.setattr(rdr, "is_allowed", allow)
    monkeypatch.setattr(rdr, "render_page", no_render)
    r = asyncio.run(rdr.read_url("https://s.com/p", include_links=True))
    assert r["success"] is True
    assert r["title"] == "T"
    assert "# Head" in r["markdown"]
    assert r["citation"]["domain"] == "s.com"
    assert r["confidence"]["level"] in ("low", "medium", "high")
    assert r["monitoring"]["status"] == "ok"

def test_read_url_robots_blocked(monkeypatch):
    async def deny(url, **k):
        return False
    monkeypatch.setattr(rdr, "validate_url", lambda u: (True, ""))
    monkeypatch.setattr(rdr, "is_allowed", deny)
    r = asyncio.run(rdr.read_url("https://s.com/p"))
    assert r["success"] is False and "robots" in r["monitoring"]["status"]


# ── recursive crawl (network mocked) ────────────────────────────────────────
def test_recursive_crawl_bfs(monkeypatch):
    from backend.modules.web_intelligence.crawler import recursive as rec
    PAGES = {
        "https://s.com/": '<a href="/a">a</a><a href="/b">b</a><a href="https://other.com/x">o</a>',
        "https://s.com/a": '<p>page a</p>',
        "https://s.com/b": '<p>page b</p>',
    }
    async def fake_fetch(url, **k):
        html = PAGES.get(url, "")
        return {"success": True, "url": url, "final_url": url, "status": 200,
                "content_type": "text/html", "content": html.encode(), "bytes": len(html)}
    async def allow(url, **k):
        return True
    monkeypatch.setattr(rec, "fetch_url", fake_fetch)
    monkeypatch.setattr(rec, "is_allowed", allow)
    monkeypatch.setattr(rec, "validate_url", lambda u: (True, ""))
    out = asyncio.run(rec.recursive_crawl("https://s.com/", max_depth=1, max_pages=10,
                                          same_site_only=True, respect_robots=True, rate_limit_seconds=0))
    urls = {p["url"] for p in out["pages"]}
    assert "https://s.com/" in urls and "https://s.com/a" in urls and "https://s.com/b" in urls
    assert "https://other.com/x" not in urls          # same-site scoping
    assert out["stats"]["pages_crawled"] == 3

def test_recursive_crawl_rejects_bad_seed():
    from backend.modules.web_intelligence.crawler import recursive as rec
    out = asyncio.run(rec.recursive_crawl("file:///etc/passwd"))
    assert out["pages"] == [] and out["stats"]["status"] == "rejected"


# ── API router (TestClient) ─────────────────────────────────────────────────
def test_router_status_and_read(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.modules.web_intelligence.api import routes
    async def fake_read(url, **k):
        return {"success": True, "url": url, "markdown": "# ok", "title": "T"}
    monkeypatch.setattr(routes, "read_url", fake_read)
    app = FastAPI()
    app.include_router(routes.build_web_intelligence_router(), prefix="/api")
    c = TestClient(app)
    st = c.get("/api/web-intelligence/status").json()
    assert st["module"] == "web_intelligence" and st["capabilities"]["markdown"] is True
    r = c.post("/api/web-intelligence/read", json={"url": "https://s.com"}).json()
    assert r["success"] is True and r["markdown"] == "# ok"

def test_router_rbac_gate_called():
    from backend.modules.web_intelligence.api import routes
    seen = []
    def require_permission(perm):
        seen.append(perm)
        async def _c():
            return {"org_id": "o"}
        return _c
    routes.build_web_intelligence_router(require_permission=require_permission, get_pool=lambda: None)
    assert "knowledge.read" in seen and "knowledge.write" in seen
