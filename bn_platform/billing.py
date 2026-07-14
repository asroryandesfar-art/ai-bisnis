"""
bn_platform/billing.py — Subscription & Billing

Paket: Free, Starter, Pro, Business, Enterprise (lihat schema_platform.sql §2/§11
untuk definisi limit per paket — tabel `plans`). Mendukung dua payment gateway
populer di Indonesia:

  • Midtrans  — Snap API (redirect ke halaman pembayaran terhosting Midtrans)
    Docs: https://docs.midtrans.com/docs/snap-snap-integration-guide
  • Xendit    — Invoices API (redirect ke invoice page Xendit)
    Docs: https://developers.xendit.co/api-reference/#create-invoice

Alur checkout:
  1. POST /billing/checkout {plan_key, billing_cycle, provider}
       -> buat baris `invoices` (status=open) + panggil API provider
       -> simpan provider_invoice_id & provider_payment_url
       -> kembalikan redirect_url ke frontend
  2. User membayar di halaman provider
  3. Provider memanggil webhook kita (POST /billing/webhooks/{provider})
       -> verifikasi signature/token
       -> tandai invoice `paid`, catat di `payment_history`
       -> aktifkan/extend `subscriptions` (status=active, period+30/365 hari)
       -> dispatch_webhook(org_id, "subscription.activated", ...) ke klien

Enforcement limit paket dilakukan oleh `check_limit()` — dipanggil dari
endpoint pembuatan resource (bots, users, dokumen, channel) di main.py.
"""
# from __future__ import annotations  # dihapus: menyebabkan Depends(closure_var) gagal di-resolve oleh FastAPI get_type_hints()

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Awaitable, Callable

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from .config import cfg as platform_cfg
from .security import _check_rate_limit, _BILLING_MAX_REQUESTS, write_audit_log

logger = logging.getLogger("bn_platform.billing")

GetCurrentUser = Callable[..., Awaitable[dict]]
GetPool        = Callable[..., Awaitable[asyncpg.Pool]]
DispatchWebhook = Callable[..., Awaitable[None]]

MIDTRANS_SNAP_URL = (
    "https://app.midtrans.com/snap/v1/transactions"
    if platform_cfg.midtrans_is_production else
    "https://app.sandbox.midtrans.com/snap/v1/transactions"
)
XENDIT_INVOICE_URL = "https://api.xendit.co/v2/invoices"

# Limit field di tabel `plans` -> nama yang dipakai saat enforcement
LIMIT_FIELDS = {
    "conversations": "max_conversations_per_month",
    "agents":        "max_agents",
    "users":         "max_users",
    "knowledge":     "max_knowledge_docs",
    "channels":      "max_channels",
    "image_generations": "max_image_generations_per_month",
}


# ============================================================
# REPOSITORY
# ============================================================

async def get_plan_by_key(pool: asyncpg.Pool, key: str) -> dict | None:
    row = await pool.fetchrow("SELECT * FROM plans WHERE key=$1 AND is_active=TRUE", key)
    return dict(row) if row else None


async def list_plans(pool: asyncpg.Pool) -> list[dict]:
    rows = await pool.fetch("SELECT * FROM plans WHERE is_active=TRUE ORDER BY sort_order")
    return [dict(r) for r in rows]


async def get_active_subscription(pool: asyncpg.Pool, org_id: str) -> dict | None:
    row = await pool.fetchrow(
        """SELECT s.*, p.key AS plan_key, p.name AS plan_name,
                  p.max_conversations_per_month, p.max_agents, p.max_users,
                  p.max_knowledge_docs, p.max_channels, p.max_image_generations_per_month, p.features,
                  p.price_monthly_idr, p.price_yearly_idr
           FROM subscriptions s JOIN plans p ON p.id = s.plan_id
           WHERE s.org_id = $1""",
        org_id,
    )
    return dict(row) if row else None


def effective_price(sub: dict, billing_cycle: str) -> int:
    """Harga efektif yang ditagihkan ke tenant untuk siklus ini (grandfathering).

    Bila subscription punya harga terkunci (locked) untuk siklus tsb, itulah yang
    dibayar — walaupun admin sudah menaikkan harga live plan. Bila belum terkunci
    (NULL, mis. paket free/legacy), pakai harga live plan. `sub` diharapkan hasil
    get_active_subscription (punya kolom locked_* + price_*_idr dari JOIN plans).
    """
    if billing_cycle == "yearly":
        locked, live = sub.get("locked_price_yearly_idr"), sub.get("price_yearly_idr")
    else:
        locked, live = sub.get("locked_price_monthly_idr"), sub.get("price_monthly_idr")
    return int(locked if locked is not None else (live or 0))


def is_grandfathered(sub: dict, billing_cycle: str) -> bool:
    """True bila harga terkunci lebih murah dari harga live plan (pelanggan lama
    diuntungkan). Sama/lebih mahal → bukan grandfather (tak perlu badge)."""
    if billing_cycle == "yearly":
        locked, live = sub.get("locked_price_yearly_idr"), sub.get("price_yearly_idr")
    else:
        locked, live = sub.get("locked_price_monthly_idr"), sub.get("price_monthly_idr")
    return locked is not None and live is not None and int(locked) < int(live)


async def ensure_subscription(pool: asyncpg.Pool, org_id: str) -> dict:
    """Pastikan tenant punya baris subscription (auto-provision Free + trial saat baru daftar)."""
    sub = await get_active_subscription(pool, org_id)
    if sub:
        return sub
    free_plan = await get_plan_by_key(pool, "free")
    if not free_plan:
        raise RuntimeError("Plan 'free' tidak ditemukan — jalankan schema_platform.sql")
    trial_ends = datetime.now(timezone.utc) + timedelta(days=platform_cfg.trial_days)
    await pool.execute(
        """INSERT INTO subscriptions (org_id, plan_id, status, trial_ends_at,
                                      current_period_start, current_period_end)
           VALUES ($1, $2, 'trialing', $3, NOW(), $3)
           ON CONFLICT (org_id) DO NOTHING""",
        org_id, free_plan["id"], trial_ends,
    )
    return await get_active_subscription(pool, org_id)


async def current_usage(pool: asyncpg.Pool, org_id: str) -> dict:
    """Hitung pemakaian bulan berjalan untuk tiap dimensi limit."""
    row = await pool.fetchrow(
        """SELECT
             (SELECT COUNT(*) FROM conversations
                WHERE org_id=$1 AND started_at >= DATE_TRUNC('month', NOW()))      AS conversations,
             (SELECT COUNT(*) FROM bots WHERE org_id=$1 AND status != 'inactive')   AS agents,
             (SELECT COUNT(*) FROM users WHERE org_id=$1 AND is_active=TRUE)        AS users,
             (SELECT COUNT(*) FROM documents WHERE org_id=$1)                      AS knowledge,
             (SELECT COUNT(*) FROM channel_accounts WHERE org_id=$1 AND is_active)  AS channels,
             (SELECT COUNT(*) FROM image_generations
                WHERE org_id=$1 AND kind='generate' AND status='completed'
                  AND created_at >= DATE_TRUNC('month', NOW()))                    AS image_generations,
             -- P1-6: percakapan via WhatsApp bulan berjalan (eksposur biaya Meta
             -- pass-through). WA sudah memotong kuota yang sama; ini untuk
             -- VISIBILITAS biaya per-channel, bukan limit terpisah.
             (SELECT COUNT(*) FROM conversations
                WHERE org_id=$1 AND channel='whatsapp'
                  AND started_at >= DATE_TRUNC('month', NOW()))                    AS whatsapp_conversations
        """,
        org_id,
    )
    return dict(row)


async def check_limit(pool: asyncpg.Pool, org_id: str, dimension: str) -> tuple[bool, dict]:
    """
    Periksa apakah tenant masih di bawah limit paketnya untuk `dimension`
    (salah satu dari LIMIT_FIELDS keys). Return (allowed, detail).
    -1 pada kolom limit berarti unlimited (paket Enterprise).

    Dipanggil SEBELUM membuat resource baru, contoh di main.py:

        ok, detail = await check_limit(pool, org_id, "agents")
        if not ok:
            raise HTTPException(402, f"Limit paket '{detail['plan']}' tercapai ({detail['used']}/{detail['limit']})")
    """
    if dimension not in LIMIT_FIELDS:
        raise ValueError(f"Dimensi limit tidak dikenal: {dimension}")
    sub = await ensure_subscription(pool, org_id)
    limit_value = sub[LIMIT_FIELDS[dimension]]
    usage = await current_usage(pool, org_id)
    used = usage[dimension]
    detail = {"plan": sub["plan_key"], "dimension": dimension, "used": used, "limit": limit_value}
    if limit_value == -1:
        return True, detail
    return used < limit_value, detail


async def consume_conversation_quota(pool: asyncpg.Pool, org_id: str) -> tuple[bool, dict]:
    """P1-5 — kuota percakapan dengan OVERAGE PRABAYAR via saldo top-up.

    Urutan:
      1. Masih dalam kuota paket → izinkan (source='plan', tanpa debit).
      2. Lewat kuota TAPI ada saldo addon (top-up) → debit 1 percakapan dari
         saldo lalu izinkan (source='addon' = overage). Ini yang membuat top-up
         benar-benar TERPAKAI saat kuota habis (sebelumnya tidak pernah).
      3. Kuota paket habis DAN saldo addon 0 → tolak (source='exhausted').

    Dipanggil di jalur chat sebelum memproses percakapan (lihat bn_platform/chat.py).
    """
    ok, detail = await check_limit(pool, org_id, "conversations")
    if ok:
        detail["source"] = "plan"
        return True, detail
    addon = await get_addon_conversation_balance(pool, org_id)
    if addon > 0:
        await add_credits(
            pool, org_id=org_id, conversations=-1, amount_idr=0, kind="debit",
            description="Overage percakapan (dari saldo top-up)",
        )
        detail["source"] = "addon"
        detail["addon_remaining"] = addon - 1
        return True, detail
    detail["source"] = "exhausted"
    detail["addon_remaining"] = 0
    return False, detail


def _generate_invoice_number() -> str:
    now = datetime.now(timezone.utc)
    return f"INV-{now:%Y%m}-{uuid.uuid4().hex[:8].upper()}"


# ============================================================
# CREDIT LEDGER
# ============================================================

# Nominal top-up (P0-1 repricing): harga/percakapan SENGAJA di ATAS harga
# per-percakapan paket tertinggi (Starter = Rp99/percakapan) supaya top-up jadi
# solusi DARURAT overflow, bukan celah lebih murah dari kuota bawaan paket.
# Rp/percakapan turun sedikit seiring nominal (diskon volume) tapi tetap
# Rp125–143 — jauh di atas COGS (~Rp40) → margin ~70%+ dan mendorong upgrade,
# bukan cannibalisasi paket. Paket Rp25.000 lama dihapus (rugi & terlalu kecil).
TOPUP_PACKAGES = [
    {"amount_idr": 50_000,  "conversations": 350,   "label": "Rp50.000"},   # Rp142,9/percakapan
    {"amount_idr": 150_000, "conversations": 1_100, "label": "Rp150.000"},  # Rp136,4/percakapan
    {"amount_idr": 350_000, "conversations": 2_700, "label": "Rp350.000"},  # Rp129,6/percakapan
    {"amount_idr": 750_000, "conversations": 6_000, "label": "Rp750.000"},  # Rp125,0/percakapan
]

# Lookup: amount_idr → conversations
_TOPUP_CONV_MAP: dict = {p["amount_idr"]: p["conversations"] for p in TOPUP_PACKAGES}


async def get_addon_conversation_balance(pool: asyncpg.Pool, org_id: str) -> int:
    """Hitung sisa percakapan tambahan (addon) dari ledger."""
    val = await pool.fetchval(
        "SELECT COALESCE(SUM(conversations), 0) FROM credit_ledger WHERE org_id=$1",
        org_id,
    )
    return int(val or 0)


# Alias lama — backward compat
async def get_credit_balance(pool: asyncpg.Pool, org_id: str) -> int:
    return await get_addon_conversation_balance(pool, org_id)


async def add_credits(pool: asyncpg.Pool, *, org_id: str, conversations: int,
                      amount_idr: int, kind: str, description: str,
                      invoice_id: str | None = None,
                      credits: int = 0) -> dict:
    """Tambah atau kurangi addon conversation balance.

    conversations = jumlah percakapan (+N topup, -N debit).
    credits diabaikan (legacy field, tidak dipakai di UI).
    """
    row = await pool.fetchrow(
        """INSERT INTO credit_ledger
               (org_id, kind, amount_idr, credits, conversations, description, invoice_id)
           VALUES ($1, $2, $3, 0, $4, $5, $6) RETURNING *""",
        org_id, kind, amount_idr, conversations, description,
        uuid.UUID(invoice_id) if invoice_id else None,
    )
    await pool.execute(
        """INSERT INTO credit_balances (org_id, balance, updated_at)
           VALUES ($1, $2, NOW())
           ON CONFLICT (org_id) DO UPDATE SET
               balance = credit_balances.balance + $2,
               updated_at = NOW()""",
        org_id, conversations,
    )
    return dict(row)


def compute_invoice_tax(amount_idr: int) -> tuple[int, int, float]:
    """P2-9 — pecah total menjadi (DPP/subtotal, PPN, tarif).

    Harga tax-INCLUSIVE: total (amount_idr) tidak berubah; DPP = total/(1+tarif),
    PPN = total - DPP. Saat pajak nonaktif → (total, 0, 0.0) sehingga invoice
    lama/konteks non-PKP tetap konsisten. Tidak mengubah jumlah yang ditagih.
    """
    if not platform_cfg.tax_enabled or platform_cfg.tax_rate <= 0:
        return amount_idr, 0, 0.0
    rate = float(platform_cfg.tax_rate)
    subtotal = round(amount_idr / (1 + rate))
    tax = amount_idr - subtotal
    return subtotal, tax, rate


def tax_invoice_meta() -> dict:
    """Info penjual untuk header faktur pajak (dari config PKP)."""
    return {
        "tax_enabled": bool(platform_cfg.tax_enabled),
        "tax_rate": float(platform_cfg.tax_rate),
        "seller_name": platform_cfg.seller_name,
        "seller_npwp": platform_cfg.seller_npwp,
    }


async def create_invoice(
    pool: asyncpg.Pool, *, org_id: str, subscription_id: str | None,
    amount_idr: int, description: str, provider: str | None = None,
) -> dict:
    subtotal_idr, tax_idr, tax_rate = compute_invoice_tax(amount_idr)
    row = await pool.fetchrow(
        """INSERT INTO invoices (org_id, subscription_id, invoice_number, status,
                                 amount_idr, subtotal_idr, tax_idr, tax_rate,
                                 description, provider, due_date)
           VALUES ($1, $2, $3, 'open', $4, $5, $6, $7, $8, $9, $10)
           RETURNING *""",
        org_id, subscription_id, _generate_invoice_number(), amount_idr,
        subtotal_idr, tax_idr, tax_rate, description,
        provider, datetime.now(timezone.utc) + timedelta(days=platform_cfg.invoice_due_days),
    )
    return dict(row)


# ============================================================
# MIDTRANS — Snap API
# ============================================================

async def midtrans_create_transaction(*, order_id: str, amount_idr: int,
                                       customer_name: str, customer_email: str) -> dict:
    """
    Buat transaksi Snap. Mengembalikan {"token": ..., "redirect_url": ...}.
    Auth: HTTP Basic dengan server_key sebagai username, password kosong
    (lihat https://docs.midtrans.com/docs/snap-snap-integration-guide#1-get-snap-token).
    """
    if not platform_cfg.midtrans_server_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Midtrans belum dikonfigurasi (MIDTRANS_SERVER_KEY kosong)")

    payload = {
        "transaction_details": {"order_id": order_id, "gross_amount": amount_idr},
        "customer_details": {"first_name": customer_name or "Customer", "email": customer_email or ""},
        "credit_card": {"secure": True},
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            MIDTRANS_SNAP_URL, json=payload,
            auth=(platform_cfg.midtrans_server_key, ""),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
    if resp.status_code >= 400:
        logger.error("Midtrans create transaction gagal: %s %s", resp.status_code, resp.text[:500])
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Gagal membuat transaksi Midtrans")
    data = resp.json()
    return {"token": data.get("token"), "redirect_url": data.get("redirect_url")}


def midtrans_verify_signature(*, order_id: str, status_code: str, gross_amount: str, signature_key: str) -> bool:
    """
    Verifikasi signature notifikasi Midtrans:
      SHA512(order_id + status_code + gross_amount + server_key) == signature_key
    https://docs.midtrans.com/docs/https-notification-webhooks#notification-payload
    """
    if not platform_cfg.midtrans_server_key:
        return False
    raw = f"{order_id}{status_code}{gross_amount}{platform_cfg.midtrans_server_key}"
    expected = hashlib.sha512(raw.encode("utf-8")).hexdigest()
    return hmac.compare_digest(expected, signature_key or "")


# ============================================================
# XENDIT — Invoices API
# ============================================================

async def xendit_create_invoice(*, external_id: str, amount_idr: int,
                                 customer_name: str, customer_email: str,
                                 description: str) -> dict:
    """
    Buat invoice Xendit. Mengembalikan {"id": ..., "invoice_url": ...}.
    Auth: HTTP Basic dengan secret_key sebagai username, password kosong.
    https://developers.xendit.co/api-reference/#create-invoice
    """
    if not platform_cfg.xendit_secret_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Xendit belum dikonfigurasi (XENDIT_SECRET_KEY kosong)")

    payload = {
        "external_id": external_id,
        "amount": amount_idr,
        "currency": "IDR",
        "description": description,
        "customer": {"given_names": customer_name or "Customer", "email": customer_email or ""},
        "invoice_duration": platform_cfg.invoice_due_days * 24 * 3600,
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            XENDIT_INVOICE_URL, json=payload,
            auth=(platform_cfg.xendit_secret_key, ""),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
    if resp.status_code >= 400:
        logger.error("Xendit create invoice gagal: %s %s", resp.status_code, resp.text[:500])
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Gagal membuat invoice Xendit")
    data = resp.json()
    return {"id": data.get("id"), "invoice_url": data.get("invoice_url")}


def xendit_verify_callback_token(token: str | None) -> bool:
    """Bandingkan header `x-callback-token` dengan token yang dikonfigurasi di Xendit dashboard."""
    if not platform_cfg.xendit_callback_token:
        return False
    return hmac.compare_digest(platform_cfg.xendit_callback_token, token or "")


# ============================================================
# SUBSCRIPTION LIFECYCLE
# ============================================================

async def activate_subscription(pool: asyncpg.Pool, *, org_id: str, plan_key: str,
                                 billing_cycle: str = "monthly",
                                 is_free_trial: bool = False) -> dict:
    plan = await get_plan_by_key(pool, plan_key)
    if not plan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Plan '{plan_key}' tidak ditemukan")
    days = 365 if billing_cycle == "yearly" else 30
    period_end = datetime.now(timezone.utc) + timedelta(days=days)
    trial_ends = datetime.now(timezone.utc) + timedelta(days=30) if is_free_trial else None
    sub_status = "trialing" if is_free_trial else "active"
    # Grandfathering: kunci harga live plan saat aktivasi. Bila tetap di plan yang
    # sama (renewal), lock LAMA dipertahankan (COALESCE) supaya kenaikan harga
    # tidak menular ke pelanggan lama. Berpindah plan → kunci ulang harga baru.
    lock_monthly = int(plan["price_monthly_idr"])
    lock_yearly = int(plan["price_yearly_idr"])
    row = await pool.fetchrow(
        """INSERT INTO subscriptions (org_id, plan_id, status, billing_cycle,
                                      current_period_start, current_period_end,
                                      cancel_at_period_end, canceled_at, trial_ends_at,
                                      is_free_trial, locked_price_monthly_idr,
                                      locked_price_yearly_idr, price_locked_at)
           VALUES ($1, $2, $3, $4, NOW(), $5, FALSE, NULL, $6, $7, $8, $9, NOW())
           ON CONFLICT (org_id) DO UPDATE SET
               plan_id = EXCLUDED.plan_id,
               status = EXCLUDED.status,
               billing_cycle = EXCLUDED.billing_cycle,
               current_period_start = NOW(),
               current_period_end = EXCLUDED.current_period_end,
               cancel_at_period_end = FALSE,
               canceled_at = NULL,
               trial_ends_at = EXCLUDED.trial_ends_at,
               is_free_trial = EXCLUDED.is_free_trial,
               locked_price_monthly_idr = CASE
                   WHEN subscriptions.plan_id = EXCLUDED.plan_id
                   THEN COALESCE(subscriptions.locked_price_monthly_idr, EXCLUDED.locked_price_monthly_idr)
                   ELSE EXCLUDED.locked_price_monthly_idr END,
               locked_price_yearly_idr = CASE
                   WHEN subscriptions.plan_id = EXCLUDED.plan_id
                   THEN COALESCE(subscriptions.locked_price_yearly_idr, EXCLUDED.locked_price_yearly_idr)
                   ELSE EXCLUDED.locked_price_yearly_idr END,
               price_locked_at = CASE
                   WHEN subscriptions.plan_id = EXCLUDED.plan_id
                   THEN COALESCE(subscriptions.price_locked_at, EXCLUDED.price_locked_at)
                   ELSE EXCLUDED.price_locked_at END,
               updated_at = NOW()
           RETURNING *""",
        org_id, plan["id"], sub_status, billing_cycle, period_end, trial_ends,
        is_free_trial, lock_monthly, lock_yearly,
    )
    # sinkronkan kolom legacy organizations.plan agar fitur lama tetap konsisten
    legacy_plan = {"free": "starter", "starter": "starter", "pro": "growth",
                   "business": "scale", "enterprise": "scale"}.get(plan_key, "starter")
    await pool.execute(
        "UPDATE organizations SET plan=$1, billing_status='active' WHERE id=$2",
        legacy_plan, org_id,
    )
    return dict(row)


async def cancel_subscription(pool: asyncpg.Pool, *, org_id: str, at_period_end: bool = True) -> dict:
    if at_period_end:
        row = await pool.fetchrow(
            """UPDATE subscriptions SET cancel_at_period_end=TRUE, updated_at=NOW()
               WHERE org_id=$1 RETURNING *""", org_id,
        )
    else:
        row = await pool.fetchrow(
            """UPDATE subscriptions SET status='canceled', canceled_at=NOW(), updated_at=NOW()
               WHERE org_id=$1 RETURNING *""", org_id,
        )
        await pool.execute("UPDATE organizations SET billing_status='canceled' WHERE id=$1", org_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subscription tidak ditemukan")
    return dict(row)


async def _mark_invoice_paid(pool: asyncpg.Pool, invoice: dict, *, provider: str,
                             provider_tx_id: str | None, payment_method: str | None,
                             raw_payload: dict) -> None:
    await pool.execute(
        "UPDATE invoices SET status='paid', paid_at=NOW() WHERE id=$1", invoice["id"],
    )
    inserted = await pool.fetchval(
        """INSERT INTO payment_history (org_id, invoice_id, provider, provider_transaction_id,
                                        amount_idr, status, payment_method, raw_payload)
           VALUES ($1,$2,$3,$4,$5,'paid',$6,$7)
           ON CONFLICT (provider, provider_transaction_id) WHERE provider_transaction_id IS NOT NULL
           DO NOTHING
           RETURNING id""",
        invoice["org_id"], invoice["id"], provider, provider_tx_id,
        invoice["amount_idr"], payment_method, json.dumps(raw_payload or {}),
    )
    if inserted is None:
        # Provider sudah pernah kirim notifikasi paid dengan provider_transaction_id
        # yang sama (retry) -- payment_history sudah punya baris ini, jangan
        # aktivasi subscription/audit log dobel.
        return
    meta = invoice.get("metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except json.JSONDecodeError:
            meta = {}
    plan_key = meta.get("plan_key") if isinstance(meta, dict) else None
    cycle = (meta.get("billing_cycle") if isinstance(meta, dict) else None) or "monthly"
    if plan_key:
        await activate_subscription(pool, org_id=invoice["org_id"], plan_key=plan_key, billing_cycle=cycle)
    topup_amount = meta.get("topup_credits") if isinstance(meta, dict) else None
    if topup_amount and meta.get("kind") == "credit_topup":
        amount_idr = int(invoice["amount_idr"])
        conv_count = _TOPUP_CONV_MAP.get(amount_idr, 0)
        pkg = next((p for p in TOPUP_PACKAGES if p["amount_idr"] == amount_idr), None)
        label = pkg["label"] if pkg else f"Rp{amount_idr:,}".replace(",", ".")
        await add_credits(
            pool, org_id=invoice["org_id"],
            conversations=conv_count, amount_idr=amount_idr,
            kind="topup",
            description=f"Top Up Percakapan Tambahan {label}",
            invoice_id=str(invoice["id"]),
        )
    # Pembelian template marketplace berbayar → buat bot untuk pembeli + bagi
    # hasil publisher (pola sama seperti top-up; lazy import cegah circular).
    if isinstance(meta, dict) and meta.get("kind") == "marketplace_purchase":
        try:
            import bn_platform.marketplace as _mp
            await _mp.complete_marketplace_purchase(pool, invoice=invoice, meta=meta)
        except Exception:
            logger.exception("marketplace purchase completion failed inv=%s", invoice.get("id"))
    await pool.execute(
        """INSERT INTO audit_logs (org_id, action, resource_type, resource_id, metadata)
           VALUES ($1, 'payment', 'invoice', $2, $3)""",
        invoice["org_id"], str(invoice["id"]),
        json.dumps({"provider": provider, "amount_idr": int(invoice["amount_idr"]), "status": "paid"}),
    )


# ============================================================
# ROUTER
# ============================================================

class CheckoutReq(BaseModel):
    plan_key:      str
    billing_cycle: str = Field(default="monthly", pattern="^(monthly|yearly)$")
    provider:      str = Field(default="midtrans", pattern="^(midtrans|xendit|local)$")
    use_free_trial: bool = False


class TopupReq(BaseModel):
    amount_idr: int = Field(..., ge=50_000, le=750_000)
    provider:   str = Field(default="midtrans", pattern="^(midtrans|xendit|local)$")


class CancelReq(BaseModel):
    at_period_end: bool = True


def build_billing_router(*, get_pool: GetPool, get_current_user: GetCurrentUser,
                          require_permission, dispatch_webhook: DispatchWebhook | None = None) -> APIRouter:
    router = APIRouter(prefix="/billing", tags=["billing"])

    @router.get("/plans")
    async def get_plans(pool: Annotated[asyncpg.Pool, Depends(get_pool)]):
        # sales_email dipakai frontend untuk CTA "Hubungi Sales" (paket custom).
        return {"plans": await list_plans(pool), "sales_email": platform_cfg.sales_email}

    @router.get("/subscription")
    async def get_subscription(
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        sub = await ensure_subscription(pool, user["org_id"])
        usage = await current_usage(pool, user["org_id"])
        limits = {dim: sub[field] for dim, field in LIMIT_FIELDS.items()}
        cycle = sub.get("billing_cycle") or "monthly"
        # Grandfathering: harga efektif (locked bila ada) + harga live plan untuk
        # ditampilkan sebagai referensi (strikethrough) + flag badge di UI.
        sub = {
            **sub,
            "effective_price_monthly_idr": effective_price(sub, "monthly"),
            "effective_price_yearly_idr": effective_price(sub, "yearly"),
            "list_price_monthly_idr": int(sub.get("price_monthly_idr") or 0),
            "list_price_yearly_idr": int(sub.get("price_yearly_idr") or 0),
            "is_grandfathered": is_grandfathered(sub, cycle),
        }
        return {"subscription": sub, "usage": usage, "limits": limits}

    @router.get("/usage")
    async def get_usage(
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        results = {}
        for dim in LIMIT_FIELDS:
            ok, detail = await check_limit(pool, user["org_id"], dim)
            results[dim] = {**detail, "within_limit": ok}
        # P1-6: eksposur biaya per-channel (WhatsApp) — info, bukan limit.
        usage = await current_usage(pool, user["org_id"])
        return {
            "usage": results,
            "channel_usage": {"whatsapp": int(usage.get("whatsapp_conversations", 0))},
        }

    @router.post("/checkout", status_code=status.HTTP_201_CREATED)
    async def checkout(
        body: CheckoutReq,
        user: Annotated[dict, Depends(require_permission("billing.manage"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        _check_rate_limit(user["org_id"], _BILLING_MAX_REQUESTS)
        plan = await get_plan_by_key(pool, body.plan_key)
        if not plan:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Plan '{body.plan_key}' tidak ditemukan")
        # P0-4: paket custom/Enterprise TIDAK bisa checkout self-serve — harus
        # lewat sales (harga dinegosiasikan). Guard defense-in-depth walau UI
        # sudah mengarahkan ke "Hubungi Sales".
        _feat = plan.get("features")
        if isinstance(_feat, str):
            try:
                _feat = json.loads(_feat)
            except Exception:
                _feat = {}
        if body.plan_key == "enterprise" or bool((_feat or {}).get("custom_pricing")):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Paket '{plan['name']}' memerlukan konsultasi tim sales "
                f"(harga custom). Hubungi {platform_cfg.sales_email}.",
            )
        # Grandfathering: bila tenant memperpanjang plan yang SAMA dan sudah punya
        # harga terkunci, tagih harga locked (bukan harga baru yang lebih mahal).
        # Ganti plan → tagih harga live plan tujuan.
        current_sub = await get_active_subscription(pool, user["org_id"])
        if current_sub and current_sub.get("plan_key") == body.plan_key:
            amount = effective_price(current_sub, body.billing_cycle)
        else:
            amount = plan["price_yearly_idr"] if body.billing_cycle == "yearly" else plan["price_monthly_idr"]

        # Free trial: plan berbayar + eligible + user meminta trial
        use_trial = (
            body.use_free_trial
            and bool(plan.get("free_trial_eligible"))
            and body.plan_key != "enterprise"
            and amount > 0
        )
        if use_trial:
            # Cek apakah org ini sudah pernah trial sebelumnya
            had_trial = await pool.fetchval(
                "SELECT COUNT(*) FROM subscriptions WHERE org_id=$1 AND is_free_trial=TRUE",
                user["org_id"],
            )
            if had_trial:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Free trial 1 bulan hanya berlaku sekali. Akun Anda sudah pernah menggunakan trial.",
                )
            sub = await activate_subscription(
                pool, org_id=user["org_id"], plan_key=body.plan_key,
                billing_cycle=body.billing_cycle, is_free_trial=True,
            )
            await write_audit_log(
                pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
                action="plan_change", resource_type="subscription", resource_id=str(sub["id"]),
                metadata={"plan_key": body.plan_key, "billing_cycle": body.billing_cycle,
                          "requires_payment": False, "free_trial": True},
            )
            return {"requires_payment": False, "free_trial": True, "subscription": sub}

        if amount <= 0:
            # Plan gratis: aktifkan langsung tanpa proses pembayaran
            sub = await activate_subscription(pool, org_id=user["org_id"], plan_key=body.plan_key,
                                               billing_cycle=body.billing_cycle)
            await write_audit_log(
                pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
                action="plan_change", resource_type="subscription", resource_id=str(sub["id"]),
                metadata={"plan_key": body.plan_key, "billing_cycle": body.billing_cycle, "requires_payment": False},
            )
            return {"requires_payment": False, "subscription": sub}

        sub = await ensure_subscription(pool, user["org_id"])
        invoice = await create_invoice(
            pool, org_id=user["org_id"], subscription_id=sub["id"], amount_idr=amount,
            description=f"Upgrade ke paket {plan['name']} ({body.billing_cycle})",
            provider=("manual" if body.provider == "local" else body.provider),
        )
        await pool.execute(
            "UPDATE invoices SET metadata = metadata || $2::jsonb WHERE id=$1",
            invoice["id"], json.dumps({"plan_key": body.plan_key, "billing_cycle": body.billing_cycle}),
        )

        org = await pool.fetchrow("SELECT name FROM organizations WHERE id=$1", user["org_id"])
        customer_name = (org["name"] if org else None) or user.get("full_name") or "Customer"
        customer_email = user.get("email") or ""

        if body.provider == "local":
            if not platform_cfg.local_billing_enabled:
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Billing lokal dinonaktifkan")
            # Sama seperti webhook Midtrans/Xendit: bungkus update invoice ->
            # payment_history -> activate_subscription -> audit log dalam satu
            # transaction supaya atomik. Kalau salah satu langkah gagal di
            # tengah (mis. activate_subscription raise), tidak ada state
            # setengah-jadi (invoice ke-mark paid tapi subscription belum aktif).
            async with pool.acquire() as conn:
                async with conn.transaction():
                    invoice = dict(await conn.fetchrow(
                        "SELECT * FROM invoices WHERE id=$1 FOR UPDATE", invoice["id"],
                    ))
                    await _mark_invoice_paid(
                        conn, invoice, provider="manual",
                        provider_tx_id=f"local-{invoice['invoice_number']}",
                        payment_method="local-development",
                        raw_payload={"mode": "local", "approved_by": user.get("email")},
                    )
            return {
                "requires_payment": False,
                "local": True,
                "invoice_id": str(invoice["id"]),
                "invoice_number": invoice["invoice_number"],
                "subscription": await get_active_subscription(pool, user["org_id"]),
            }

        if body.provider == "midtrans":
            result = await midtrans_create_transaction(
                order_id=invoice["invoice_number"], amount_idr=amount,
                customer_name=customer_name, customer_email=customer_email,
            )
            redirect_url = result["redirect_url"]
            provider_id = invoice["invoice_number"]
        else:
            result = await xendit_create_invoice(
                external_id=invoice["invoice_number"], amount_idr=amount,
                customer_name=customer_name, customer_email=customer_email,
                description=invoice["description"],
            )
            redirect_url = result["invoice_url"]
            provider_id = result["id"]

        await pool.execute(
            "UPDATE invoices SET provider_invoice_id=$1, provider_payment_url=$2 WHERE id=$3",
            provider_id, redirect_url, invoice["id"],
        )
        return {
            "requires_payment": True,
            "invoice_id": str(invoice["id"]),
            "invoice_number": invoice["invoice_number"],
            "amount_idr": amount,
            "provider": body.provider,
            "redirect_url": redirect_url,
        }

    @router.post("/cancel")
    async def cancel(
        body: CancelReq,
        user: Annotated[dict, Depends(require_permission("billing.manage"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        sub = await cancel_subscription(pool, org_id=user["org_id"], at_period_end=body.at_period_end)
        await write_audit_log(
            pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
            action="plan_change", resource_type="subscription", resource_id=str(sub["id"]),
            metadata={"at_period_end": body.at_period_end, "status": sub["status"]},
        )
        return {"subscription": sub}

    @router.get("/invoices")
    async def list_invoices(
        user: Annotated[dict, Depends(require_permission("billing.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        limit: int = 20, offset: int = 0,
    ):
        rows = await pool.fetch(
            """SELECT id, invoice_number, status, amount_idr, subtotal_idr, tax_idr,
                      tax_rate, currency, description, provider, provider_payment_url,
                      due_date, paid_at, created_at
               FROM invoices WHERE org_id=$1 ORDER BY created_at DESC LIMIT $2 OFFSET $3""",
            user["org_id"], limit, offset,
        )
        return {"invoices": [dict(r) for r in rows], "tax": tax_invoice_meta()}

    @router.get("/invoices/by-number/{invoice_number}")
    async def get_invoice_by_number(
        invoice_number: str,
        user: Annotated[dict, Depends(require_permission("billing.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        """Status invoice untuk halaman redirect pembayaran (Midtrans/Xendit finish-URL).
        Sumber kebenaran tetap kolom `status` di DB, yang HANYA diubah oleh webhook
        provider (`midtrans_webhook`/`xendit_webhook`) — endpoint ini cuma membaca,
        tidak pernah menerima/mempercayai status dari query param redirect."""
        row = await pool.fetchrow(
            """SELECT id, invoice_number, status, amount_idr, currency, description,
                      provider, paid_at, created_at
               FROM invoices WHERE invoice_number=$1 AND org_id=$2""",
            invoice_number, user["org_id"],
        )
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice tidak ditemukan")
        return {"invoice": dict(row)}

    @router.get("/payments")
    async def list_payments(
        user: Annotated[dict, Depends(require_permission("billing.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        limit: int = 20, offset: int = 0,
    ):
        rows = await pool.fetch(
            """SELECT id, invoice_id, provider, provider_transaction_id, amount_idr,
                      status, payment_method, received_at
               FROM payment_history WHERE org_id=$1 ORDER BY received_at DESC LIMIT $2 OFFSET $3""",
            user["org_id"], limit, offset,
        )
        return {"payments": [dict(r) for r in rows]}

    @router.get("/credits")
    async def get_credits(
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        balance = await get_addon_conversation_balance(pool, user["org_id"])
        rows = await pool.fetch(
            """SELECT id, kind, amount_idr, conversations, description, created_at
               FROM credit_ledger WHERE org_id=$1 ORDER BY created_at DESC LIMIT 20""",
            user["org_id"],
        )
        return {
            "addon_conversation_balance": balance,
            "topup_packages": TOPUP_PACKAGES,
            "history": [dict(r) for r in rows],
        }

    @router.post("/credits/topup", status_code=status.HTTP_201_CREATED)
    async def topup_credits(
        body: TopupReq,
        user: Annotated[dict, Depends(require_permission("billing.manage"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        _check_rate_limit(user["org_id"], _BILLING_MAX_REQUESTS)
        valid_amounts = {p["amount_idr"] for p in TOPUP_PACKAGES}
        if body.amount_idr not in valid_amounts:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Nominal top-up tidak valid. Pilihan: {sorted(valid_amounts)}",
            )
        conv_count = _TOPUP_CONV_MAP[body.amount_idr]
        pkg = next(p for p in TOPUP_PACKAGES if p["amount_idr"] == body.amount_idr)
        sub = await ensure_subscription(pool, user["org_id"])
        invoice = await create_invoice(
            pool, org_id=user["org_id"], subscription_id=sub["id"],
            amount_idr=body.amount_idr,
            description=f"Top Up Percakapan Tambahan {pkg['label']}",
            provider=("manual" if body.provider == "local" else body.provider),
        )
        await pool.execute(
            "UPDATE invoices SET metadata = metadata || $2::jsonb WHERE id=$1",
            invoice["id"], json.dumps({"topup_credits": body.amount_idr, "kind": "credit_topup"}),
        )

        org = await pool.fetchrow("SELECT name FROM organizations WHERE id=$1", user["org_id"])
        customer_name = (org["name"] if org else None) or user.get("full_name") or "Customer"
        customer_email = user.get("email") or ""

        if body.provider == "local":
            if not platform_cfg.local_billing_enabled:
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Billing lokal dinonaktifkan")
            async with pool.acquire() as conn:
                async with conn.transaction():
                    inv = dict(await conn.fetchrow(
                        "SELECT * FROM invoices WHERE id=$1 FOR UPDATE", invoice["id"],
                    ))
                    await _mark_invoice_paid(
                        conn, inv, provider="manual",
                        provider_tx_id=f"local-{inv['invoice_number']}",
                        payment_method="local-development",
                        raw_payload={"mode": "local", "approved_by": user.get("email")},
                    )
                    await add_credits(
                        conn, org_id=user["org_id"], conversations=conv_count,
                        amount_idr=body.amount_idr, kind="topup",
                        description=f"Top Up Percakapan Tambahan {pkg['label']} (lokal)",
                        invoice_id=str(invoice["id"]),
                    )
            return {
                "requires_payment": False,
                "local": True,
                "conversations_added": conv_count,
                "addon_conversation_balance": await get_addon_conversation_balance(pool, user["org_id"]),
                "invoice_id": str(invoice["id"]),
            }

        if body.provider == "midtrans":
            result = await midtrans_create_transaction(
                order_id=invoice["invoice_number"], amount_idr=body.amount_idr,
                customer_name=customer_name, customer_email=customer_email,
            )
            redirect_url = result["redirect_url"]
            provider_id = invoice["invoice_number"]
        else:
            result = await xendit_create_invoice(
                external_id=invoice["invoice_number"], amount_idr=body.amount_idr,
                customer_name=customer_name, customer_email=customer_email,
                description=invoice["description"],
            )
            redirect_url = result["invoice_url"]
            provider_id = result["id"]

        await pool.execute(
            "UPDATE invoices SET provider_invoice_id=$1, provider_payment_url=$2 WHERE id=$3",
            provider_id, redirect_url, invoice["id"],
        )
        return {
            "requires_payment": True,
            "invoice_id": str(invoice["id"]),
            "invoice_number": invoice["invoice_number"],
            "amount_idr": body.amount_idr,
            "conversations_pending": conv_count,
            "provider": body.provider,
            "redirect_url": redirect_url,
        }

    # ── Webhook: Midtrans HTTP Notification ────────────────────
    @router.post("/webhooks/midtrans", include_in_schema=False)
    async def midtrans_webhook(request: Request, pool: Annotated[asyncpg.Pool, Depends(get_pool)]):
        payload = await request.json()
        order_id     = str(payload.get("order_id", ""))
        status_code  = str(payload.get("status_code", ""))
        gross_amount = str(payload.get("gross_amount", ""))
        signature    = str(payload.get("signature_key", ""))
        transaction_status = payload.get("transaction_status")

        if not midtrans_verify_signature(order_id=order_id, status_code=status_code,
                                          gross_amount=gross_amount, signature_key=signature):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Signature tidak valid")

        just_paid = False
        async with pool.acquire() as conn:
            async with conn.transaction():
                # FOR UPDATE mengunci baris invoice sampai transaksi ini commit --
                # notifikasi retry Midtrans yang datang bersamaan akan menunggu di
                # sini, lalu melihat status sudah 'paid' dan tidak mengaktivasi
                # subscription dua kali (sebelumnya invoice di-SELECT tanpa lock,
                # jadi dua request bisa lolos cek status='paid' bersamaan).
                invoice = await conn.fetchrow(
                    "SELECT * FROM invoices WHERE invoice_number=$1 FOR UPDATE", order_id,
                )
                if not invoice:
                    return {"ok": True, "note": "invoice tidak ditemukan, diabaikan"}
                invoice = dict(invoice)

                if transaction_status in ("settlement", "capture") and invoice["status"] != "paid":
                    await _mark_invoice_paid(
                        conn, invoice, provider="midtrans",
                        provider_tx_id=str(payload.get("transaction_id", "")),
                        payment_method=payload.get("payment_type"),
                        raw_payload=payload,
                    )
                    just_paid = True
                elif transaction_status in ("expire", "cancel", "deny"):
                    await conn.execute("UPDATE invoices SET status='void', voided_at=NOW() WHERE id=$1", invoice["id"])
        if just_paid and dispatch_webhook:
            await dispatch_webhook(invoice["org_id"], "subscription.activated",
                                   {"invoice_number": order_id, "provider": "midtrans"}, pool)
        return {"ok": True}

    # ── Webhook: Xendit Invoice Callback ────────────────────────
    @router.post("/webhooks/xendit", include_in_schema=False)
    async def xendit_webhook(request: Request, pool: Annotated[asyncpg.Pool, Depends(get_pool)]):
        token = request.headers.get("x-callback-token")
        if not xendit_verify_callback_token(token):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Callback token tidak valid")

        payload = await request.json()
        external_id = str(payload.get("external_id", ""))
        xendit_status = str(payload.get("status", "")).upper()

        just_paid = False
        async with pool.acquire() as conn:
            async with conn.transaction():
                invoice = await conn.fetchrow(
                    "SELECT * FROM invoices WHERE invoice_number=$1 FOR UPDATE", external_id,
                )
                if not invoice:
                    return {"ok": True, "note": "invoice tidak ditemukan, diabaikan"}
                invoice = dict(invoice)

                if xendit_status == "PAID" and invoice["status"] != "paid":
                    await _mark_invoice_paid(
                        conn, invoice, provider="xendit",
                        provider_tx_id=str(payload.get("id", "")),
                        payment_method=payload.get("payment_method") or payload.get("payment_channel"),
                        raw_payload=payload,
                    )
                    just_paid = True
                elif xendit_status in ("EXPIRED", "FAILED"):
                    await conn.execute("UPDATE invoices SET status='void', voided_at=NOW() WHERE id=$1", invoice["id"])
        if just_paid and dispatch_webhook:
            await dispatch_webhook(invoice["org_id"], "subscription.activated",
                                   {"invoice_number": external_id, "provider": "xendit"}, pool)
        return {"ok": True}

    return router
