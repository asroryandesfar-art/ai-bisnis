"""bn_platform/finance.py — Finance Center router (AI Workforce Phase 1).

Dashboard keuangan BISNIS TENANT sendiri: invoice, expense, payment, dan
laporan revenue/profit/cashflow/forecast. Semua endpoint org-scoped, RBAC-
gated (finance.read/finance.write/finance.approve), dan audit-logged --
mengikuti pola persis bn_platform/workflow_builder.py."""
import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import finance_agent as fa
from .security import _check_rate_limit, write_audit_log
from .agent_toggles import require_agent_enabled

GetPool = Callable[..., Awaitable[asyncpg.Pool]]
GetCurrentUser = Callable[..., Awaitable[dict]]


def _jsonb(value, default=None):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default if default is not None else []
    if value is None:
        return default if default is not None else []
    return value


def _invoice_out(row: dict) -> dict:
    out = dict(row)
    out["line_items"] = _jsonb(out.get("line_items"))
    return out


def _parse_period(period_days: int) -> tuple[datetime, datetime]:
    period_days = max(1, min(period_days, 365))
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=period_days)
    return start, end


class InvoiceCreateRequest(BaseModel):
    customer_name: str
    customer_contact: str | None = None
    amount_idr: int = Field(gt=0)
    due_date: datetime | None = None
    line_items: list[dict] = Field(default_factory=list)
    notes: str | None = None
    is_recurring: bool = False
    bot_id: str | None = None


class InvoiceStatusRequest(BaseModel):
    status: str


class PaymentCreateRequest(BaseModel):
    invoice_id: str | None = None
    amount_idr: int = Field(gt=0)
    method: str = "transfer"
    paid_at: datetime | None = None
    notes: str | None = None


class ExpenseCreateRequest(BaseModel):
    category: str = "lainnya"
    description: str
    amount_idr: int = Field(gt=0)
    expense_date: datetime | None = None


class ExpenseApprovalRequest(BaseModel):
    approve: bool


class ParseIntentRequest(BaseModel):
    text: str
    bot_id: str | None = None


class RunTaskRequest(BaseModel):
    goal: str
    bot_id: str | None = None


def build_finance_router(*, get_pool: GetPool, get_current_user: GetCurrentUser,
                          require_permission, get_agent_config: Callable[[], dict]) -> APIRouter:
    router = APIRouter(prefix="/finance", tags=["finance"])
    cfg = get_agent_config()
    agent = fa.FinanceAgent(api_key=cfg.get("api_key"), model=cfg.get("model"),
                             base_url=cfg.get("base_url"), deepseek_api_key=cfg.get("deepseek_api_key", ""), openrouter_api_key=cfg.get("openrouter_api_key", ""), app_url=cfg.get("app_url", "https://botnesia.id"))

    # ── Dashboard & reports ─────────────────────────────────────

    @router.get("/dashboard")
    async def dashboard(
        user: Annotated[dict, Depends(require_permission("finance.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        return await fa.dashboard_summary(pool, user["org_id"])

    @router.get("/reports/revenue")
    async def revenue_report(
        user: Annotated[dict, Depends(require_permission("finance.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        period_days: int = 30,
    ):
        start, end = _parse_period(period_days)
        return await fa.generate_revenue_report(pool, user["org_id"], start, end)

    @router.get("/reports/profit")
    async def profit_report(
        user: Annotated[dict, Depends(require_permission("finance.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        period_days: int = 30,
    ):
        start, end = _parse_period(period_days)
        return await fa.generate_profit_report(pool, user["org_id"], start, end)

    @router.get("/reports/cashflow")
    async def cashflow_report(
        user: Annotated[dict, Depends(require_permission("finance.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        period_days: int = 30,
    ):
        start, end = _parse_period(period_days)
        return await fa.generate_cashflow_report(pool, user["org_id"], start, end)

    @router.get("/reports/forecast")
    async def forecast_report(
        user: Annotated[dict, Depends(require_permission("finance.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        months_back: int = 3,
    ):
        return await fa.generate_forecast(pool, user["org_id"], months_back=max(1, min(months_back, 12)))

    @router.get("/reminders")
    async def payment_reminders(
        user: Annotated[dict, Depends(require_permission("finance.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        rows = await fa.list_payment_reminders(pool, user["org_id"])
        return {"reminders": [_invoice_out(r) for r in rows]}

    # ── Invoices ─────────────────────────────────────────────────

    @router.get("/invoices")
    async def list_invoices(
        user: Annotated[dict, Depends(require_permission("finance.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ):
        org_id = user["org_id"]
        limit = max(1, min(limit, 200))
        if status:
            rows = await pool.fetch(
                """SELECT * FROM finance_invoices WHERE org_id=$1 AND status=$2
                   ORDER BY created_at DESC LIMIT $3 OFFSET $4""",
                org_id, status, limit, offset,
            )
        else:
            rows = await pool.fetch(
                """SELECT * FROM finance_invoices WHERE org_id=$1
                   ORDER BY created_at DESC LIMIT $2 OFFSET $3""",
                org_id, limit, offset,
            )
        return {"invoices": [_invoice_out(dict(r)) for r in rows]}

    @router.post("/invoices", status_code=201)
    async def create_invoice_route(
        body: InvoiceCreateRequest,
        user: Annotated[dict, Depends(require_permission("finance.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        invoice = await fa.create_invoice(
            pool, org_id=org_id, bot_id=body.bot_id, customer_name=body.customer_name,
            customer_contact=body.customer_contact, amount_idr=body.amount_idr,
            due_date=body.due_date, line_items=body.line_items, notes=body.notes,
            is_recurring=body.is_recurring, created_by=user["id"],
        )
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="create", resource_type="finance_invoice", resource_id=invoice["id"],
            metadata={"customer_name": body.customer_name, "amount_idr": body.amount_idr},
        )
        return _invoice_out(invoice)

    @router.get("/invoices/{invoice_id}")
    async def get_invoice(
        invoice_id: str,
        user: Annotated[dict, Depends(require_permission("finance.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        row = await pool.fetchrow(
            "SELECT * FROM finance_invoices WHERE id=$1 AND org_id=$2", invoice_id, user["org_id"],
        )
        if not row:
            raise HTTPException(404, "Invoice tidak ditemukan")
        return _invoice_out(dict(row))

    @router.patch("/invoices/{invoice_id}/status")
    async def update_invoice_status(
        invoice_id: str,
        body: InvoiceStatusRequest,
        user: Annotated[dict, Depends(require_permission("finance.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        try:
            row = await fa.mark_invoice_status(pool, org_id=org_id, invoice_id=invoice_id, status=body.status)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if not row:
            raise HTTPException(404, "Invoice tidak ditemukan")
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="finance_invoice", resource_id=invoice_id,
            metadata={"status": body.status},
        )
        return _invoice_out(row)

    @router.delete("/invoices/{invoice_id}")
    async def delete_invoice(
        invoice_id: str,
        user: Annotated[dict, Depends(require_permission("finance.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        row = await pool.fetchrow(
            "SELECT id FROM finance_invoices WHERE id=$1 AND org_id=$2", invoice_id, org_id,
        )
        if not row:
            raise HTTPException(404, "Invoice tidak ditemukan")
        await pool.execute("DELETE FROM finance_invoices WHERE id=$1 AND org_id=$2", invoice_id, org_id)
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="delete", resource_type="finance_invoice", resource_id=invoice_id, metadata={},
        )
        return {"deleted": True}

    # ── Payments ─────────────────────────────────────────────────

    @router.get("/payments")
    async def list_payments(
        user: Annotated[dict, Depends(require_permission("finance.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        limit: int = 50,
    ):
        limit = max(1, min(limit, 200))
        rows = await pool.fetch(
            "SELECT * FROM finance_payments WHERE org_id=$1 ORDER BY paid_at DESC LIMIT $2",
            user["org_id"], limit,
        )
        return {"payments": [dict(r) for r in rows]}

    @router.post("/payments", status_code=201)
    async def create_payment_route(
        body: PaymentCreateRequest,
        user: Annotated[dict, Depends(require_permission("finance.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        if body.invoice_id:
            inv = await pool.fetchrow(
                "SELECT id FROM finance_invoices WHERE id=$1 AND org_id=$2", body.invoice_id, org_id,
            )
            if not inv:
                raise HTTPException(404, "Invoice tidak ditemukan")
        payment = await fa.record_payment(
            pool, org_id=org_id, invoice_id=body.invoice_id, amount_idr=body.amount_idr,
            method=body.method, paid_at=body.paid_at, notes=body.notes, created_by=user["id"],
        )
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="payment", resource_type="finance_payment", resource_id=payment["id"],
            metadata={"amount_idr": body.amount_idr, "method": body.method, "invoice_id": body.invoice_id},
        )
        return payment

    # ── Expenses ─────────────────────────────────────────────────

    @router.get("/expenses")
    async def list_expenses(
        user: Annotated[dict, Depends(require_permission("finance.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        status: str | None = None,
        limit: int = 50,
    ):
        org_id = user["org_id"]
        limit = max(1, min(limit, 200))
        if status:
            rows = await pool.fetch(
                """SELECT * FROM finance_expenses WHERE org_id=$1 AND status=$2
                   ORDER BY expense_date DESC LIMIT $3""",
                org_id, status, limit,
            )
        else:
            rows = await pool.fetch(
                "SELECT * FROM finance_expenses WHERE org_id=$1 ORDER BY expense_date DESC LIMIT $2",
                org_id, limit,
            )
        return {"expenses": [dict(r) for r in rows]}

    @router.post("/expenses", status_code=201)
    async def create_expense_route(
        body: ExpenseCreateRequest,
        user: Annotated[dict, Depends(require_permission("finance.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        expense = await fa.record_expense(
            pool, org_id=org_id, category=body.category, description=body.description,
            amount_idr=body.amount_idr, expense_date=body.expense_date, created_by=user["id"],
        )
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="create", resource_type="finance_expense", resource_id=expense["id"],
            metadata={"category": body.category, "amount_idr": body.amount_idr},
        )
        return expense

    @router.patch("/expenses/{expense_id}/approval")
    async def approve_expense_route(
        expense_id: str,
        body: ExpenseApprovalRequest,
        user: Annotated[dict, Depends(require_permission("finance.approve"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        row = await fa.approve_expense(pool, org_id=org_id, expense_id=expense_id,
                                        approve=body.approve, approver_id=user["id"])
        if not row:
            raise HTTPException(404, "Expense tidak ditemukan")
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="finance_expense", resource_id=expense_id,
            metadata={"approved": body.approve},
        )
        return row

    # ── AI parsing (Finance Agent NLP) ──────────────────────────
    # SENGAJA require_permission("finance.write") -- endpoint ini bisa
    # langsung membuat invoice/expense/payment dari teks bebas, jadi harus
    # setara hak akses dengan endpoint create manual. TIDAK pernah dipasang
    # di jalur chat publik/customer-facing (lihat docstring finance_agent.py).

    @router.post("/parse")
    async def parse_and_execute(
        body: ParseIntentRequest,
        user: Annotated[dict, Depends(require_permission("finance.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        result = await agent.safe_run({
            "user_message": body.text, "org_id": user["org_id"], "bot_id": body.bot_id,
            "pool": pool, "actor_user_id": user["id"],
        })
        if not result.success:
            raise HTTPException(422, result.error or "Tidak bisa memproses permintaan")
        await write_audit_log(
            pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
            action="create", resource_type="finance_ai_action",
            metadata={"intent": result.output.get("intent")},
        )
        return result.output

    # ── Task Engine: goal bebas multi-step lewat Finance Agent's tools ──
    # SENGAJA require_permission("finance.write") -- sama alasan dengan
    # /parse di atas. TIDAK dipasang di jalur chat publik.

    @router.post("/run-task")
    async def run_task(
        body: RunTaskRequest,
        user: Annotated[dict, Depends(require_permission("finance.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        await _check_rate_limit(f"finance-run-task:{user['org_id']}", 5)
        await require_agent_enabled(pool, str(user["org_id"]), "finance")
        result = await agent.run_task(body.goal, pool=pool, org_id=user["org_id"], bot_id=body.bot_id)
        await write_audit_log(
            pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
            action="create", resource_type="agent_task_execution",
            metadata={"goal": body.goal, "status": result.get("status")},
        )
        return result

    return router
