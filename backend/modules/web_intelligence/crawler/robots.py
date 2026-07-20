"""robots.txt checker (respects site crawl rules). Fetches over the SSRF-safe
HTTP path and caches parsed rules per origin."""
from __future__ import annotations

import time
from urllib.parse import urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx

from ..security.validator import validate_url

USER_AGENT = "BotNesiaWebIntelligence/1.0 (+https://botnesia.uk)"
_cache: dict[str, tuple[float, RobotFileParser | None]] = {}
_TTL = 3600


def _origin(url: str) -> str:
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, "", "", "", ""))


async def _fetch_robots(origin: str, *, timeout: float = 8.0) -> RobotFileParser | None:
    robots_url = origin.rstrip("/") + "/robots.txt"
    ok, _ = validate_url(robots_url)
    if not ok:
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                     headers={"User-Agent": USER_AGENT}) as client:
            resp = await client.get(robots_url)
    except Exception:
        return None
    rp = RobotFileParser()
    if resp.status_code >= 400:
        rp.parse([])          # no robots.txt / error → allow all (standard behavior)
        return rp
    rp.parse(resp.text.splitlines())
    return rp


async def is_allowed(url: str, *, user_agent: str = USER_AGENT) -> bool:
    """True if `url` may be crawled per the site's robots.txt (fail-open on fetch
    error, which is standard: absence of robots.txt means allowed)."""
    origin = _origin(url)
    now = time.time()
    cached = _cache.get(origin)
    if cached and now - cached[0] < _TTL:
        rp = cached[1]
    else:
        rp = await _fetch_robots(origin)
        _cache[origin] = (now, rp)
    if rp is None:
        return True
    try:
        return rp.can_fetch(user_agent, url)
    except Exception:
        return True


async def crawl_delay(url: str, *, user_agent: str = USER_AGENT) -> float | None:
    origin = _origin(url)
    cached = _cache.get(origin)
    rp = cached[1] if cached else None
    if rp is None:
        return None
    try:
        d = rp.crawl_delay(user_agent)
        return float(d) if d is not None else None
    except Exception:
        return None


def clear_cache() -> None:
    _cache.clear()
