"""
checkout()'s "local" provider path (used for local/dev billing approval)
called _mark_invoice_paid(pool, ...) -- update invoice, insert
payment_history, activate_subscription, audit log -- as four independent
pooled statements with no transaction wrapper, same gap as the webhook
handlers had before the race-condition fix (test_billing_webhook_race.py).
Unlike the webhook retries, there's no concurrent-double-insert risk here
(each checkout() call creates a brand-new invoice), but a crash mid-sequence
(e.g. activate_subscription raising) could still leave the invoice marked
'paid' with no subscription actually activated -- an inconsistent state
that's not safely retryable, since the invoice no longer satisfies
status != 'paid' on a retry.

Fix: the local-payment branch now runs inside one explicit transaction
(SELECT ... FOR UPDATE + the same _mark_invoice_paid call), so a failure
partway through rolls back everything instead of leaving a half-applied
state.
"""
import asyncio
import uuid

import asyncpg
import pytest

import main
from bn_platform.billing import build_billing_router, create_invoice


def _run(coro_fn):
    async def _wrapped():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await coro_fn(pool)
        finally:
            await pool.close()
    asyncio.run(_wrapped())


def _get_route_endpoint(router, path: str, method: str):
    for route in router.routes:
        if route.path == path and method in route.methods:
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


async def _seed_org(pool: asyncpg.Pool) -> str:
    org_id = str(uuid.uuid4())
    await pool.execute(
        "INSERT INTO organizations (id, name, slug) VALUES ($1, $2, $3)",
        org_id, f"Test Org {org_id[:8]}", f"test-org-{org_id[:8]}",
    )
    return org_id


async def _delete_org(pool: asyncpg.Pool, org_id: str) -> None:
    await pool.execute("DELETE FROM organizations WHERE id=$1", org_id)


def _build_checkout_handler(monkeypatch, *, local_billing_enabled: bool = True):
    import bn_platform.billing as billing_module
    monkeypatch.setattr(billing_module.platform_cfg, "local_billing_enabled", local_billing_enabled)

    async def fake_dep():
        return None

    router = build_billing_router(
        get_pool=fake_dep, get_current_user=fake_dep,
        require_permission=lambda key: fake_dep, dispatch_webhook=None,
    )
    return _get_route_endpoint(router, "/billing/checkout", "POST")


def test_local_checkout_atomically_marks_paid_and_activates_subscription(monkeypatch):
    async def body(pool):
        org_id = await _seed_org(pool)
        try:
            handler = _build_checkout_handler(monkeypatch)
            from bn_platform.billing import CheckoutReq

            user = {"org_id": org_id, "id": "user-1", "email": "owner@test.local", "full_name": "Owner"}
            result = await handler(
                CheckoutReq(plan_key="starter", billing_cycle="monthly", provider="local"),
                user=user, pool=pool,
            )
            assert result["requires_payment"] is False
            assert result["local"] is True

            invoice_row = await pool.fetchrow("SELECT status FROM invoices WHERE id=$1", result["invoice_id"])
            assert invoice_row["status"] == "paid"

            payment_rows = await pool.fetch(
                "SELECT * FROM payment_history WHERE invoice_id=$1", result["invoice_id"],
            )
            assert len(payment_rows) == 1

            sub_row = await pool.fetchrow("SELECT status FROM subscriptions WHERE org_id=$1", org_id)
            assert sub_row["status"] == "active"
        finally:
            await _delete_org(pool, org_id)

    _run(body)


def test_local_checkout_rolls_back_everything_if_activate_subscription_fails(monkeypatch):
    """The property the transaction wrapper exists for: if activate_subscription
    raises mid-sequence, the invoice must NOT end up stuck as 'paid' with no
    payment_history/subscription to show for it."""
    async def body(pool):
        org_id = await _seed_org(pool)
        try:
            handler = _build_checkout_handler(monkeypatch)
            from bn_platform.billing import CheckoutReq
            import bn_platform.billing as billing_module

            async def boom(*args, **kwargs):
                raise RuntimeError("simulated crash mid-transaction")

            monkeypatch.setattr(billing_module, "activate_subscription", boom)

            user = {"org_id": org_id, "id": "user-1", "email": "owner@test.local", "full_name": "Owner"}
            with pytest.raises(RuntimeError):
                await handler(
                    CheckoutReq(plan_key="starter", billing_cycle="monthly", provider="local"),
                    user=user, pool=pool,
                )

            invoice_rows = await pool.fetch(
                "SELECT status FROM invoices WHERE org_id=$1", org_id,
            )
            assert len(invoice_rows) == 1
            assert invoice_rows[0]["status"] == "open"  # NOT 'paid' -- rolled back

            payment_rows = await pool.fetch(
                "SELECT * FROM payment_history WHERE org_id=$1", org_id,
            )
            assert payment_rows == []  # rolled back too, not an orphaned row

            # ensure_subscription() runs before the transaction (separate
            # concern: makes sure a subscription row exists at all) so it's
            # untouched by the rollback -- what matters is it was never
            # flipped to 'active' by the (rolled-back) activate_subscription.
            sub_row = await pool.fetchrow("SELECT status FROM subscriptions WHERE org_id=$1", org_id)
            assert sub_row["status"] != "active"
        finally:
            await _delete_org(pool, org_id)

    _run(body)
