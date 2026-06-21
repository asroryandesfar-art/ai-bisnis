"""
agents/finance_agent.py — Finance Agent (AI Workforce Phase 1)

Mengelola KEUANGAN BISNIS TENANT sendiri (invoice ke pelanggan mereka,
expense, payment, dan laporan revenue/profit/cashflow/forecast) -- terpisah
total dari billing SaaS BotNesia (bn_platform/billing.py, tabel `invoices`
lama). Semua fungsi di bawah org-scoped dan dipakai bersama oleh:
  - bn_platform/finance.py (router dashboard Finance Center, RBAC-gated)
  - FinanceAgent.run() (ekstraksi niat dari bahasa natural, dipanggil HANYA
    dari endpoint terautentikasi -- TIDAK pernah dari chat publik/customer-
    facing, supaya end-user anonim tidak bisa memicu pembuatan invoice).
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg

from base import BaseAgent, AgentResult

CATEGORIES = {"operasional", "gaji", "marketing", "sewa", "lainnya"}
PAYMENT_METHODS = {"cash", "transfer", "qris", "other"}
INVOICE_STATUSES = {"draft", "sent", "paid", "overdue", "cancelled"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


_FINANCE_HINTS = re.compile(
    r"\b(invoice|faktur|tagihan|nota|expense|pengeluaran|biaya|profit|"
    r"untung|rugi|cashflow|arus\s*kas|revenue|pendapatan|omzet|forecast|"
    r"proyeksi\s*keuangan|laporan\s*keuangan)\b",
    re.IGNORECASE,
)


def looks_like_finance_request(text: str) -> bool:
    """Heuristik ringan (tanpa LLM) untuk deteksi niat finance. Dipakai sebagai
    sinyal opsional oleh permukaan INTERNAL (dashboard/staff tools) -- bukan
    dipasang sebagai gate otomatis di chat publik."""
    return bool(_FINANCE_HINTS.search(text or ""))


# ─── HELPER: NUMBERING & LEDGER ────────────────────────────────

async def _next_invoice_number(pool: asyncpg.Pool, org_id: str) -> str:
    year = _now().year
    count = await pool.fetchval(
        "SELECT COUNT(*) FROM finance_invoices WHERE org_id=$1 AND invoice_number LIKE $2",
        org_id, f"INV-{year}-%",
    )
    seq = int(count or 0) + 1
    return f"INV-{year}-{seq:06d}"


async def _write_ledger(pool: asyncpg.Pool, *, org_id: str, tx_type: str, category: str,
                         amount_idr: int, source_type: str, source_id: str | None,
                         description: str | None, occurred_at: datetime,
                         created_by: str | None) -> None:
    await pool.execute(
        """INSERT INTO finance_transactions
               (id, org_id, type, category, amount_idr, source_type, source_id,
                description, occurred_at, created_by)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
        str(uuid.uuid4()), org_id, tx_type, category, amount_idr, source_type,
        str(source_id) if source_id else None, description, occurred_at,
        str(created_by) if created_by else None,
    )


# ─── INVOICES ───────────────────────────────────────────────────

async def create_invoice(pool: asyncpg.Pool, *, org_id: str, bot_id: str | None,
                          customer_name: str, customer_contact: str | None,
                          amount_idr: int, due_date: datetime | None,
                          line_items: list[dict] | None, notes: str | None,
                          is_recurring: bool, created_by: str | None) -> dict:
    invoice_id = str(uuid.uuid4())
    invoice_number = await _next_invoice_number(pool, org_id)
    due = due_date or (_now() + timedelta(days=7))
    row = await pool.fetchrow(
        """INSERT INTO finance_invoices
               (id, org_id, bot_id, invoice_number, customer_name, customer_contact,
                amount_idr, line_items, notes, is_recurring, due_date, created_by)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10,$11,$12)
           RETURNING *""",
        invoice_id, org_id, bot_id, invoice_number, customer_name, customer_contact,
        amount_idr, json.dumps(line_items or []), notes, is_recurring, due,
        str(created_by) if created_by else None,
    )
    return dict(row)


async def mark_invoice_status(pool: asyncpg.Pool, *, org_id: str, invoice_id: str,
                               status: str) -> dict | None:
    if status not in INVOICE_STATUSES:
        raise ValueError(f"status tidak valid: {status}")
    extra_set = ""
    if status == "sent":
        extra_set = ", sent_at=NOW()"
    row = await pool.fetchrow(
        f"""UPDATE finance_invoices SET status=$1, updated_at=NOW(){extra_set}
            WHERE id=$2 AND org_id=$3 RETURNING *""",
        status, invoice_id, org_id,
    )
    return dict(row) if row else None


async def list_payment_reminders(pool: asyncpg.Pool, org_id: str) -> list[dict]:
    """Invoice yang jatuh tempo <=3 hari atau sudah lewat -- juga menandai
    status 'overdue' bagi yang sudah lewat due_date tapi belum dibayar."""
    await pool.execute(
        """UPDATE finance_invoices SET status='overdue', updated_at=NOW()
           WHERE org_id=$1 AND status='sent' AND due_date < NOW()""",
        org_id,
    )
    rows = await pool.fetch(
        """SELECT * FROM finance_invoices
           WHERE org_id=$1 AND status IN ('sent','overdue')
             AND due_date < NOW() + INTERVAL '3 days'
           ORDER BY due_date ASC""",
        org_id,
    )
    return [dict(r) for r in rows]


# ─── PAYMENTS ───────────────────────────────────────────────────

async def record_payment(pool: asyncpg.Pool, *, org_id: str, invoice_id: str | None,
                          amount_idr: int, method: str, paid_at: datetime | None,
                          notes: str | None, created_by: str | None) -> dict:
    if method not in PAYMENT_METHODS:
        method = "other"
    when = paid_at or _now()
    payment_id = str(uuid.uuid4())
    row = await pool.fetchrow(
        """INSERT INTO finance_payments
               (id, org_id, invoice_id, amount_idr, method, paid_at, notes, created_by)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING *""",
        payment_id, org_id, invoice_id, amount_idr, method, when, notes,
        str(created_by) if created_by else None,
    )
    invoice = None
    if invoice_id:
        invoice = await pool.fetchrow(
            """UPDATE finance_invoices SET status='paid', paid_at=$1, updated_at=NOW()
               WHERE id=$2 AND org_id=$3 RETURNING *""",
            when, invoice_id, org_id,
        )
    await _write_ledger(
        pool, org_id=org_id, tx_type="income", category="pembayaran",
        amount_idr=amount_idr, source_type="payment", source_id=payment_id,
        description=notes or (f"Pembayaran invoice {invoice['invoice_number']}" if invoice else "Pembayaran"),
        occurred_at=when, created_by=created_by,
    )
    out = dict(row)
    out["invoice"] = dict(invoice) if invoice else None
    return out


# ─── EXPENSES ───────────────────────────────────────────────────

async def record_expense(pool: asyncpg.Pool, *, org_id: str, category: str,
                          description: str, amount_idr: int,
                          expense_date: datetime | None, created_by: str | None) -> dict:
    if category not in CATEGORIES:
        category = "lainnya"
    when = expense_date or _now()
    expense_id = str(uuid.uuid4())
    row = await pool.fetchrow(
        """INSERT INTO finance_expenses
               (id, org_id, category, description, amount_idr, expense_date, created_by)
           VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *""",
        expense_id, org_id, category, description, amount_idr, when,
        str(created_by) if created_by else None,
    )
    await _write_ledger(
        pool, org_id=org_id, tx_type="expense", category=category,
        amount_idr=amount_idr, source_type="expense", source_id=expense_id,
        description=description, occurred_at=when, created_by=created_by,
    )
    return dict(row)


async def approve_expense(pool: asyncpg.Pool, *, org_id: str, expense_id: str,
                           approve: bool, approver_id: str | None) -> dict | None:
    status = "approved" if approve else "rejected"
    row = await pool.fetchrow(
        """UPDATE finance_expenses SET status=$1, approved_by=$2, approved_at=NOW()
           WHERE id=$3 AND org_id=$4 RETURNING *""",
        status, str(approver_id) if approver_id else None, expense_id, org_id,
    )
    return dict(row) if row else None


# ─── REPORTS ────────────────────────────────────────────────────

async def generate_revenue_report(pool: asyncpg.Pool, org_id: str,
                                   period_start: datetime, period_end: datetime) -> dict:
    row = await pool.fetchrow(
        """SELECT COALESCE(SUM(amount_idr), 0) AS total_idr, COUNT(*) AS tx_count
           FROM finance_transactions
           WHERE org_id=$1 AND type='income' AND occurred_at >= $2 AND occurred_at < $3""",
        org_id, period_start, period_end,
    )
    by_category = await pool.fetch(
        """SELECT category, COALESCE(SUM(amount_idr), 0) AS total_idr
           FROM finance_transactions
           WHERE org_id=$1 AND type='income' AND occurred_at >= $2 AND occurred_at < $3
           GROUP BY category ORDER BY total_idr DESC""",
        org_id, period_start, period_end,
    )
    return {
        "period_start": period_start.isoformat(), "period_end": period_end.isoformat(),
        "total_revenue_idr": int(row["total_idr"]), "transaction_count": int(row["tx_count"]),
        "by_category": [dict(r) for r in by_category],
    }


async def generate_profit_report(pool: asyncpg.Pool, org_id: str,
                                  period_start: datetime, period_end: datetime) -> dict:
    row = await pool.fetchrow(
        """SELECT
             COALESCE(SUM(amount_idr) FILTER (WHERE type='income'), 0)  AS income_idr,
             COALESCE(SUM(amount_idr) FILTER (WHERE type='expense'), 0) AS expense_idr
           FROM finance_transactions
           WHERE org_id=$1 AND occurred_at >= $2 AND occurred_at < $3""",
        org_id, period_start, period_end,
    )
    income = int(row["income_idr"])
    expense = int(row["expense_idr"])
    profit = income - expense
    margin = round((profit / income) * 100, 2) if income > 0 else 0.0
    return {
        "period_start": period_start.isoformat(), "period_end": period_end.isoformat(),
        "income_idr": income, "expense_idr": expense,
        "profit_idr": profit, "profit_margin_pct": margin,
    }


async def generate_cashflow_report(pool: asyncpg.Pool, org_id: str,
                                    period_start: datetime, period_end: datetime) -> dict:
    rows = await pool.fetch(
        """SELECT date_trunc('day', occurred_at) AS day,
                  COALESCE(SUM(amount_idr) FILTER (WHERE type='income'), 0)  AS inflow_idr,
                  COALESCE(SUM(amount_idr) FILTER (WHERE type='expense'), 0) AS outflow_idr
           FROM finance_transactions
           WHERE org_id=$1 AND occurred_at >= $2 AND occurred_at < $3
           GROUP BY day ORDER BY day ASC""",
        org_id, period_start, period_end,
    )
    buckets = []
    running_balance = 0
    for r in rows:
        net = int(r["inflow_idr"]) - int(r["outflow_idr"])
        running_balance += net
        buckets.append({
            "date": r["day"].date().isoformat(),
            "inflow_idr": int(r["inflow_idr"]), "outflow_idr": int(r["outflow_idr"]),
            "net_idr": net, "running_balance_idr": running_balance,
        })
    return {
        "period_start": period_start.isoformat(), "period_end": period_end.isoformat(),
        "daily": buckets, "ending_balance_idr": running_balance,
    }


async def generate_forecast(pool: asyncpg.Pool, org_id: str, months_back: int = 3) -> dict:
    """Forecast deterministik (rata-rata + tren linear sederhana dari N bulan
    terakhir) -- tidak butuh LLM, konsisten dengan revenue_intel.py yang juga
    laporan SQL murni."""
    rows = await pool.fetch(
        """SELECT date_trunc('month', occurred_at) AS month,
                  COALESCE(SUM(amount_idr) FILTER (WHERE type='income'), 0)  AS income_idr,
                  COALESCE(SUM(amount_idr) FILTER (WHERE type='expense'), 0) AS expense_idr
           FROM finance_transactions
           WHERE org_id=$1 AND occurred_at >= date_trunc('month', NOW()) - INTERVAL '1 month' * $2
           GROUP BY month ORDER BY month ASC""",
        org_id, months_back,
    )
    history = [{"month": r["month"].date().isoformat(),
                "income_idr": int(r["income_idr"]), "expense_idr": int(r["expense_idr"])} for r in rows]
    if not history:
        return {"history": [], "next_month_income_idr": 0, "next_month_expense_idr": 0, "trend": "insufficient_data"}

    incomes = [h["income_idr"] for h in history]
    expenses = [h["expense_idr"] for h in history]
    avg_income = sum(incomes) / len(incomes)
    avg_expense = sum(expenses) / len(expenses)
    if len(incomes) >= 2:
        delta_income = incomes[-1] - incomes[0]
        trend = "naik" if delta_income > 0 else ("turun" if delta_income < 0 else "stabil")
    else:
        trend = "insufficient_data"
    return {
        "history": history,
        "next_month_income_idr": round(avg_income),
        "next_month_expense_idr": round(avg_expense),
        "next_month_profit_idr": round(avg_income - avg_expense),
        "trend": trend,
    }


async def dashboard_summary(pool: asyncpg.Pool, org_id: str) -> dict:
    period_start = _now() - timedelta(days=30)
    period_end = _now()
    revenue = await pool.fetchrow(
        """SELECT
             COALESCE(SUM(amount_idr) FILTER (WHERE type='income'), 0)  AS revenue_idr,
             COALESCE(SUM(amount_idr) FILTER (WHERE type='income'), 0)
               - COALESCE(SUM(amount_idr) FILTER (WHERE type='expense'), 0) AS profit_idr
           FROM finance_transactions
           WHERE org_id=$1 AND occurred_at >= $2 AND occurred_at < $3""",
        org_id, period_start, period_end,
    )
    pending = await pool.fetchrow(
        """SELECT COUNT(*) AS cnt, COALESCE(SUM(amount_idr), 0) AS total_idr
           FROM finance_invoices WHERE org_id=$1 AND status IN ('sent','overdue')""",
        org_id,
    )
    overdue_count = await pool.fetchval(
        "SELECT COUNT(*) FROM finance_invoices WHERE org_id=$1 AND status='overdue'", org_id,
    )
    recurring_row = await pool.fetchrow(
        """SELECT COALESCE(SUM(amount_idr), 0) AS mrr_idr,
                  COUNT(*) FILTER (WHERE status='cancelled') AS cancelled_cnt,
                  COUNT(*) AS total_cnt
           FROM finance_invoices WHERE org_id=$1 AND is_recurring=TRUE""",
        org_id,
    )
    mrr = int(recurring_row["mrr_idr"])
    total_recurring = int(recurring_row["total_cnt"])
    churn_pct = round((recurring_row["cancelled_cnt"] / total_recurring) * 100, 2) if total_recurring > 0 else 0.0
    return {
        "revenue_30d_idr": int(revenue["revenue_idr"]),
        "profit_30d_idr": int(revenue["profit_idr"]),
        "pending_invoices_count": int(pending["cnt"]),
        "pending_invoices_amount_idr": int(pending["total_idr"]),
        "overdue_invoices_count": int(overdue_count or 0),
        "mrr_idr": mrr,
        "arr_idr": mrr * 12,
        "churn_pct": churn_pct,
    }


# ─── AGENT ──────────────────────────────────────────────────────

class FinanceAgent(BaseAgent):
    name = "finance_agent"
    system_prompt = """Kamu adalah Finance Agent dalam sistem multi-agent BotNesia (AI Workforce).

Tugas: ekstrak niat keuangan dari teks staf tenant (Bahasa Indonesia) menjadi
JSON terstruktur. Niat yang didukung:
  - create_invoice: butuh customer_name, amount_idr, due_date (ISO date, opsional), notes (opsional)
  - record_expense: butuh category (operasional|gaji|marketing|sewa|lainnya), description, amount_idr
  - record_payment: butuh amount_idr, method (cash|transfer|qris|other), notes (opsional)
  - query_report: butuh report_type (revenue|profit|cashflow|forecast)
  - unknown: jika tidak jelas

Balas HANYA JSON dengan field: action, dan field lain sesuai action di atas
(field yang tidak relevan boleh null). amount_idr harus angka bulat rupiah
tanpa titik/koma. Jangan menyertakan penjelasan di luar JSON."""

    async def parse_intent(self, text: str) -> dict:
        messages = [
            {"role": "system", "content": self.system_prompt + "\n\nOutput harus JSON."},
            {"role": "user", "content": text},
        ]
        return await self._call_llm_json(messages, temperature=0.1, default={"action": "unknown"})

    async def run(self, context: dict) -> AgentResult:
        """Hanya dipanggil dari permukaan TERAUTENTIKASI (lihat docstring modul).
        context wajib berisi: user_message, org_id, pool (asyncpg.Pool),
        actor_user_id. bot_id opsional."""
        user_message = context.get("user_message", "") or ""
        org_id = context.get("org_id")
        pool: asyncpg.Pool | None = context.get("pool") or context.get("_observability_pool")
        actor_user_id = context.get("actor_user_id")
        bot_id = context.get("bot_id")

        if not org_id or not pool:
            return AgentResult(agent=self.name, success=False, output={}, latency_ms=0,
                                error="org_id dan pool wajib diisi")

        intent = await self.parse_intent(user_message)
        action = intent.get("action", "unknown")
        output: dict = {"intent": intent}

        try:
            if action == "create_invoice" and intent.get("customer_name") and intent.get("amount_idr"):
                due = None
                if intent.get("due_date"):
                    try:
                        due = datetime.fromisoformat(intent["due_date"]).replace(tzinfo=timezone.utc)
                    except Exception:
                        due = None
                invoice = await create_invoice(
                    pool, org_id=org_id, bot_id=bot_id,
                    customer_name=intent["customer_name"], customer_contact=None,
                    amount_idr=int(intent["amount_idr"]), due_date=due,
                    line_items=None, notes=intent.get("notes"), is_recurring=False,
                    created_by=actor_user_id,
                )
                output["result"] = invoice
            elif action == "record_expense" and intent.get("description") and intent.get("amount_idr"):
                expense = await record_expense(
                    pool, org_id=org_id, category=intent.get("category") or "lainnya",
                    description=intent["description"], amount_idr=int(intent["amount_idr"]),
                    expense_date=None, created_by=actor_user_id,
                )
                output["result"] = expense
            elif action == "record_payment" and intent.get("amount_idr"):
                payment = await record_payment(
                    pool, org_id=org_id, invoice_id=intent.get("invoice_id"),
                    amount_idr=int(intent["amount_idr"]), method=intent.get("method") or "transfer",
                    paid_at=None, notes=intent.get("notes"), created_by=actor_user_id,
                )
                output["result"] = payment
            elif action == "query_report" and intent.get("report_type"):
                period_end = _now()
                period_start = period_end - timedelta(days=30)
                report_type = intent["report_type"]
                if report_type == "revenue":
                    output["result"] = await generate_revenue_report(pool, org_id, period_start, period_end)
                elif report_type == "profit":
                    output["result"] = await generate_profit_report(pool, org_id, period_start, period_end)
                elif report_type == "cashflow":
                    output["result"] = await generate_cashflow_report(pool, org_id, period_start, period_end)
                elif report_type == "forecast":
                    output["result"] = await generate_forecast(pool, org_id)
            else:
                return AgentResult(agent=self.name, success=False, output=output, latency_ms=0,
                                    error="Niat tidak dikenali atau data tidak lengkap")
        except Exception as exc:
            return AgentResult(agent=self.name, success=False, output=output, latency_ms=0, error=str(exc))

        # Memory: ingat aksi finance terakhir per staf (rule "semua agent harus
        # memiliki memory") -- reuse user_memory_profiles dgn bot_id sintetis
        # karena ini bukan profil end-customer CS, tapi catatan internal staf.
        try:
            from memory_agent import get_memory_store
            store = get_memory_store()
            await store.apply_fact_updates(
                user_id=str(actor_user_id) if actor_user_id else "unknown",
                org_id=str(org_id), bot_id=str(bot_id) if bot_id else "_finance_agent",
                facts_to_store=[{
                    "key": "last_finance_action",
                    "value": {"action": action, "at": _now().isoformat()},
                    "confidence": 1.0, "source": "explicit",
                }],
                forget_keys=[], pool=pool,
            )
        except Exception:
            pass  # memory tidak boleh menggagalkan aksi finance yang sudah berhasil

        return AgentResult(agent=self.name, success=True, output=output, latency_ms=0)
