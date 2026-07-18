"""Multi-device Local Agent — registry manager + device SQL + endpoints presence.

Membuktikan: satu org bisa punya BANYAK perangkat, status online/busy/offline
akurat, pemilihan perangkat mengutamakan yang idle, eksekusi menarget perangkat
tertentu dan mem-flip busy→online, deregister membersihkan + menyegarkan primary,
serta shim backward-compat (_conn_ids/_meta, is_connected(org_id)) tetap jalan.
"""
import asyncio
import uuid

import asyncpg
import pytest

import bn_platform.local_agent_router as la
import main


# ── Fakes ────────────────────────────────────────────────────────────────
class FakePool:
    async def fetchrow(self, sql, *a):
        if "INSERT INTO local_agent_commands" in sql:
            return {"id": "cmd-1"}
        return None

    async def execute(self, sql, *a):
        return "OK"

    async def fetch(self, sql, *a):
        return []


class FakeWS:
    """Meniru WebSocket: saat menerima 'execute', langsung selesaikan future."""
    def __init__(self, mgr):
        self.mgr = mgr
        self.sent = []
        self.busy_at_send = None
        self.org = None
        self.device_id = None

    async def send_json(self, payload):
        self.sent.append(payload)
        if payload.get("type") == "execute":
            self.busy_at_send = self.mgr.device_status(self.org, self.device_id)
            fut = self.mgr._futures.get(payload["command_id"])
            if fut and not fut.done():
                fut.set_result({"success": True, "output": "ok"})


def _mgr():
    return la.LocalAgentManager()


# ── Manager: multi-device registry ───────────────────────────────────────
def test_register_multiple_devices_per_org():
    mgr = _mgr()
    org = "org-1"
    mgr.register(org, "dev-a", FakeWS(mgr), {"name": "Laptop"}, "row-a")
    mgr.register(org, "dev-b", FakeWS(mgr), {"name": "Desktop"}, "row-b")
    assert mgr.is_connected(org)                       # backward-compat (any device)
    assert mgr.is_connected(org, "dev-a") and mgr.is_connected(org, "dev-b")
    assert not mgr.is_connected(org, "dev-x")
    assert set(mgr.device_ids(org)) == {"dev-a", "dev-b"}
    assert mgr.device_status(org, "dev-a") == "online"
    assert mgr.device_status(org, "dev-x") is None


def test_primary_shims_track_a_device():
    mgr = _mgr()
    mgr.register("o", "d1", FakeWS(mgr), {"name": "A"}, "row-1")
    assert mgr._conn_ids["o"] == "row-1"               # shim untuk pemanggil lama
    assert mgr.get_meta("o")["name"] == "A"


def test_deregister_refreshes_and_clears():
    mgr = _mgr()
    mgr.register("o", "d1", FakeWS(mgr), {"name": "A"}, "row-1")
    mgr.register("o", "d2", FakeWS(mgr), {"name": "B"}, "row-2")
    asyncio.run(mgr.deregister("o", "d1", FakePool()))
    assert mgr.device_ids("o") == ["d2"]
    assert mgr._conn_ids["o"] == "row-2"               # primary pindah ke sisa
    asyncio.run(mgr.deregister("o", "d2", FakePool()))
    assert not mgr.is_connected("o")
    assert "o" not in mgr._conn_ids and "o" not in mgr._meta


def test_pick_prefers_idle_device():
    mgr = _mgr()
    mgr.register("o", "busy", FakeWS(mgr), {}, "r1")
    mgr.register("o", "idle", FakeWS(mgr), {}, "r2")
    mgr._devices["o"]["busy"].busy = True
    did, conn = mgr._pick("o", None)
    assert did == "idle"                                # lewati yang busy


def test_execute_targets_device_and_flips_busy():
    mgr = _mgr()
    ws = FakeWS(mgr); ws.org = "o"; ws.device_id = "d1"
    mgr.register("o", "d1", ws, {"name": "A"}, "row-1")
    result = asyncio.run(mgr.execute("o", "get_info", {}, device_id="d1", pool=FakePool()))
    assert result["success"] is True
    assert ws.sent[0]["tool"] == "get_info"             # perintah sampai ke perangkat
    assert ws.busy_at_send == "busy"                    # busy SELAMA eksekusi
    assert mgr.device_status("o", "d1") == "online"     # kembali online setelah selesai


def test_execute_unknown_device_raises():
    from fastapi import HTTPException
    mgr = _mgr()
    mgr.register("o", "d1", FakeWS(mgr), {}, "row-1")
    with pytest.raises(HTTPException) as ei:
        asyncio.run(mgr.execute("o", "get_info", {}, device_id="ghost", pool=FakePool()))
    assert ei.value.status_code == 503


# ── DB: device upsert + rename (skema nyata) ─────────────────────────────
def test_device_upsert_and_rename_sql():
    async def body():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await la.ensure_schema(pool)
            org = str(uuid.uuid4())
            await pool.execute("INSERT INTO organizations (id,name,slug) VALUES ($1,$2,$3)",
                               org, f"D {org[:6]}", f"d-{org[:6]}")
            dev = "dev-xyz"
            # upsert pertama
            rid = await pool.fetchval(
                """INSERT INTO local_agent_devices (org_id, device_id, name, hostname, status)
                   VALUES ($1,$2,$3,$4,'online') RETURNING id""", org, dev, "Laptop Kerja", "host1")
            assert rid
            # upsert kedua (reconnect) tak menimpa nama hasil rename (COALESCE)
            await pool.execute(
                """INSERT INTO local_agent_devices (org_id, device_id, name, hostname, status)
                   VALUES ($1,$2,$3,$4,'online')
                   ON CONFLICT (org_id, device_id) DO UPDATE SET
                       name=COALESCE(local_agent_devices.name, EXCLUDED.name),
                       hostname=EXCLUDED.hostname, status='online'""",
                org, dev, "host1-default", "host1-new")
            row = await pool.fetchrow("SELECT name, hostname FROM local_agent_devices WHERE org_id=$1 AND device_id=$2", org, dev)
            assert row["name"] == "Laptop Kerja"          # nama dipertahankan
            assert row["hostname"] == "host1-new"          # metadata diperbarui
            # rename
            await pool.execute("UPDATE local_agent_devices SET name=$1 WHERE org_id=$2 AND device_id=$3",
                               "PC Rumah", org, dev)
            assert await pool.fetchval("SELECT name FROM local_agent_devices WHERE org_id=$1 AND device_id=$2", org, dev) == "PC Rumah"
        finally:
            await pool.execute("DELETE FROM local_agent_devices WHERE org_id=$1", org)
            await pool.execute("DELETE FROM organizations WHERE id=$1", org)
            await pool.close()
    asyncio.run(body())


def test_device_routes_present():
    paths = {getattr(r, "path", "") for r in main.app.routes}
    assert "/api/local-agent/devices" in paths
    assert "/api/local-agent/devices/{device_id}/rename" in paths
    assert "/api/local-agent/devices/{device_id}/disconnect" in paths
