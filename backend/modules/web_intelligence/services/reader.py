"""Single URL Reader — the end-to-end pipeline:

  validate → robots (optional) → fetch → (render JS if needed) → clean →
  extract main content → metadata/tables/links/images → markdown/json/text →
  citation + confidence → monitoring.

Pure orchestration over the module's own components. No imports from `main`."""
from __future__ import annotations

import time

from ..security.validator import validate_url
from ..crawler.crawl import fetch_url, RateLimiter
from ..crawler.robots import is_allowed
from ..browser.playwright import render_page
from ..parser.metadata import extract_metadata, extract_links, extract_images
from ..parser.tables import extract_tables
from ..parser.markdown import html_to_markdown
from ..parser.html import html_to_text
from ..parser.pdf import extract_pdf_text
from ..cleaner.trafilatura import extract_with_trafilatura
from ..cleaner.readability import extract_main_content
from ..verifier.citation import build_citation
from ..verifier.confidence import score_source

# Below this many chars of static text we consider JS-rendering worthwhile.
_THIN_CONTENT_CHARS = 250


async def read_url(
    url: str,
    *,
    render_js: bool = False,
    output: str = "markdown",
    include_tables: bool = True,
    include_links: bool = False,
    include_images: bool = False,
    use_cache: bool = True,
    respect_robots: bool = True,
    rate_limiter: RateLimiter | None = None,
) -> dict:
    """Read + extract one URL. Returns a ReadResult-shaped dict. Never raises."""
    started = time.perf_counter()
    ok, reason = validate_url(url)
    if not ok:
        return {"success": False, "url": url, "error": reason,
                "monitoring": {"status": "blocked", "duration_ms": 0}}

    if respect_robots and not await is_allowed(url):
        return {"success": False, "url": url, "error": "Diblokir oleh robots.txt situs.",
                "monitoring": {"status": "blocked_by_robots",
                               "duration_ms": int((time.perf_counter() - started) * 1000)}}

    fetched = await fetch_url(url, rate_limiter=rate_limiter, use_cache=use_cache)
    if not fetched.get("success"):
        return {"success": False, "url": url, "error": fetched.get("error", "Fetch gagal."),
                "monitoring": {"status": "fetch_failed",
                               "duration_ms": int((time.perf_counter() - started) * 1000)}}

    ctype = fetched.get("content_type", "")
    raw: bytes = fetched.get("content", b"")
    final_url = fetched.get("final_url", url)

    # ── PDF branch ──────────────────────────────────────────────────────
    if "application/pdf" in ctype or url.lower().endswith(".pdf"):
        pdf = extract_pdf_text(raw)
        text = pdf.get("text", "")
        result = _base_result(url, final_url, fetched, method="pdf", rendered=False)
        result.update({"text": text, "markdown": text,
                       "metadata": {"title": url.rsplit("/", 1)[-1], "pages": pdf.get("pages")}})
        return _finalize(result, url, final_url, text, {"title": None}, "pdf", started, fetched)

    html = raw.decode("utf-8", "ignore")
    rendered = False

    # ── JS rendering if requested or content looks thin ─────────────────
    static_text_len = len(html_to_text(html)) if html else 0
    if render_js or static_text_len < _THIN_CONTENT_CHARS:
        rp = await render_page(url)
        if rp.get("success") and rp.get("html"):
            html = rp["html"]
            final_url = rp.get("final_url", final_url)
            rendered = True

    # ── Main-content extraction: trafilatura → readability → bs4 ────────
    metadata = extract_metadata(html, base_url=final_url)
    traf = extract_with_trafilatura(html, url=final_url, output="markdown")
    if traf:
        method = traf["method"]
        text = traf["text"]
        markdown = traf.get("markdown", text)
        content_html = html
    else:
        main = extract_main_content(html, url=final_url)
        method = main["method"]
        content_html = main["content_html"]
        text = main["text"]
        markdown = html_to_markdown(content_html, base_url=final_url)
        if main.get("title") and not metadata.get("title"):
            metadata["title"] = main["title"]

    result = _base_result(url, final_url, fetched, method=method, rendered=rendered)
    result.update({
        "title": metadata.get("title"),
        "text": text,
        "markdown": markdown,
        "metadata": metadata,
        "tables": extract_tables(content_html) if include_tables else [],
        "links": extract_links(html, base_url=final_url) if include_links else [],
        "images": extract_images(html, base_url=final_url) if include_images else [],
    })
    return _finalize(result, url, final_url, text, metadata, method, started, fetched)


def _base_result(url, final_url, fetched, *, method, rendered) -> dict:
    return {
        "success": True, "url": url, "final_url": final_url,
        "status": fetched.get("status"), "content_type": fetched.get("content_type"),
        "method": method, "rendered": rendered,
    }


def _finalize(result, url, final_url, text, metadata, method, started, fetched) -> dict:
    result["citation"] = build_citation(url, metadata, final_url=final_url)
    result["confidence"] = score_source(url=final_url, text=text or "", metadata=metadata, method=method)
    result["monitoring"] = {
        "status": "ok",
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "bytes": fetched.get("bytes", 0),
        "from_cache": fetched.get("from_cache", False),
        "content_chars": len(text or ""),
    }
    return result
