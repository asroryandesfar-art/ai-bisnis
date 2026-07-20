"""FastAPI router for Web Intelligence (factory-DI, no import from main).

Mount with:
    from backend.modules.web_intelligence.api.routes import build_web_intelligence_router
    app.include_router(build_web_intelligence_router(
        get_current_user=get_current_user, require_permission=require_permission,
        get_pool=get_pool), prefix="/api")

All injected deps are OPTIONAL — the module also runs standalone (read/crawl are
read-only and safe; ingest requires get_pool + auth). If require_permission is
given, write/ingest routes are RBAC-gated."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response

from ..schemas.models import ReadRequest, CrawlRequest, IngestRequest
from ..services.reader import read_url
from ..services.pipeline import crawl_and_extract, ingest_to_kb
from ..browser.screenshot import capture_screenshot
from ..browser.playwright import playwright_available
from ..cleaner.trafilatura import trafilatura_available
from ..cleaner.readability import readability_available
from ..parser.pdf import pdf_available
from ..cache.cache import default_cache


def build_web_intelligence_router(*, get_current_user=None, require_permission=None,
                                  get_pool=None) -> APIRouter:
    router = APIRouter(prefix="/web-intelligence", tags=["web-intelligence"])

    def _auth(perm: str):
        """Return a dependency: RBAC checker if wired, else current_user, else none."""
        if require_permission is not None:
            return require_permission(perm)
        if get_current_user is not None:
            return get_current_user
        async def _noop():
            return {}
        return _noop

    @router.get("/status")
    async def status():
        return {
            "module": "web_intelligence",
            "capabilities": {
                "static_fetch": True, "html_clean": True, "markdown": True,
                "metadata": True, "tables": True, "recursive_crawl": True,
                "robots_txt": True, "rate_limit": True, "retry": True, "cache": True,
                "js_render_playwright": playwright_available(),
                "screenshot": playwright_available(),
                "extract_trafilatura": trafilatura_available(),
                "extract_readability": readability_available(),
                "pdf": pdf_available(),
            },
            "cache": default_cache.stats(),
        }

    @router.post("/read")
    async def read(body: ReadRequest, user=Depends(_auth("knowledge.read"))):
        return await read_url(
            body.url, render_js=body.render_js, output=body.output,
            include_tables=body.include_tables, include_links=body.include_links,
            include_images=body.include_images, use_cache=body.use_cache,
        )

    @router.post("/crawl")
    async def crawl(body: CrawlRequest, user=Depends(_auth("knowledge.read"))):
        return await crawl_and_extract(
            body.url, max_depth=body.max_depth, max_pages=body.max_pages,
            same_site_only=body.same_site_only, respect_robots=body.respect_robots,
            rate_limit_seconds=body.rate_limit_seconds,
        )

    @router.post("/screenshot")
    async def screenshot(body: ReadRequest, user=Depends(_auth("knowledge.read"))):
        res = await capture_screenshot(body.url)
        if not res.get("success"):
            raise HTTPException(status_code=422 if res.get("available") else 501,
                                detail=res.get("error") or res.get("reason"))
        return Response(content=res["png"], media_type="image/png")

    @router.post("/ingest")
    async def ingest(body: IngestRequest, bot_id: str,
                     user=Depends(_auth("knowledge.write"))):
        if get_pool is None:
            raise HTTPException(503, "Ingest butuh koneksi DB (get_pool tidak di-wire).")
        org_id = str(user.get("org_id")) if isinstance(user, dict) else None
        if not org_id:
            raise HTTPException(401, "Butuh autentikasi tenant untuk ingest ke Knowledge Base.")
        pool = await get_pool()
        return await ingest_to_kb(
            pool, org_id=org_id, bot_id=bot_id, seed_url=body.url,
            max_depth=body.max_depth, max_pages=body.max_pages, category=body.category,
            respect_robots=body.respect_robots,
        )

    @router.post("/cache/clear")
    async def clear_cache(user=Depends(_auth("knowledge.write"))):
        default_cache.clear()
        return {"cleared": True, "cache": default_cache.stats()}

    return router
