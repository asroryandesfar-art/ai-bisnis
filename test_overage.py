"""P1-5 — Overage prabayar: saldo top-up dipakai saat kuota paket habis.

Menguji consume_conversation_quota (deterministik; check_limit/addon/add_credits
di-fake). Ini SEKALIGUS memperbaiki bug lama: top-up tidak pernah dikonsumsi.
"""
import asyncio

import bn_platform.billing as billing


def test_within_plan_allows_without_debit(monkeypatch):
    debits = []

    async def fake_check(pool, org, dim):
        return True, {"plan": "pro", "used": 10, "limit": 5000}

    async def fake_addon(pool, org):
        return 0

    async def fake_add(pool, **kw):
        debits.append(kw)

    monkeypatch.setattr(billing, "check_limit", fake_check)
    monkeypatch.setattr(billing, "get_addon_conversation_balance", fake_addon)
    monkeypatch.setattr(billing, "add_credits", fake_add)

    ok, detail = asyncio.run(billing.consume_conversation_quota(None, "org1"))
    assert ok is True
    assert detail["source"] == "plan"
    assert debits == []  # tidak mendebit saldo saat masih dalam kuota


def test_over_plan_consumes_topup_balance(monkeypatch):
    debits = []

    async def fake_check(pool, org, dim):
        return False, {"plan": "pro", "used": 5000, "limit": 5000}

    async def fake_addon(pool, org):
        return 3

    async def fake_add(pool, *, org_id, conversations, amount_idr, kind, description, **kw):
        debits.append((conversations, kind))

    monkeypatch.setattr(billing, "check_limit", fake_check)
    monkeypatch.setattr(billing, "get_addon_conversation_balance", fake_addon)
    monkeypatch.setattr(billing, "add_credits", fake_add)

    ok, detail = asyncio.run(billing.consume_conversation_quota(None, "org1"))
    assert ok is True
    assert detail["source"] == "addon"          # overage dari top-up
    assert detail["addon_remaining"] == 2
    assert debits == [(-1, "debit")]            # tepat 1 percakapan didebit


def test_exhausted_denies(monkeypatch):
    debits = []

    async def fake_check(pool, org, dim):
        return False, {"plan": "starter", "used": 1000, "limit": 1000}

    async def fake_addon(pool, org):
        return 0

    async def fake_add(pool, **kw):
        debits.append(kw)

    monkeypatch.setattr(billing, "check_limit", fake_check)
    monkeypatch.setattr(billing, "get_addon_conversation_balance", fake_addon)
    monkeypatch.setattr(billing, "add_credits", fake_add)

    ok, detail = asyncio.run(billing.consume_conversation_quota(None, "org1"))
    assert ok is False
    assert detail["source"] == "exhausted"
    assert detail["addon_remaining"] == 0
    assert debits == []  # tak ada yang didebit saat saldo 0
