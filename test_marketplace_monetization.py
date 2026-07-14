"""Marketplace monetisasi — pembelian template berbayar + bagi hasil publisher.

Menguji jalur LUNAS deterministik (provider='local'): beli template berbayar →
invoice paid → bot dibuat untuk pembeli + entri revenue ledger (publisher 70%,
platform 30%). Disbursement payout = proses ops (status='pending').
"""
import asyncio
import uuid

import asyncpg

import bn_platform.billing as billing
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


async def _seed_org(pool, name):
    oid = str(uuid.uuid4())
    await pool.execute("INSERT INTO organizations (id,name,slug) VALUES ($1,$2,$3)",
                       oid, f"{name} {oid[:6]}", f"{name.lower()}-{oid[:6]}")
    return oid


async def _seed_org_user(pool, name):
    """Org + 1 user nyata (audit_logs.actor_user_id punya FK ke users)."""
    oid = await _seed_org(pool, name)
    uid = str(uuid.uuid4())
    await pool.execute(
        "INSERT INTO users (id,org_id,email,hashed_password) VALUES ($1,$2,$3,$4)",
        uid, oid, f"{uid[:8]}@test.local", "x",
    )
    return oid, uid


def test_uninstall_removes_agent_and_install():
    """Bug fix: uninstall HARUS menghapus bot (hilang dari Pusat Agent) + record
    install, supaya template kembali 'Available' dan bisa dipasang ulang."""
    async def body(pool):
        org, uid = await _seed_org_user(pool, "Uninst")
        try:
            key = await pool.fetchval(
                "SELECT key FROM marketplace_templates WHERE is_paid=FALSE AND status='published' LIMIT 1")
            r = await mp.install_template(pool, org_id=org, user_id=uid, template_key=key, bot_name="X")
            bot_id = r["bot"]["id"]
            assert len(await mp.list_installs(pool, org)) == 1
            await mp.uninstall_install(pool, org_id=org, user_id=uid, install_id=r["install_id"])
            # bot dihapus → hilang dari Pusat Agent
            assert await pool.fetchval("SELECT COUNT(*) FROM bots WHERE id=$1", bot_id) == 0
            # record install ikut hilang (CASCADE) → template Available lagi
            assert await pool.fetchval("SELECT COUNT(*) FROM tenant_template_installs WHERE org_id=$1", org) == 0
            assert len(await mp.list_installs(pool, org)) == 0
            # bisa dipasang ulang (install baru)
            r2 = await mp.install_template(pool, org_id=org, user_id=uid, template_key=key, bot_name="Y")
            assert r2["install_id"] != r["install_id"]
        finally:
            await pool.execute("DELETE FROM tenant_template_installs WHERE org_id=$1", org)
            await pool.execute("DELETE FROM bots WHERE org_id=$1", org)
            await pool.execute("DELETE FROM users WHERE org_id=$1", org)
            await pool.execute("DELETE FROM organizations WHERE id=$1", org)
    _run(body)


def test_record_template_revenue_split():
    async def body(pool):
        pub = await _seed_org(pool, "Pub")
        buyer = await _seed_org(pool, "Buyer")
        inv = str(uuid.uuid4())
        try:
            await mp.record_template_revenue(
                pool, publisher_org_id=pub, buyer_org_id=buyer,
                template_id=None, invoice_id=inv, gross_idr=150000, revenue_share_pct=70,
            )
            row = await pool.fetchrow("SELECT * FROM template_revenue_ledger WHERE invoice_id=$1", inv)
            assert row["publisher_share_idr"] == 105000   # 70%
            assert row["platform_share_idr"] == 45000     # 30%
            assert row["status"] == "pending"
        finally:
            await pool.execute("DELETE FROM template_revenue_ledger WHERE invoice_id=$1", inv)
            await pool.execute("DELETE FROM organizations WHERE id=ANY($1::uuid[])", [pub, buyer])
    _run(body)


def test_paid_install_local_creates_bot_and_revenue(monkeypatch):
    monkeypatch.setattr(billing.platform_cfg, "local_billing_enabled", True)

    async def body(pool):
        pub, pub_user = await _seed_org_user(pool, "Publisher")
        buyer, buyer_uid = await _seed_org_user(pool, "Buyer")
        try:
            created = await mp.create_template(
                pool, org_id=pub, user_id=pub_user,
                data={"name": "Agen Premium X", "category": "Finance & Accounting",
                      "system_prompt": "prompt", "price_idr": 200000},
            )
            key = created["key"]
            await mp.set_template_status(pool, org_id=pub, user_id=pub_user, key=key, publish=True)
            template = await mp.get_template(pool, key)   # published dict
            assert template["is_paid"] is True

            buyer_user = {"id": buyer_uid, "email": "buyer@test.local"}
            res = await mp.create_paid_install(
                pool, org_id=buyer, user=buyer_user, template=template, bot_name=None, provider="local",
            )
            assert res["requires_payment"] is False and res["paid"] is True

            # Bot pembeli dibuat (install tercatat)
            install = await mp._fetch_install_by_template(pool, org_id=buyer, template_id=template["id"])
            assert install is not None
            # Revenue ledger utk publisher
            earn = await mp.publisher_earnings(pool, pub)
            assert earn["sales_count"] == 1
            assert earn["total_earned_idr"] == 140000       # 70% dari 200k
            assert earn["pending_payout_idr"] == 140000
        finally:
            # bersihkan bot & install & ledger & invoice & template & org
            await pool.execute("DELETE FROM template_revenue_ledger WHERE publisher_org_id=$1 OR buyer_org_id=$2", pub, buyer)
            await pool.execute("DELETE FROM tenant_template_installs WHERE org_id=$1", buyer)
            await pool.execute("DELETE FROM bots WHERE org_id=$1", buyer)
            await pool.execute("DELETE FROM invoices WHERE org_id=$1", buyer)
            await pool.execute("DELETE FROM marketplace_templates WHERE owner_org_id=$1", pub)
            await pool.execute("DELETE FROM users WHERE org_id=ANY($1::uuid[])", [pub, buyer])
            await pool.execute("DELETE FROM organizations WHERE id=ANY($1::uuid[])", [pub, buyer])
    _run(body)
