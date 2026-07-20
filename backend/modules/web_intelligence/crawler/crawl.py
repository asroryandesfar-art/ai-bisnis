"""Core HTTP fetcher: SSRF-safe, redirect-safe, with rate-limiting, retry,
timeout and TTL caching. Reuses the platform's IP-pinning (build_pinned_request)
so DNS-rebinding protection is identical to the rest of the app."""
from __future__ import annotations

import asyncio
import time
from urllib.parse import urlparse

import httpx

from tool_registry import build_pinned_request, SSRFBlocked
from ..security.validator import validate_url
from ..cache.cache import TTLCache, default_cache
from .robots import USER_AGENT

MAX_BYTES = 5_000_000        # 5 MB per page
MAX_REDIRECTS = 5
DEFAULT_TIMEOUT = 20.0


class RateLimiter:
    """Per-host minimum interval between requests (politeness)."""

    def __init__(self, min_interval_seconds: float = 1.0):
        self.min_interval = max(0.0, float(min_interval_seconds))
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def acquire(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            wait = self.min_interval - (now - self._last.get(host, 0.0))
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[host] = time.monotonic()


async def retry_async(coro_factory, *, attempts: int = 3, base_delay: float = 0.5):
    """Run an async factory with exponential backoff. Re-raises the last error."""
    last: Exception | None = None
    for i in range(max(1, attempts)):
        try:
            return await coro_factory()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last = exc
            if i < attempts - 1:
                await asyncio.sleep(base_delay * (2 ** i))
        except Exception:
            raise
    if last:
        raise last


async def fetch_url(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = MAX_BYTES,
    rate_limiter: RateLimiter | None = None,
    cache: TTLCache | None = default_cache,
    use_cache: bool = True,
    attempts: int = 3,
) -> dict:
    """Fetch one URL. Returns {success, url, final_url, status, content_type,
    content, elapsed_ms, from_cache, error?}. Never raises."""
    ok, reason = validate_url(url)
    if not ok:
        return {"success": False, "url": url, "error": reason, "blocked": True}

    ck = TTLCache.key_for(url)
    if use_cache and cache is not None:
        hit = cache.get(ck)
        if hit is not None:
            return {**hit, "from_cache": True}

    host = urlparse(url).hostname or ""
    if rate_limiter is not None:
        await rate_limiter.acquire(host)

    started = time.perf_counter()

    async def _do() -> dict:
        async with httpx.AsyncClient(timeout=timeout) as client:
            current = url
            for _ in range(MAX_REDIRECTS + 1):
                v_ok, v_reason = validate_url(current)
                if not v_ok:
                    return {"success": False, "url": url, "error": f"Redirect ditolak: {v_reason}"}
                try:
                    req = build_pinned_request(client, "GET", current,
                                               headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
                except SSRFBlocked as exc:
                    return {"success": False, "url": url, "error": str(exc), "blocked": True}
                resp = await client.send(req, stream=True, follow_redirects=False)
                if resp.is_redirect and resp.headers.get("location"):
                    await resp.aclose()
                    current = str(httpx.URL(current).join(resp.headers["location"]))
                    continue
                # read bounded body
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) >= max_bytes:
                        break
                await resp.aclose()
                ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
                return {
                    "success": resp.status_code < 400,
                    "url": url, "final_url": current, "status": resp.status_code,
                    "content_type": ctype, "content": bytes(buf),
                    "bytes": len(buf), "truncated": len(buf) >= max_bytes,
                }
            return {"success": False, "url": url, "error": "Terlalu banyak redirect."}

    try:
        result = await retry_async(_do, attempts=attempts)
    except Exception as exc:
        return {"success": False, "url": url, "error": f"Fetch gagal: {exc!s}",
                "elapsed_ms": int((time.perf_counter() - started) * 1000)}

    result["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    result["from_cache"] = False
    if use_cache and cache is not None and result.get("success"):
        cache.set(ck, result)
    return result
