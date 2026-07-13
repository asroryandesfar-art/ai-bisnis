"""P0-2 — Kunci kurva harga paket monoton di DB `plans`.

Harga per-percakapan HARUS turun tiap naik paket (Starter > Pro > Business),
kalau tidak, paket lebih mahal justru value/rupiah lebih buruk (bug lama:
Business Rp99,9/conv > Pro Rp59,8/conv). Test membaca tabel plans nyata
(sumber kebenaran enforcement `check_limit` & pricing UI), jadi mendeteksi
kalau migrasi belum diterapkan.
"""
import asyncio

import asyncpg

import main


def _plans():
    async def _run():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            rows = await pool.fetch(
                "SELECT key, price_monthly_idr, price_yearly_idr, "
                "max_conversations_per_month FROM plans WHERE is_active"
            )
            return {r["key"]: dict(r) for r in rows}
        finally:
            await pool.close()
    return asyncio.run(_run())


def test_new_plan_values_applied():
    p = _plans()
    assert p["pro"]["price_monthly_idr"] == 349_000
    assert p["pro"]["price_yearly_idr"] == 3_490_000
    assert p["business"]["price_monthly_idr"] == 990_000
    assert p["business"]["price_yearly_idr"] == 9_900_000
    assert p["business"]["max_conversations_per_month"] == 16_500


def test_price_per_conversation_is_monotonic_decreasing():
    p = _plans()

    def ppc(key):
        return p[key]["price_monthly_idr"] / p[key]["max_conversations_per_month"]

    starter, pro, business = ppc("starter"), ppc("pro"), ppc("business")
    # Starter 99 > Pro 69,8 > Business 60 — makin tinggi paket, makin murah/percakapan.
    assert starter > pro > business, (
        f"kurva tidak monoton: starter={starter:.1f} pro={pro:.1f} business={business:.1f}"
    )


def test_annual_gives_two_months_free():
    # price_yearly = 10x monthly (2 bulan gratis) untuk paket berbayar.
    p = _plans()
    for key in ("starter", "pro", "business"):
        assert p[key]["price_yearly_idr"] == p[key]["price_monthly_idr"] * 10
