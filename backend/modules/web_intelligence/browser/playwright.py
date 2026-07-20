"""JavaScript rendering via Playwright (for SPA / JS-heavy pages).

Opt-in and used only when static fetch yields too little content. Honest
degradation: if Playwright or its browser binaries are not installed,
`playwright_available()` is False and callers fall back to the static path.

SSRF note: the URL is validated (public host) BEFORE launching the browser. The
browser resolves DNS itself (can't be IP-pinned like httpx), so rendering is
gated to already-validated public URLs and is opt-in per request."""
from __future__ import annotations

from ..security.validator import validate_url

_DEFAULT_UA = "BotNesiaWebIntelligence/1.0 (+https://botnesia.uk)"


def playwright_available() -> bool:
    try:
        from playwright.async_api import async_playwright  # noqa: F401
        return True
    except Exception:
        return False


async def render_page(url: str, *, timeout_ms: int = 20_000, wait_until: str = "networkidle") -> dict:
    """Return {available, success, url, html?, status?, reason?} after JS execution."""
    ok, reason = validate_url(url)
    if not ok:
        return {"available": True, "success": False, "url": url, "error": reason, "blocked": True}
    if not playwright_available():
        return {"available": False, "success": False, "url": url,
                "reason": "Rendering JS butuh Playwright + browser (jalankan: playwright install chromium)."}
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            try:
                page = await browser.new_page(user_agent=_DEFAULT_UA)
                resp = await page.goto(url, timeout=timeout_ms, wait_until=wait_until)
                # Re-validate final URL after any client-side redirects.
                final = page.url
                fv_ok, fv_reason = validate_url(final)
                if not fv_ok:
                    return {"available": True, "success": False, "url": url,
                            "error": f"URL setelah render ditolak: {fv_reason}", "blocked": True}
                html = await page.content()
                return {"available": True, "success": True, "url": url, "final_url": final,
                        "status": resp.status if resp else None, "html": html}
            finally:
                await browser.close()
    except Exception as exc:
        return {"available": True, "success": False, "url": url,
                "reason": f"Render gagal: {exc!s}"}
