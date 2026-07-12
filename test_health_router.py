"""Test for the extracted health/readiness router (main.py strangler split)."""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bn_platform.health import build_health_router


def _cfg(**over):
    base = dict(
        groq_api_key="", deepseek_api_key="", openrouter_api_key="",
        gemini_api_key="", google_api_key="", gemini_model="gemini-2.5-flash",
        gemini_pro_model="gemini-2.5-pro", groq_model="groq-model",
    )
    base.update(over)
    ns = SimpleNamespace(**base)
    ns.effective_gemini_api_key = ns.gemini_api_key or ns.google_api_key
    return ns


def _app(cfg, pool=None):
    async def get_pool_safe():
        return pool

    async def ensure_schema(_pool):
        return True

    app = FastAPI()
    app.include_router(build_health_router(get_pool_safe=get_pool_safe, ensure_schema=ensure_schema, cfg=cfg))
    return app


def test_ready_is_always_ok_without_db():
    r = TestClient(_app(_cfg())).get("/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_degraded_when_no_db_and_no_ai_key():
    r = TestClient(_app(_cfg(), pool=None)).get("/health")
    body = r.json()
    assert r.status_code == 200
    assert body["status"] == "degraded"
    assert body["db"] is False
    assert body["ai"]["configured"] is False


def test_health_reports_configured_ai_provider():
    r = TestClient(_app(_cfg(groq_api_key="gsk_x"))).get("/health")
    body = r.json()
    assert body["ai"]["configured"] is True
    assert body["ai"]["providers"]["groq"]["active"] is True
