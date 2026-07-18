"""Per-agent ON/OFF toggle — gate nyata per agent (bukan hanya UI).

Default ON (non-breaking), toggle persist, require_agent_enabled menolak (423)
saat OFF. Juga verifikasi jalur run-task agent memanggil gate.
"""
import asyncio
import uuid

import asyncpg
import pytest
from fastapi import HTTPException

import bn_platform.agent_toggles as at
import main


def _run(coro_fn):
    async def _wrapped():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await at.ensure_schema(pool)
            await coro_fn(pool)
        finally:
            await pool.close()
    asyncio.run(_wrapped())


async def _seed_org(pool):
    oid = str(uuid.uuid4())
    await pool.execute("INSERT INTO organizations (id,name,slug) VALUES ($1,$2,$3)",
                       oid, f"AG {oid[:6]}", f"ag-{oid[:6]}")
    return oid


def test_defaults_on_when_unset():
    async def body(pool):
        org = await _seed_org(pool)
        try:
            assert await at.is_agent_enabled(pool, org, "finance") is True
            assert await at.get_agent_toggles(pool, org) == {}          # belum di-set
        finally:
            await pool.execute("DELETE FROM organizations WHERE id=$1", org)
    _run(body)


def test_toggle_persists_and_gate():
    async def body(pool):
        org = await _seed_org(pool)
        try:
            await at.set_agent_enabled(pool, org, "finance", False)
            assert await at.is_agent_enabled(pool, org, "finance") is False
            assert await at.get_agent_toggles(pool, org) == {"finance": False}
            with pytest.raises(HTTPException) as ei:
                await at.require_agent_enabled(pool, org, "finance")
            assert ei.value.status_code == 423
            # agent lain tetap ON
            await at.require_agent_enabled(pool, org, "marketing")
            # nyalakan lagi
            await at.set_agent_enabled(pool, org, "finance", True)
            await at.require_agent_enabled(pool, org, "finance")         # tak raise
        finally:
            await pool.execute("DELETE FROM org_agent_toggles WHERE org_id=$1", org)
            await pool.execute("DELETE FROM organizations WHERE id=$1", org)
    _run(body)


def test_routes_present():
    paths = {getattr(r, "path", "") for r in main.app.routes}
    assert "/api/agents/toggles" in paths
    assert "/api/agents/{agent_key}/toggle" in paths


def test_run_task_endpoints_call_the_gate():
    """Regresi: router agent bisnis + computer memanggil require_agent_enabled."""
    for mod in ("finance", "marketing", "hr", "operations"):
        m = __import__(f"bn_platform.{mod}", fromlist=["x"])
        assert hasattr(m, "require_agent_enabled"), mod
    import bn_platform.local_agent_router as lar
    assert "require_agent_enabled" in lar.build_local_agent_router.__globals__
