"""Identitas pajak pembeli — profil per-org + snapshot NPWP/nama ke invoice.

Faktur pajak butuh NPWP pembeli (PKP). Profil disimpan per-org dan di-SNAPSHOT
ke tiap invoice saat diterbitkan, sehingga faktur historis stabil walau profil
berubah kemudian. DB nyata (asyncpg); bersih-bersih di finally.
"""
import asyncio
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
                       oid, f"Tax {oid[:6]}", f"tax-{oid[:6]}")
    return oid


async def _set_profile(pool, org, **kw):
    await pool.execute(
        """INSERT INTO org_billing_profile (org_id, tax_name, tax_npwp, tax_address, is_pkp, updated_at)
           VALUES ($1,$2,$3,$4,$5,NOW())
           ON CONFLICT (org_id) DO UPDATE SET tax_name=EXCLUDED.tax_name,
             tax_npwp=EXCLUDED.tax_npwp, tax_address=EXCLUDED.tax_address, is_pkp=EXCLUDED.is_pkp""",
        org, kw.get("tax_name", ""), kw.get("tax_npwp", ""),
        kw.get("tax_address", ""), kw.get("is_pkp", False),
    )


async def _cleanup(pool, org):
    await pool.execute("DELETE FROM invoices WHERE org_id=$1", org)
    await pool.execute("DELETE FROM org_billing_profile WHERE org_id=$1", org)
    await pool.execute("DELETE FROM organizations WHERE id=$1", org)


def test_get_billing_profile_roundtrip():
    async def body(pool):
        org = await _seed_org(pool)
        try:
            assert await billing.get_billing_profile(pool, org) is None      # belum diisi
            await _set_profile(pool, org, tax_name="PT Contoh", tax_npwp="001234567890000", is_pkp=True)
            prof = await billing.get_billing_profile(pool, org)
            assert prof["tax_name"] == "PT Contoh"
            assert prof["tax_npwp"] == "001234567890000"
            assert prof["is_pkp"] is True
        finally:
            await _cleanup(pool, org)
    _run(body)


def test_invoice_snapshots_buyer_identity():
    async def body(pool):
        org = await _seed_org(pool)
        try:
            await _set_profile(pool, org, tax_name="PT Snapshot", tax_npwp="009876543210000", is_pkp=True)
            inv = await billing.create_invoice(
                pool, org_id=org, subscription_id=None, amount_idr=349000,
                description="Test", provider="manual")
            assert inv["buyer_npwp"] == "009876543210000"
            assert inv["buyer_name"] == "PT Snapshot"

            # Profil berubah → invoice LAMA tetap memakai snapshot lama.
            await _set_profile(pool, org, tax_name="PT Baru", tax_npwp="111111111111111", is_pkp=True)
            still = await pool.fetchrow("SELECT buyer_npwp, buyer_name FROM invoices WHERE id=$1", inv["id"])
            assert still["buyer_npwp"] == "009876543210000"
            assert still["buyer_name"] == "PT Snapshot"

            # Invoice BARU memakai profil terbaru.
            inv2 = await billing.create_invoice(
                pool, org_id=org, subscription_id=None, amount_idr=99000,
                description="Test2", provider="manual")
            assert inv2["buyer_npwp"] == "111111111111111"
        finally:
            await _cleanup(pool, org)
    _run(body)


def test_invoice_without_profile_has_null_buyer():
    async def body(pool):
        org = await _seed_org(pool)
        try:
            inv = await billing.create_invoice(
                pool, org_id=org, subscription_id=None, amount_idr=50000,
                description="No profile", provider="manual")
            assert inv["buyer_npwp"] is None and inv["buyer_name"] is None
        finally:
            await _cleanup(pool, org)
    _run(body)


def test_tax_profile_routes_present():
    paths = {getattr(r, "path", "") for r in main.app.routes}
    assert "/api/billing/tax-profile" in paths
