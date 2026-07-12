"""Test for the extracted static/pages router (main.py strangler split).

Verifies the factory registers every page route and serves files from the given
base dir, so the extraction is behavior-preserving and self-contained (no import
cycle with main).
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bn_platform.pages import build_pages_router

EXPECTED_PATHS = {
    "/", "/casper", "/dashboard/billing", "/dashboard/billing/{result_page}",
    "/demo", "/dashboard", "/ui/{asset_path:path}", "/assets/{asset_path:path}",
    "/download/botnesia-local-agent.py", "/favicon.ico", "/apple-touch-icon.png",
    "/botnesia-widget.js", "/api.js", "/multiagent", "/multiagent/quick-start",
    "/multiagent/framework", "/multiagent/integration",
}


def test_factory_registers_all_page_routes():
    router = build_pages_router(Path("/tmp"))
    got = {r.path for r in router.routes}
    assert EXPECTED_PATHS <= got, f"missing: {EXPECTED_PATHS - got}"


def test_serves_landing_from_base_dir(tmp_path):
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "landing.html").write_text("<h1>hi</h1>", encoding="utf-8")
    app = FastAPI()
    app.include_router(build_pages_router(tmp_path))
    r = TestClient(app).get("/")
    assert r.status_code == 200
    assert "hi" in r.text


def test_missing_file_returns_404(tmp_path):
    app = FastAPI()
    app.include_router(build_pages_router(tmp_path))
    r = TestClient(app).get("/demo")
    assert r.status_code == 404


def test_casper_redirects(tmp_path):
    app = FastAPI()
    app.include_router(build_pages_router(tmp_path))
    r = TestClient(app).get("/casper", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/dashboard#casper-agentic-workflow"
