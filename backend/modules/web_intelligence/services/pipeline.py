"""Higher-level pipelines + agent-facing facade.

- `crawl_and_extract`: recursive crawl → extract main content per page.
- `ingest_to_kb`: crawl → extract → chunk → save into the platform Knowledge Base.
- `agent_read` / `agent_crawl`: thin, safe entry points for the Supervisor,
  Research, and Memory agents to call (no side effects unless a pool is given).
"""
from __future__ import annotations

import time

from ..crawler.recursive import recursive_crawl
from ..crawler.crawl import RateLimiter
from ..parser.metadata import extract_metadata
from ..parser.markdown import html_to_markdown
from ..parser.html import html_to_text
from ..cleaner.trafilatura import extract_with_trafilatura
from ..cleaner.readability import extract_main_content
from ..verifier.citation import build_citation
from ..verifier.confidence import score_source
from ..knowledge.chunker import chunk_text
from ..knowledge.vector import save_to_knowledge_base
from .reader import read_url


def _extract_page(html: str, url: str) -> dict:
    metadata = extract_metadata(html, base_url=url)
    traf = extract_with_trafilatura(html, url=url, output="markdown")
    if traf:
        method, text, markdown = traf["method"], traf["text"], traf.get("markdown", traf["text"])
    else:
        main = extract_main_content(html, url=url)
        method, text = main["method"], main["text"]
        markdown = html_to_markdown(main["content_html"], base_url=url)
        if main.get("title") and not metadata.get("title"):
            metadata["title"] = main["title"]
    return {
        "url": url, "title": metadata.get("title"), "method": method,
        "text": text, "markdown": markdown, "metadata": metadata,
        "citation": build_citation(url, metadata, final_url=url),
        "confidence": score_source(url=url, text=text, metadata=metadata, method=method),
    }


async def crawl_and_extract(seed_url: str, *, max_depth: int = 1, max_pages: int = 10,
                            same_site_only: bool = True, respect_robots: bool = True,
                            rate_limit_seconds: float = 1.0, on_progress=None) -> dict:
    """Recursive crawl + per-page content extraction."""
    crawl = await recursive_crawl(
        seed_url, max_depth=max_depth, max_pages=max_pages, same_site_only=same_site_only,
        respect_robots=respect_robots, rate_limit_seconds=rate_limit_seconds, on_progress=on_progress,
    )
    if crawl.get("error"):
        return {"seed": seed_url, "documents": [], "stats": crawl.get("stats", {})}
    docs = [_extract_page(p["html"], p["url"]) for p in crawl["pages"] if p.get("html")]
    return {"seed": seed_url, "documents": docs, "stats": crawl["stats"]}


async def ingest_to_kb(pool, *, org_id: str, bot_id: str, seed_url: str,
                       max_depth: int = 1, max_pages: int = 10, category: str = "web_intelligence",
                       respect_robots: bool = True) -> dict:
    """Crawl → extract → chunk → save to the platform Knowledge Base."""
    started = time.perf_counter()
    crawled = await crawl_and_extract(seed_url, max_depth=max_depth, max_pages=max_pages,
                                      respect_robots=respect_robots)
    saved = []
    for doc in crawled["documents"]:
        chunks = chunk_text(doc["text"])
        if not chunks:
            continue
        res = await save_to_knowledge_base(
            pool, org_id=org_id, bot_id=bot_id, url=doc["url"], title=doc["title"],
            chunks=chunks, category=category, citation=doc["citation"],
        )
        saved.append(res)
    return {
        "seed": seed_url,
        "documents_extracted": len(crawled["documents"]),
        "documents_saved": sum(1 for s in saved if s.get("stored")),
        "total_chunks": sum(s.get("chunks", 0) for s in saved),
        "results": saved,
        "monitoring": {**crawled["stats"], "total_duration_ms": int((time.perf_counter() - started) * 1000)},
    }


# ── Agent-facing facade (Supervisor / Research / Memory) ────────────────────
async def agent_read(url: str, *, output: str = "markdown", render_js: bool = False) -> dict:
    """Safe single-URL read for an agent. Returns text/markdown + citation +
    confidence. No persistence."""
    return await read_url(url, output=output, render_js=render_js,
                          include_tables=True, include_links=False)


async def agent_crawl(seed_url: str, *, max_pages: int = 5, max_depth: int = 1) -> dict:
    """Safe shallow crawl for an agent (read-only, no persistence)."""
    return await crawl_and_extract(seed_url, max_depth=max_depth, max_pages=max_pages)
