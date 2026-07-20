"""Full-page screenshot via Playwright (PNG bytes). Degrades honestly."""
from __future__ import annotations

from ..security.validator import validate_url
from .playwright import playwright_available, _DEFAULT_UA


async def capture_screenshot(url: str, *, timeout_ms: int = 20_000, full_page: bool = True) -> dict:
    """Return {available, success, url, png?, reason?}."""
    ok, reason = validate_url(url)
    if not ok:
        return {"available": True, "success": False, "url": url, "error": reason, "blocked": True}
    if not playwright_available():
        return {"available": False, "success": False, "url": url,
                "reason": "Screenshot butuh Playwright + browser (playwright install chromium)."}
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            try:
                page = await browser.new_page(user_agent=_DEFAULT_UA)
                await page.goto(url, timeout=timeout_ms, wait_until="networkidle")
                fv_ok, fv_reason = validate_url(page.url)
                if not fv_ok:
                    return {"available": True, "success": False, "url": url,
                            "error": f"URL setelah render ditolak: {fv_reason}", "blocked": True}
                png = await page.screenshot(full_page=full_page, type="png")
                return {"available": True, "success": True, "url": url, "png": png, "bytes": len(png)}
            finally:
                await browser.close()
    except Exception as exc:
        return {"available": True, "success": False, "url": url, "reason": f"Screenshot gagal: {exc!s}"}
