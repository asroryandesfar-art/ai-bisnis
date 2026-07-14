"""P1-6 — Eksposur pemakaian WhatsApp (visibilitas biaya Meta pass-through).

WA sudah memotong kuota percakapan yang sama (jalur chat() bersama, lihat
_route_inbound_platform_message / _meta_route_and_reply_whatsapp), jadi ini
BUKAN limit baru — hanya menampilkan jumlah percakapan WhatsApp bulan berjalan
supaya eksposur biaya per-channel terlihat di billing.
"""
import asyncio
import uuid

import asyncpg

import bn_platform.billing as billing
import main
from bn_platform.billing import build_billing_router


def test_current_usage_includes_whatsapp_conversations_key():
    async def _run():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            usage = await billing.current_usage(pool, str(uuid.uuid4()))
            assert "whatsapp_conversations" in usage           # kolom SQL ter-wire
            assert usage["whatsapp_conversations"] == 0         # org kosong → 0
        finally:
            await pool.close()
    asyncio.run(_run())


def _route(router, path, method):
    for r in router.routes:
        if r.path.endswith(path) and method in r.methods:
            return r.endpoint
    raise AssertionError(f"route not found: {method} {path}")


def test_get_usage_returns_whatsapp_channel_usage(monkeypatch):
    async def fake_current_usage(pool, org_id):
        return {"conversations": 0, "agents": 0, "users": 0, "knowledge": 0,
                "channels": 0, "image_generations": 0, "whatsapp_conversations": 7}

    async def fake_check(pool, org_id, dim):
        return True, {"plan": "pro", "dimension": dim, "used": 0, "limit": 100}

    monkeypatch.setattr(billing, "current_usage", fake_current_usage)
    monkeypatch.setattr(billing, "check_limit", fake_check)

    async def fake_dep():
        return None

    router = build_billing_router(
        get_pool=fake_dep, get_current_user=fake_dep,
        require_permission=lambda key: fake_dep,
    )
    handler = _route(router, "/billing/usage", "GET")
    out = asyncio.run(handler(user={"org_id": "o1"}, pool=None))
    assert out["channel_usage"]["whatsapp"] == 7
    assert "usage" in out and "conversations" in out["usage"]
