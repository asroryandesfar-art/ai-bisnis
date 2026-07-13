"""P0-4 — Lantai Enterprise + guard checkout + quote flow.

- Enterprise punya harga lantai (bukan 0) & kuota percakapan FINITE (bukan -1).
- Kurva tetap monoton termasuk Enterprise (Rp/conv < Business).
- Checkout self-serve untuk paket custom/Enterprise DITOLAK (harus sales).
- /billing/plans mengekspos sales_email untuk CTA "Hubungi Sales".
"""
import asyncio

import asyncpg
import pytest
from fastapi import HTTPException

import main
from bn_platform.billing import CheckoutReq, build_billing_router


def _run(coro_fn):
    async def _wrapped():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await coro_fn(pool)
        finally:
            await pool.close()
    asyncio.run(_wrapped())


def _route(router, path, method):
    for r in router.routes:
        if r.path.endswith(path) and method in r.methods:
            return r.endpoint
    raise AssertionError(f"route not found: {method} {path}")


def _router():
    async def fake_dep():
        return None
    return build_billing_router(
        get_pool=fake_dep, get_current_user=fake_dep,
        require_permission=lambda key: fake_dep, dispatch_webhook=None,
    )


def test_enterprise_has_floor_price_and_finite_quota():
    async def body(pool):
        r = await pool.fetchrow(
            "SELECT price_monthly_idr, price_yearly_idr, max_conversations_per_month "
            "FROM plans WHERE key='enterprise'"
        )
        assert r["price_monthly_idr"] == 4_000_000
        assert r["price_yearly_idr"] == 40_000_000
        assert r["max_conversations_per_month"] == 100_000  # finite, bukan -1
    _run(body)


def test_price_per_conversation_monotonic_through_enterprise():
    async def body(pool):
        rows = await pool.fetch(
            "SELECT key, price_monthly_idr, max_conversations_per_month "
            "FROM plans WHERE key IN ('business','enterprise')"
        )
        p = {r["key"]: dict(r) for r in rows}
        biz = p["business"]["price_monthly_idr"] / p["business"]["max_conversations_per_month"]
        ent = p["enterprise"]["price_monthly_idr"] / p["enterprise"]["max_conversations_per_month"]
        assert ent < biz, f"enterprise Rp{ent:.1f}/conv harus < business Rp{biz:.1f}/conv"
    _run(body)


def test_get_plans_exposes_sales_email():
    async def body(pool):
        handler = _route(_router(), "/billing/plans", "GET")
        out = await handler(pool=pool)
        assert out.get("sales_email")
        assert "@" in out["sales_email"]
        assert any(pl["key"] == "enterprise" for pl in out["plans"])
    _run(body)


def test_checkout_rejects_enterprise_self_serve():
    async def body(pool):
        handler = _route(_router(), "/billing/checkout", "POST")
        user = {"org_id": "test-ent-guard", "id": "u1", "email": "x@test.local"}
        with pytest.raises(HTTPException) as exc:
            await handler(
                CheckoutReq(plan_key="enterprise", billing_cycle="monthly", provider="local"),
                user=user, pool=pool,
            )
        assert exc.value.status_code == 400
        assert "sales" in exc.value.detail.lower() or "@" in exc.value.detail
    _run(body)
