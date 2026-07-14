"""Add-on kapasitas (P2) — beli slot agent/anggota/channel/dokumen di atas limit paket.

Membuktikan: grant menambah kapasitas (akumulatif), check_limit menaikkan limit
efektif sesuai kapasitas add-on, dan jalur pembayaran (_mark_invoice_paid dengan
metadata kind='addon_purchase') benar-benar memberi kapasitas. DB nyata (asyncpg);
selalu bersih-bersih di finally.
"""
import asyncio
import json
import uuid

import asyncpg

import bn_platform.billing as billing
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
                       oid, f"AO {oid[:6]}", f"ao-{oid[:6]}")
    return oid


async def _cleanup(pool, org):
    await pool.execute("DELETE FROM org_addons WHERE org_id=$1", org)
    await pool.execute("DELETE FROM invoices WHERE org_id=$1", org)
    await pool.execute("DELETE FROM subscriptions WHERE org_id=$1", org)
    await pool.execute("DELETE FROM organizations WHERE id=$1", org)


def test_catalog_dimensions_are_valid_and_exclude_conversations():
    dims = {a["dimension"] for a in billing.ADDON_CATALOG}
    assert dims <= set(billing.LIMIT_FIELDS)          # semua dimensi valid
    assert "conversations" not in dims                # itu ranah top-up/overage
    assert {a["key"] for a in billing.ADDON_CATALOG} == set(billing._ADDON_BY_KEY)


def test_grant_addon_accumulates():
    async def body(pool):
        org = await _seed_org(pool)
        try:
            await billing.grant_addon(pool, org_id=org, addon_key="extra_agents", units=2)
            assert await billing.get_addon_capacity(pool, org, "agents") == 2
            await billing.grant_addon(pool, org_id=org, addon_key="extra_agents", units=1)
            assert await billing.get_addon_capacity(pool, org, "agents") == 3   # akumulatif
            owned = await billing.get_org_addons(pool, org)
            assert owned["extra_agents"] == {"dimension": "agents", "quantity": 3}
        finally:
            await _cleanup(pool, org)
    _run(body)


def test_check_limit_includes_addon_capacity():
    async def body(pool):
        org = await _seed_org(pool)
        try:
            await billing.activate_subscription(pool, org_id=org, plan_key="starter", billing_cycle="monthly")
            _, detail0 = await billing.check_limit(pool, org, "agents")
            plan_limit = detail0["limit"]
            assert detail0.get("addon_extra", 0) == 0

            await billing.grant_addon(pool, org_id=org, addon_key="extra_agents", units=5)
            ok, detail = await billing.check_limit(pool, org, "agents")
            assert detail["plan_limit"] == plan_limit
            assert detail["addon_extra"] == 5
            assert detail["limit"] == plan_limit + 5      # limit efektif naik
        finally:
            await _cleanup(pool, org)
    _run(body)


def test_addon_purchase_payment_grants_capacity():
    """Jalur pembayaran: invoice metadata kind='addon_purchase' → _mark_invoice_paid
    memanggil grant_addon (units = unit × quantity)."""
    async def body(pool):
        org = await _seed_org(pool)
        try:
            sub = await billing.ensure_subscription(pool, org)
            spec = billing._ADDON_BY_KEY["extra_knowledge"]      # unit=50
            qty = 2
            units = spec["unit"] * qty                            # 100
            invoice = await billing.create_invoice(
                pool, org_id=org, subscription_id=sub["id"],
                amount_idr=spec["price_idr"] * qty,
                description="Add-on Kapasitas: test", provider="manual",
            )
            await pool.execute(
                "UPDATE invoices SET metadata = metadata || $2::jsonb WHERE id=$1",
                invoice["id"], json.dumps({"kind": "addon_purchase",
                                           "addon_key": "extra_knowledge", "units": units, "quantity": qty}),
            )
            async with pool.acquire() as conn:
                async with conn.transaction():
                    inv = dict(await conn.fetchrow("SELECT * FROM invoices WHERE id=$1 FOR UPDATE", invoice["id"]))
                    await billing._mark_invoice_paid(
                        conn, inv, provider="manual",
                        provider_tx_id=f"local-{inv['invoice_number']}",
                        payment_method="local-development", raw_payload={"mode": "local"},
                    )
            assert await billing.get_addon_capacity(pool, org, "knowledge") == 100
        finally:
            await pool.execute("DELETE FROM payment_history WHERE org_id=$1", org)
            await _cleanup(pool, org)
    _run(body)


def test_addon_routes_present():
    paths = {getattr(r, "path", "") for r in main.app.routes}
    assert "/api/billing/addons" in paths
    assert "/api/billing/addons/checkout" in paths
