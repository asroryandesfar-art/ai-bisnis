"""Recursive / BFS website crawl with depth & page limits, same-origin scoping,
robots.txt compliance, and live monitoring (pages / bytes / duration / progress)."""
from __future__ import annotations

import time
from urllib.parse import urlparse

from .crawl import RateLimiter, fetch_url
from .robots import is_allowed
from ..parser.metadata import extract_links
from ..security.validator import validate_url


def _same_site(a: str, b: str) -> bool:
    return urlparse(a).hostname == urlparse(b).hostname


async def recursive_crawl(
    seed_url: str,
    *,
    max_depth: int = 2,
    max_pages: int = 25,
    same_site_only: bool = True,
    respect_robots: bool = True,
    rate_limit_seconds: float = 1.0,
    timeout: float = 20.0,
    on_progress=None,
) -> dict:
    """Crawl starting from `seed_url`. Returns {seed, pages:[{url,status,bytes,html}],
    stats:{...}}. Read-only; write-safe by construction (no side effects on sites)."""
    ok, reason = validate_url(seed_url)
    if not ok:
        return {"seed": seed_url, "pages": [], "error": reason,
                "stats": {"status": "rejected", "reason": reason}}

    limiter = RateLimiter(rate_limit_seconds)
    started = time.perf_counter()
    seen: set[str] = {seed_url}
    queue: list[tuple[str, int]] = [(seed_url, 0)]
    pages: list[dict] = []
    total_bytes = 0
    errors = 0

    while queue and len(pages) < max_pages:
        url, depth = queue.pop(0)
        if respect_robots and not await is_allowed(url):
            continue
        res = await fetch_url(url, timeout=timeout, rate_limiter=limiter)
        if not res.get("success"):
            errors += 1
            continue
        ctype = res.get("content_type", "")
        html = res["content"].decode("utf-8", "ignore") if ctype.startswith("text/html") else ""
        total_bytes += res.get("bytes", 0)
        page = {"url": res.get("final_url", url), "status": res.get("status"),
                "bytes": res.get("bytes", 0), "depth": depth,
                "content_type": ctype, "html": html}
        pages.append(page)
        if on_progress:
            try:
                on_progress({"crawled": len(pages), "queued": len(queue),
                             "max_pages": max_pages, "current_url": url})
            except Exception:
                pass
        # enqueue children
        if depth < max_depth and html:
            for link in extract_links(html, base_url=res.get("final_url", url)):
                if link in seen or len(seen) >= max_pages * 5:
                    continue
                if same_site_only and not _same_site(seed_url, link):
                    continue
                if not validate_url(link)[0]:
                    continue
                seen.add(link)
                queue.append((link, depth + 1))

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "seed": seed_url,
        "pages": pages,
        "stats": {
            "status": "completed",
            "pages_crawled": len(pages),
            "errors": errors,
            "total_bytes": total_bytes,
            "duration_ms": elapsed_ms,
            "max_depth": max_depth,
            "max_pages": max_pages,
        },
    }
