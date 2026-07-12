"""Static/landing/asset page routes, extracted verbatim from main.py.

These endpoints serve HTML and static files and have NO database or auth
dependency, which makes them the safest first slice of the main.py strangler
split. The factory takes the project base dir and derives the same paths main.py
used, so behavior is byte-for-byte identical and there is no import cycle with
main.
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse, RedirectResponse


def build_pages_router(base_dir: Path) -> APIRouter:
    base_dir = Path(base_dir)
    frontend_dir = base_dir / "frontend"
    public_dir = frontend_dir / "public"
    dashboard_path = frontend_dir / "index.html"
    public_demo_path = frontend_dir / "demo.html"
    landing_path = frontend_dir / "landing.html"
    api_js_path = base_dir / "api.js"
    multiagent_index_path = base_dir / "MultiAgent_Index.html"
    multiagent_quick_path = base_dir / "MultiAgent_Quick_Start.html"
    multiagent_framework_path = base_dir / "MultiAgent_AI_Framework.html"
    multiagent_integration_path = base_dir / "MultiAgent_App_Integration.html"
    official_logo_path = public_dir / "assets" / "brand" / "botnesia-clean-logo.png"

    router = APIRouter()

    @router.get("/", include_in_schema=False)
    async def root():
        if landing_path.exists():
            return FileResponse(
                landing_path,
                media_type="text/html",
                headers={"Cache-Control": "no-store"},
            )
        if dashboard_path.exists():
            return RedirectResponse(url="/dashboard")
        return {"status": "ok"}

    @router.get("/casper", include_in_schema=False)
    async def casper_agentic_page():
        """Redirect to the Casper Agentic Workflow dashboard tab (Buildathon 2026)."""
        return RedirectResponse(url="/dashboard#casper-agentic-workflow", status_code=302)

    @router.get("/dashboard/billing", include_in_schema=False)
    async def dashboard_billing_redirect(request: Request):
        qs = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(url=f"/dashboard{qs}#billing", status_code=302)

    @router.get("/dashboard/billing/{result_page}", include_in_schema=False)
    async def dashboard_billing_result_redirect(result_page: str, request: Request):
        qs = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(url=f"/dashboard{qs}#billing", status_code=302)

    @router.get("/demo", include_in_schema=False)
    async def public_demo_page():
        if not public_demo_path.exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "demo.html tidak ditemukan")
        return FileResponse(
            public_demo_path,
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/dashboard", include_in_schema=False)
    async def dashboard():
        if not dashboard_path.exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "dashboard-connected.html tidak ditemukan")
        return FileResponse(
            dashboard_path,
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/ui/{asset_path:path}", include_in_schema=False)
    async def frontend_asset(asset_path: str):
        requested = (frontend_dir / asset_path).resolve()
        frontend_root = frontend_dir.resolve()
        if frontend_root not in requested.parents or not requested.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset UI tidak ditemukan")
        media_types = {
            ".css": "text/css",
            ".js": "application/javascript",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".webp": "image/webp",
            ".ico": "image/x-icon",
        }
        return FileResponse(
            requested,
            media_type=media_types.get(requested.suffix.lower(), "application/octet-stream"),
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/assets/{asset_path:path}", include_in_schema=False)
    async def public_asset(asset_path: str):
        requested = (public_dir / "assets" / asset_path).resolve()
        public_assets_root = (public_dir / "assets").resolve()
        if public_assets_root not in requested.parents or not requested.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset publik tidak ditemukan")
        media_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".svg": "image/svg+xml",
            ".webp": "image/webp",
            ".ico": "image/x-icon",
        }
        return FileResponse(
            requested,
            media_type=media_types.get(requested.suffix.lower(), "application/octet-stream"),
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @router.get("/download/botnesia-local-agent.py", include_in_schema=False)
    async def download_local_agent():
        """Download botnesia_local_agent.py — tersedia untuk semua tenant tanpa auth."""
        script_path = base_dir / "botnesia_local_agent.py"
        if not script_path.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Script tidak ditemukan")
        return FileResponse(
            script_path,
            media_type="text/x-python",
            filename="botnesia_local_agent.py",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/favicon.ico", include_in_schema=False)
    async def favicon_ico():
        if not official_logo_path.exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "logo resmi BotNesia tidak ditemukan")
        return FileResponse(official_logo_path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})

    @router.get("/apple-touch-icon.png", include_in_schema=False)
    async def apple_touch_icon():
        if not official_logo_path.exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "logo resmi BotNesia tidak ditemukan")
        return FileResponse(official_logo_path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})

    @router.get("/botnesia-widget.js", include_in_schema=False)
    async def botnesia_widget_js():
        widget_path = frontend_dir / "botnesia-widget.js"
        if not widget_path.exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "BotNesia widget tidak ditemukan")
        return FileResponse(widget_path, media_type="application/javascript", headers={"Cache-Control": "public, max-age=300"})

    @router.get("/api.js", include_in_schema=False)
    async def api_client_js():
        if not api_js_path.exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "api.js tidak ditemukan")
        return FileResponse(
            api_js_path,
            media_type="application/javascript",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/multiagent", include_in_schema=False)
    async def multiagent_index():
        if not multiagent_index_path.exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "MultiAgent_Index.html tidak ditemukan")
        return FileResponse(
            multiagent_index_path,
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/multiagent/quick-start", include_in_schema=False)
    async def multiagent_quick_start():
        if not multiagent_quick_path.exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "MultiAgent_Quick_Start.html tidak ditemukan")
        return FileResponse(
            multiagent_quick_path,
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/multiagent/framework", include_in_schema=False)
    async def multiagent_framework():
        if not multiagent_framework_path.exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "MultiAgent_AI_Framework.html tidak ditemukan")
        return FileResponse(
            multiagent_framework_path,
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/multiagent/integration", include_in_schema=False)
    async def multiagent_integration():
        if not multiagent_integration_path.exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "MultiAgent_App_Integration.html tidak ditemukan")
        return FileResponse(
            multiagent_integration_path,
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    return router
