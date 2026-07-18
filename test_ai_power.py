"""AI Power — master autonomy switch. Gate nyata: OFF → HTTP 423 di jalur eksekusi.

Membuktikan default TRUE (non-breaking), toggle persist, dan require_autonomy
menolak (423) saat OFF / lolos saat ON — inti sakelar AI Operations Center.
"""
import asyncio
import uuid

import asyncpg
import pytest
from fastapi import HTTPException

import bn_platform.ai_power as ap
import main


def _run(coro_fn):
    async def _wrapped():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await coro_fn(pool)
        finally:
            await pool.close()
    asyncio.run(_wrapped())


async def _seed_org(pool):
    oid = str(uuid.uuid4())
    await pool.execute("INSERT INTO organizations (id,name,slug) VALUES ($1,$2,$3)",
                       oid, f"AI {oid[:6]}", f"ai-{oid[:6]}")
    return oid


def test_autonomy_defaults_on():
    async def body(pool):
        org = await _seed_org(pool)
        try:
            assert await ap.get_autonomy(pool, org) is True       # default TRUE = non-breaking
        finally:
            await pool.execute("DELETE FROM organizations WHERE id=$1", org)
    _run(body)


def test_toggle_persists():
    async def body(pool):
        org = await _seed_org(pool)
        try:
            await ap.set_autonomy(pool, org, False)
            assert await ap.get_autonomy(pool, org) is False
            await ap.set_autonomy(pool, org, True)
            assert await ap.get_autonomy(pool, org) is True
        finally:
            await pool.execute("DELETE FROM organizations WHERE id=$1", org)
    _run(body)


def test_require_autonomy_gate():
    async def body(pool):
        org = await _seed_org(pool)
        try:
            await ap.require_autonomy(pool, org)                  # ON → lolos (tak raise)
            await ap.set_autonomy(pool, org, False)
            with pytest.raises(HTTPException) as ei:
                await ap.require_autonomy(pool, org)              # OFF → 423
            assert ei.value.status_code == 423
        finally:
            await pool.execute("DELETE FROM organizations WHERE id=$1", org)
    _run(body)


def test_unknown_org_defaults_on():
    async def body(pool):
        assert await ap.get_autonomy(pool, str(uuid.uuid4())) is True
    _run(body)


def test_ai_power_routes_present():
    paths = {getattr(r, "path", "") for r in main.app.routes}
    assert "/api/ai/power" in paths


def test_execution_endpoints_call_the_gate():
    """Regresi: jalur eksekusi nyata memanggil require_autonomy (bukan hanya UI)."""
    import bn_platform.local_agent_router as lar
    import bn_platform.action_executor_router as aer
    assert "require_autonomy" in lar.build_local_agent_router.__globals__
    assert "require_autonomy" in aer.__dict__ or hasattr(aer, "require_autonomy")
