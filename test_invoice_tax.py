"""P2-9 — PPN 11% (tax-inclusive) pada invoice.

Harga paket diperlakukan SUDAH termasuk PPN: total tidak berubah, invoice
memecahnya jadi DPP (subtotal) + PPN. Saat pajak nonaktif (default, belum PKP),
subtotal=total & tax=0 (backward compatible).
"""
import asyncio
import uuid

import asyncpg

import bn_platform.billing as billing
import main


def test_tax_disabled_returns_zero(monkeypatch):
    monkeypatch.setattr(billing.platform_cfg, "tax_enabled", False)
    subtotal, tax, rate = billing.compute_invoice_tax(349_000)
    assert (subtotal, tax, rate) == (349_000, 0, 0.0)


def test_tax_inclusive_breakdown(monkeypatch):
    monkeypatch.setattr(billing.platform_cfg, "tax_enabled", True)
    monkeypatch.setattr(billing.platform_cfg, "tax_rate", 0.11)
    subtotal, tax, rate = billing.compute_invoice_tax(349_000)
    # inclusive: subtotal + tax == total (harga tak berubah), rate 11%
    assert subtotal + tax == 349_000
    assert rate == 0.11
    assert subtotal == round(349_000 / 1.11)      # DPP
    assert tax == 349_000 - subtotal              # PPN
    assert 30_000 < tax < 40_000                  # ~34.568


def test_tax_meta_exposed(monkeypatch):
    monkeypatch.setattr(billing.platform_cfg, "tax_enabled", True)
    monkeypatch.setattr(billing.platform_cfg, "seller_name", "BotNesia PT")
    meta = billing.tax_invoice_meta()
    assert meta["tax_enabled"] is True
    assert meta["seller_name"] == "BotNesia PT"
    assert meta["tax_rate"] == 0.11


def test_create_invoice_persists_tax_breakdown(monkeypatch):
    monkeypatch.setattr(billing.platform_cfg, "tax_enabled", True)
    monkeypatch.setattr(billing.platform_cfg, "tax_rate", 0.11)

    async def body(pool):
        org_id = str(uuid.uuid4())
        await pool.execute(
            "INSERT INTO organizations (id, name, slug) VALUES ($1,$2,$3)",
            org_id, f"Tax Org {org_id[:8]}", f"tax-org-{org_id[:8]}",
        )
        try:
            inv = await billing.create_invoice(
                pool, org_id=org_id, subscription_id=None,
                amount_idr=990_000, description="Business plan", provider="manual",
            )
            assert inv["amount_idr"] == 990_000
            assert inv["subtotal_idr"] + inv["tax_idr"] == 990_000
            assert float(inv["tax_rate"]) == 0.11
            assert inv["tax_idr"] > 0
        finally:
            await pool.execute("DELETE FROM invoices WHERE org_id=$1", org_id)
            await pool.execute("DELETE FROM organizations WHERE id=$1", org_id)

    async def _run():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await body(pool)
        finally:
            await pool.close()
    asyncio.run(_run())
