"""Integration: lifecycle Marketplace install → uninstall (sinkron & tanpa orphan).

Install → agent muncul (bots active, seperti sumber halaman Agents/AI Workforce)
→ uninstall → agent HILANG dari sumber data + seluruh relasi bersih (install,
agent_installs, FAQ ter-seed) → template kembali Available (reinstallable).

Supervisor/Orchestrator/Intent Router bersifat STATIK (agent_registry code, bukan
per-install), jadi tak pernah "mengenal" bot marketplace — dibuktikan: registry
tak berubah oleh install/uninstall.
"""
import asyncio
import uuid

import asyncpg

import agent_registry
import bn_platform.marketplace as mp
import main


def _run(coro_fn):
    async def _wrapped():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await coro_fn(pool)
        finally:
            await pool.close()
    asyncio.run(_wrapped())


async def _seed_org_user(pool):
    oid = str(uuid.uuid4()); uid = str(uuid.uuid4())
    await pool.execute("INSERT INTO organizations (id,name,slug) VALUES ($1,$2,$3)",
                       oid, f"Org {oid[:6]}", f"org-{oid[:6]}")
    await pool.execute("INSERT INTO users (id,org_id,email,hashed_password) VALUES ($1,$2,$3,'x')",
                       uid, oid, f"{uid[:8]}@t.local")
    return oid, uid


async def _agents_source_active(pool, org_id):
    """Meniru sumber daftar agent (halaman Agents / AI Workforce): bot aktif org."""
    return await pool.fetchval(
        "SELECT COUNT(*) FROM bots WHERE org_id=$1 AND status='active'", org_id)


def test_full_install_uninstall_lifecycle_no_orphans():
    async def body(pool):
        org, uid = await _seed_org_user(pool)
        registry_before = len(agent_registry.orchestration_agents())
        try:
            key = await pool.fetchval(
                "SELECT key FROM marketplace_templates WHERE is_paid=FALSE AND status='published' LIMIT 1")

            # ── INSTALL ── agent muncul & aktif
            r = await mp.install_template(pool, org_id=org, user_id=uid, template_key=key, bot_name="Agen Uji")
            bot_id = r["bot"]["id"]
            assert await _agents_source_active(pool, org) == 1                 # muncul di Agents/AI Workforce
            assert len(await mp.list_installs(pool, org)) == 1                 # muncul di Marketplace (installed)
            faq_before = await pool.fetchval("SELECT COUNT(*) FROM faq_entries WHERE bot_id=$1", bot_id)

            # Supervisor/Orchestrator statis: registry tak berubah oleh install.
            assert len(agent_registry.orchestration_agents()) == registry_before

            # ── UNINSTALL ── (atomik)
            res = await mp.uninstall_install(pool, org_id=org, user_id=uid, install_id=r["install_id"])
            assert res["status"] == "removed"

            # Agent HILANG dari semua sumber + NOL orphan
            assert await _agents_source_active(pool, org) == 0                 # hilang dari Agents/AI Workforce
            assert await pool.fetchval("SELECT COUNT(*) FROM bots WHERE id=$1", bot_id) == 0
            assert await pool.fetchval("SELECT COUNT(*) FROM tenant_template_installs WHERE org_id=$1", org) == 0
            assert await pool.fetchval("SELECT COUNT(*) FROM agent_installs WHERE bot_id=$1", bot_id) == 0
            assert await pool.fetchval("SELECT COUNT(*) FROM faq_entries WHERE bot_id=$1", bot_id) == 0  # CASCADE
            assert len(await mp.list_installs(pool, org)) == 0                 # hilang dari Marketplace
            # Router/registry tetap konsisten (tak pernah kenal bot ini)
            assert len(agent_registry.orchestration_agents()) == registry_before

            # ── REINSTALL ── template kembali Available
            r2 = await mp.install_template(pool, org_id=org, user_id=uid, template_key=key, bot_name="Agen Uji 2")
            assert r2["install_id"] != r["install_id"]
            assert await _agents_source_active(pool, org) == 1
            assert faq_before >= 0
        finally:
            await pool.execute("DELETE FROM faq_entries WHERE org_id=$1", org)
            await pool.execute("DELETE FROM tenant_template_installs WHERE org_id=$1", org)
            await pool.execute("DELETE FROM bots WHERE org_id=$1", org)
            await pool.execute("DELETE FROM users WHERE org_id=$1", org)
            await pool.execute("DELETE FROM organizations WHERE id=$1", org)
    _run(body)
