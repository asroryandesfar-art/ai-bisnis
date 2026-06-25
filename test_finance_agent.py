"""Tests untuk Finance Agent (AI Workforce Phase 1): finance_agent.py
(persistence helpers + FinanceAgent NLP) dan bn_platform/finance.py
(router RBAC gating + endpoint behavior).

Mengikuti pola FakePool + _route dari test_workflow_builder.py dan mock
_call_llm_json dari test_reasoning_pipeline.py -- tidak ada panggilan Groq
atau database sungguhan."""
import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

import finance_agent as fa
from bn_platform.finance import (
    build_finance_router, InvoiceCreateRequest, ExpenseCreateRequest, InvoiceStatusRequest,
    RunTaskRequest,
)


def _route(router, path, method):
    for r in router.routes:
        if r.path.endswith(path) and method in r.methods:
            return r.endpoint
    raise AssertionError(f"route not found: {method} {path}")


# ─── FakePool ───────────────────────────────────────────────────

class FakePool:
    def __init__(self, fetchval_results=None, fetchrow_results=None, fetch_results=None):
        self.calls = []
        self._fetchval_results = list(fetchval_results or [])
        self._fetchrow_results = list(fetchrow_results or [])
        self._fetch_results = list(fetch_results or [])

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        return self._fetchval_results.pop(0) if self._fetchval_results else None

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self._fetchrow_results.pop(0) if self._fetchrow_results else None

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return self._fetch_results.pop(0) if self._fetch_results else []

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return "OK"


# ─── Heuristic ──────────────────────────────────────────────────

def test_looks_like_finance_request():
    assert fa.looks_like_finance_request("Buatkan invoice untuk Budi")
    assert fa.looks_like_finance_request("Berapa profit bulan ini?")
    assert not fa.looks_like_finance_request("Halo, apa kabar?")


# ─── Persistence helpers ────────────────────────────────────────

def test_next_invoice_number_format():
    pool = FakePool(fetchval_results=[5])
    number = asyncio.run(fa._next_invoice_number(pool, "org-1"))
    year = fa._now().year
    assert number == f"INV-{year}-000006"


def test_create_invoice_inserts_and_returns_row():
    pool = FakePool(
        fetchval_results=[0],
        fetchrow_results=[{"id": "inv-1", "invoice_number": "INV-2026-000001",
                            "customer_name": "Budi", "amount_idr": 500000, "line_items": "[]"}],
    )
    invoice = asyncio.run(fa.create_invoice(
        pool, org_id="org-1", bot_id=None, customer_name="Budi", customer_contact=None,
        amount_idr=500000, due_date=None, line_items=None, notes=None,
        is_recurring=False, created_by="user-1",
    ))
    assert invoice["customer_name"] == "Budi"
    assert any("INSERT INTO finance_invoices" in c[1] for c in pool.calls)


def test_mark_invoice_status_rejects_invalid_status():
    pool = FakePool()
    with pytest.raises(ValueError):
        asyncio.run(fa.mark_invoice_status(pool, org_id="org-1", invoice_id="inv-1", status="bogus"))


def test_record_payment_marks_invoice_paid_and_writes_ledger():
    pool = FakePool(fetchrow_results=[
        {"id": "pay-1", "invoice_id": "inv-1", "amount_idr": 500000},
        {"id": "inv-1", "invoice_number": "INV-2026-000001", "status": "paid"},
    ])
    result = asyncio.run(fa.record_payment(
        pool, org_id="org-1", invoice_id="inv-1", amount_idr=500000, method="transfer",
        paid_at=None, notes=None, created_by="user-1",
    ))
    assert result["invoice"]["status"] == "paid"
    assert any("INSERT INTO finance_transactions" in c[1] and c[2][2] == "income" for c in pool.calls)


def test_record_expense_writes_ledger_entry():
    pool = FakePool(fetchrow_results=[{"id": "exp-1", "category": "operasional", "amount_idr": 100000}])
    result = asyncio.run(fa.record_expense(
        pool, org_id="org-1", category="operasional", description="Listrik kantor",
        amount_idr=100000, expense_date=None, created_by="user-1",
    ))
    assert result["category"] == "operasional"
    assert any("INSERT INTO finance_transactions" in c[1] and c[2][2] == "expense" for c in pool.calls)


def test_generate_revenue_report():
    pool = FakePool(
        fetchrow_results=[{"total_idr": 1_500_000, "tx_count": 3}],
        fetch_results=[[{"category": "pembayaran", "total_idr": 1_500_000}]],
    )
    start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    end = datetime(2026, 6, 1, tzinfo=timezone.utc)
    report = asyncio.run(fa.generate_revenue_report(pool, "org-1", start, end))
    assert report["total_revenue_idr"] == 1_500_000
    assert report["transaction_count"] == 3


def test_generate_profit_report_computes_margin():
    pool = FakePool(fetchrow_results=[{"income_idr": 200_000, "expense_idr": 50_000}])
    start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    end = datetime(2026, 6, 1, tzinfo=timezone.utc)
    report = asyncio.run(fa.generate_profit_report(pool, "org-1", start, end))
    assert report["profit_idr"] == 150_000
    assert report["profit_margin_pct"] == 75.0


def test_generate_cashflow_report_running_balance():
    pool = FakePool(fetch_results=[[
        {"day": datetime(2026, 6, 1, tzinfo=timezone.utc), "inflow_idr": 100_000, "outflow_idr": 40_000},
        {"day": datetime(2026, 6, 2, tzinfo=timezone.utc), "inflow_idr": 0, "outflow_idr": 20_000},
    ]])
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    end = datetime(2026, 6, 3, tzinfo=timezone.utc)
    report = asyncio.run(fa.generate_cashflow_report(pool, "org-1", start, end))
    assert report["daily"][0]["running_balance_idr"] == 60_000
    assert report["daily"][1]["running_balance_idr"] == 40_000
    assert report["ending_balance_idr"] == 40_000


def test_generate_forecast_detects_trend():
    pool = FakePool(fetch_results=[[
        {"month": datetime(2026, 4, 1, tzinfo=timezone.utc), "income_idr": 100_000, "expense_idr": 50_000},
        {"month": datetime(2026, 5, 1, tzinfo=timezone.utc), "income_idr": 300_000, "expense_idr": 50_000},
    ]])
    forecast = asyncio.run(fa.generate_forecast(pool, "org-1", months_back=2))
    assert forecast["trend"] == "naik"
    assert forecast["next_month_income_idr"] == 200_000


def test_generate_forecast_insufficient_data():
    pool = FakePool(fetch_results=[[]])
    forecast = asyncio.run(fa.generate_forecast(pool, "org-1"))
    assert forecast["trend"] == "insufficient_data"


def test_dashboard_summary_aggregates():
    pool = FakePool(
        fetchrow_results=[
            {"revenue_idr": 1_000_000, "profit_idr": 600_000},
            {"cnt": 2, "total_idr": 300_000},
            {"mrr_idr": 100_000, "cancelled_cnt": 1, "total_cnt": 4},
        ],
        fetchval_results=[1],
    )
    summary = asyncio.run(fa.dashboard_summary(pool, "org-1"))
    assert summary["revenue_30d_idr"] == 1_000_000
    assert summary["pending_invoices_count"] == 2
    assert summary["overdue_invoices_count"] == 1
    assert summary["mrr_idr"] == 100_000
    assert summary["arr_idr"] == 1_200_000
    assert summary["churn_pct"] == 25.0


# ─── FinanceAgent (NLP) ─────────────────────────────────────────

def test_finance_agent_requires_org_id_and_pool():
    agent = fa.FinanceAgent(api_key="test-key")
    result = asyncio.run(agent.run({"user_message": "buatkan invoice"}))
    assert result.success is False
    assert "org_id" in result.error


def test_finance_agent_create_invoice_from_natural_language(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.1, max_tokens=512, default=None):
        return {"action": "create_invoice", "customer_name": "Budi", "amount_idr": 500000,
                "due_date": None, "notes": None}

    monkeypatch.setattr(fa.FinanceAgent, "_call_llm_json", fake_call_llm_json)
    pool = FakePool(
        fetchval_results=[0],
        fetchrow_results=[{"id": "inv-1", "invoice_number": "INV-2026-000001",
                            "customer_name": "Budi", "amount_idr": 500000, "line_items": "[]"}],
    )
    agent = fa.FinanceAgent(api_key="test-key")
    result = asyncio.run(agent.run({
        "user_message": "Buatkan invoice untuk Budi Rp 500000",
        "org_id": "org-1", "pool": pool, "actor_user_id": "user-1",
    }))
    assert result.success is True
    assert result.output["result"]["customer_name"] == "Budi"


def test_finance_agent_unknown_intent_fails_gracefully(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.1, max_tokens=512, default=None):
        return {"action": "unknown"}

    monkeypatch.setattr(fa.FinanceAgent, "_call_llm_json", fake_call_llm_json)
    pool = FakePool()
    agent = fa.FinanceAgent(api_key="test-key")
    result = asyncio.run(agent.run({
        "user_message": "halo apa kabar", "org_id": "org-1", "pool": pool, "actor_user_id": "user-1",
    }))
    assert result.success is False


# ─── Router: RBAC gating ────────────────────────────────────────

def test_router_gates_every_route_with_finance_permission():
    requested_keys = []

    def recording_require_permission(key):
        requested_keys.append(key)
        async def _checker(user=None, pool=None):
            return user
        return _checker

    async def get_pool():
        return FakePool()

    async def get_current_user():
        return {"org_id": "org-1", "id": "user-1"}

    build_finance_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=recording_require_permission,
        get_agent_config=lambda: {"api_key": ""},
    )

    assert requested_keys.count("finance.read") == 10
    assert requested_keys.count("finance.write") == 7
    assert requested_keys.count("finance.approve") == 1
    assert set(requested_keys) == {"finance.read", "finance.write", "finance.approve"}


def _build_router(pool):
    async def get_pool():
        return pool

    async def get_current_user():
        return {"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}

    def require_permission(_key):
        return get_current_user

    return build_finance_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=require_permission, get_agent_config=lambda: {"api_key": ""},
    )


def test_create_invoice_route_writes_audit_log():
    pool = FakePool(
        fetchval_results=[0],
        fetchrow_results=[{"id": "inv-1", "invoice_number": "INV-2026-000001",
                            "customer_name": "Budi", "amount_idr": 500000, "line_items": "[]"}],
    )
    router = _build_router(pool)
    handler = _route(router, "/invoices", "POST")
    result = asyncio.run(handler(
        body=InvoiceCreateRequest(customer_name="Budi", amount_idr=500000),
        user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
    ))
    assert result["customer_name"] == "Budi"
    assert any("INSERT INTO audit_logs" in c[1] for c in pool.calls)


def test_run_task_route_delegates_to_task_engine_and_writes_audit_log(monkeypatch):
    captured = {}

    async def fake_run_agent_task(agent, goal, *, pool, org_id, bot_id=None, ctx=None):
        captured["goal"] = goal
        captured["org_id"] = org_id
        return {"status": "completed", "report": "ok"}

    import task_engine
    monkeypatch.setattr(task_engine, "run_agent_task", fake_run_agent_task)

    pool = FakePool()
    router = _build_router(pool)
    handler = _route(router, "/run-task", "POST")
    result = asyncio.run(handler(
        body=RunTaskRequest(goal="Cek invoice belum lunas"),
        user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
    ))
    assert result["status"] == "completed"
    assert captured["goal"] == "Cek invoice belum lunas"
    assert captured["org_id"] == "org-1"
    assert any("INSERT INTO audit_logs" in c[1] for c in pool.calls)


def test_update_invoice_status_rejects_invalid_status():
    pool = FakePool()
    router = _build_router(pool)
    handler = _route(router, "/invoices/{invoice_id}/status", "PATCH")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(
            invoice_id="inv-1", body=InvoiceStatusRequest(status="bogus"),
            user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
        ))
    assert exc.value.status_code == 422


def test_create_expense_route_writes_audit_log():
    pool = FakePool(fetchrow_results=[{"id": "exp-1", "category": "operasional", "amount_idr": 100000}])
    router = _build_router(pool)
    handler = _route(router, "/expenses", "POST")
    result = asyncio.run(handler(
        body=ExpenseCreateRequest(description="Listrik kantor", category="operasional", amount_idr=100000),
        user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
    ))
    assert result["category"] == "operasional"
    assert any("INSERT INTO audit_logs" in c[1] for c in pool.calls)
