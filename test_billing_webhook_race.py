"""
Midtrans/Xendit retry their webhook notification on anything other than a
clean 2xx response, and both gateways can also fire near-simultaneously for
unrelated reasons. The old handlers did:

    invoice = await pool.fetchrow("SELECT * FROM invoices WHERE invoice_number=$1", ...)
    if invoice["status"] != "paid":
        await _mark_invoice_paid(...)

with no row lock -- two concurrent requests could both read "not yet paid"
before either commits, both call _mark_invoice_paid, and (since
payment_history.provider_transaction_id had no UNIQUE constraint) both
INSERT, double-counting revenue and firing "subscription.activated" twice.

Fix: the webhook handlers now SELECT ... FOR UPDATE inside an explicit
transaction (bn_platform/billing.py::midtrans_webhook/xendit_webhook), and
payment_history(provider, provider_transaction_id) is now a UNIQUE index
with _mark_invoice_paid using ON CONFLICT DO NOTHING as a second line of
defense. This test drives the real handlers against the real dev Postgres
pool with two genuinely concurrent calls (asyncio.gather) to prove only one
side effect happens.
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

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


class _FakeRequest:
    def __init__(self, payload: dict, headers: dict | None = None):
        self._payload = payload
        self.headers = headers or {}

    async def json(self):
        return self._payload


def _get_route_endpoint(router, path: str):
    for route in router.routes:
        if route.path == path:
            return route.endpoint
    raise AssertionError(f"route not found: {path}")


async def _seed_org_and_invoice(pool: asyncpg.Pool, *, plan_key: str, amount_idr: int) -> dict:
    org_id = str(uuid.uuid4())
    await pool.execute(
        "INSERT INTO organizations (id, name, slug) VALUES ($1, $2, $3)",
        org_id, f"Test Org {org_id[:8]}", f"test-org-{org_id[:8]}",
    )
    invoice = await create_invoice(
        pool, org_id=org_id, subscription_id=None, amount_idr=amount_idr,
        description="Test invoice", provider="midtrans",
    )
    await pool.execute(
        "UPDATE invoices SET metadata = metadata || $2::jsonb WHERE id=$1",
        invoice["id"], '{"plan_key": "%s", "billing_cycle": "monthly"}' % plan_key,
    )
    return {"org_id": org_id, "invoice": invoice}


def test_concurrent_midtrans_webhook_retries_only_mark_paid_once(monkeypatch):
    async def body(pool):
        import bn_platform.billing as billing_module
        monkeypatch.setattr(billing_module, "midtrans_verify_signature", lambda **kw: True)

        seed = await _seed_org_and_invoice(pool, plan_key="starter", amount_idr=99000)
        order_id = seed["invoice"]["invoice_number"]

        dispatch_calls = []
        async def fake_dispatch(org_id, event, data, pool):
            dispatch_calls.append((org_id, event, data))

        async def fake_dep():
            return None

        router = build_billing_router(
            get_pool=fake_dep, get_current_user=fake_dep,
            require_permission=lambda key: fake_dep, dispatch_webhook=fake_dispatch,
        )
        handler = _get_route_endpoint(router, "/billing/webhooks/midtrans")

        payload = {
            "order_id": order_id, "status_code": "200", "gross_amount": "99000.00",
            "signature_key": "irrelevant-mocked", "transaction_status": "settlement",
            "transaction_id": "tx-fixed-123", "payment_type": "bank_transfer",
        }

        results = await asyncio.gather(
            handler(_FakeRequest(payload), pool),
            handler(_FakeRequest(payload), pool),
        )
        assert all(r == {"ok": True} for r in results)

        payment_rows = await pool.fetch(
            "SELECT * FROM payment_history WHERE invoice_id=$1", seed["invoice"]["id"],
        )
        assert len(payment_rows) == 1

        invoice_row = await pool.fetchrow("SELECT status FROM invoices WHERE id=$1", seed["invoice"]["id"])
        assert invoice_row["status"] == "paid"

        sub_row = await pool.fetchrow("SELECT status FROM subscriptions WHERE org_id=$1", seed["org_id"])
        assert sub_row["status"] == "active"

        assert len(dispatch_calls) == 1

    _run(body)


def test_unique_index_rejects_duplicate_provider_transaction_id_directly(monkeypatch):
    """Sanity check pada index-nya sendiri, terlepas dari logika webhook --
    INSERT kedua dengan (provider, provider_transaction_id) yang sama harus
    di-skip oleh ON CONFLICT, bukan gagal/exception, dan bukan baris baru."""
    async def body(pool):
        seed = await _seed_org_and_invoice(pool, plan_key="starter", amount_idr=99000)
        from bn_platform.billing import _mark_invoice_paid

        invoice = dict(await pool.fetchrow("SELECT * FROM invoices WHERE id=$1", seed["invoice"]["id"]))
        await _mark_invoice_paid(
            pool, invoice, provider="midtrans", provider_tx_id="dup-tx-456",
            payment_method="bank_transfer", raw_payload={},
        )
        # Panggil lagi dengan provider_tx_id yang sama -- harus no-op, tidak exception.
        invoice = dict(await pool.fetchrow("SELECT * FROM invoices WHERE id=$1", seed["invoice"]["id"]))
        await _mark_invoice_paid(
            pool, invoice, provider="midtrans", provider_tx_id="dup-tx-456",
            payment_method="bank_transfer", raw_payload={},
        )

        rows = await pool.fetch(
            "SELECT * FROM payment_history WHERE provider='midtrans' AND provider_transaction_id='dup-tx-456'",
        )
        assert len(rows) == 1

    _run(body)
