"""Grandfathering (P2) — harga terkunci saat aktivasi.

Bila admin menaikkan harga plan, pelanggan lama tetap membayar harga yang mereka
setujui (locked) selama tetap di plan yang sama. Berpindah plan → kunci ulang
harga plan baru. Menggunakan DB nyata (asyncpg) + selalu memulihkan harga plan
yang diubah di finally supaya tidak mengotori data seed.
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
                       oid, f"GF {oid[:6]}", f"gf-{oid[:6]}")
    return oid


# ── Unit murni: helper effective_price / is_grandfathered ──

def test_effective_price_prefers_locked_when_present():
    sub = {"locked_price_monthly_idr": 299000, "price_monthly_idr": 349000,
           "locked_price_yearly_idr": None, "price_yearly_idr": 3490000}
    assert billing.effective_price(sub, "monthly") == 299000   # locked
    assert billing.effective_price(sub, "yearly") == 3490000   # locked None → live
    assert billing.is_grandfathered(sub, "monthly") is True
    assert billing.is_grandfathered(sub, "yearly") is False


def test_effective_price_falls_back_to_live_when_unlocked():
    sub = {"locked_price_monthly_idr": None, "price_monthly_idr": 349000}
    assert billing.effective_price(sub, "monthly") == 349000
    assert billing.is_grandfathered(sub, "monthly") is False


def test_not_grandfathered_when_locked_equals_or_above_list():
    sub = {"locked_price_monthly_idr": 349000, "price_monthly_idr": 349000}
    assert billing.is_grandfathered(sub, "monthly") is False   # sama → bukan diskon


# ── Integrasi: lifecycle lock lewat activate_subscription ──

def test_activation_locks_price_and_survives_price_increase():
    async def body(pool):
        org = await _seed_org(pool)
        pro = await billing.get_plan_by_key(pool, "pro")
        orig_m, orig_y = pro["price_monthly_idr"], pro["price_yearly_idr"]
        try:
            # Aktivasi Pro → harga terkunci = harga live saat ini
            await billing.activate_subscription(pool, org_id=org, plan_key="pro", billing_cycle="monthly")
            sub = await billing.get_active_subscription(pool, org)
            assert sub["locked_price_monthly_idr"] == orig_m
            assert sub["locked_price_yearly_idr"] == orig_y
            assert sub["price_locked_at"] is not None
            assert billing.is_grandfathered(sub, "monthly") is False   # belum ada kenaikan

            # Admin naikkan harga Pro
            await pool.execute("UPDATE plans SET price_monthly_idr=$1, price_yearly_idr=$2 WHERE key='pro'",
                               orig_m + 100000, orig_y + 1000000)

            # Pelanggan lama tetap di harga locked
            sub = await billing.get_active_subscription(pool, org)
            assert sub["price_monthly_idr"] == orig_m + 100000        # list price naik
            assert sub["locked_price_monthly_idr"] == orig_m          # lock tak berubah
            assert billing.effective_price(sub, "monthly") == orig_m  # ditagih harga lama
            assert billing.is_grandfathered(sub, "monthly") is True

            # Renewal plan yang SAMA (Pro) → lock LAMA dipertahankan (tak re-lock ke harga baru)
            await billing.activate_subscription(pool, org_id=org, plan_key="pro", billing_cycle="monthly")
            sub = await billing.get_active_subscription(pool, org)
            assert sub["locked_price_monthly_idr"] == orig_m
            assert billing.is_grandfathered(sub, "monthly") is True
        finally:
            await pool.execute("UPDATE plans SET price_monthly_idr=$1, price_yearly_idr=$2 WHERE key='pro'",
                               orig_m, orig_y)
            await pool.execute("DELETE FROM subscriptions WHERE org_id=$1", org)
            await pool.execute("DELETE FROM organizations WHERE id=$1", org)
    _run(body)


def test_switching_plan_relocks_to_new_plan_price():
    async def body(pool):
        org = await _seed_org(pool)
        starter = await billing.get_plan_by_key(pool, "starter")
        biz = await billing.get_plan_by_key(pool, "business")
        try:
            await billing.activate_subscription(pool, org_id=org, plan_key="starter", billing_cycle="monthly")
            sub = await billing.get_active_subscription(pool, org)
            assert sub["locked_price_monthly_idr"] == starter["price_monthly_idr"]

            # Pindah ke Business → kunci ULANG ke harga Business saat ini
            await billing.activate_subscription(pool, org_id=org, plan_key="business", billing_cycle="monthly")
            sub = await billing.get_active_subscription(pool, org)
            assert sub["plan_key"] == "business"
            assert sub["locked_price_monthly_idr"] == biz["price_monthly_idr"]
        finally:
            await pool.execute("DELETE FROM subscriptions WHERE org_id=$1", org)
            await pool.execute("DELETE FROM organizations WHERE id=$1", org)
    _run(body)
