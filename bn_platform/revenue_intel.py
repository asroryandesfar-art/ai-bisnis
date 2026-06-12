"""
bn_platform/revenue_intel.py — Revenue Intelligence

Menghitung metrik bisnis inti SaaS dari data subscriptions/invoices/payment_history
yang sudah ada (lihat schema_platform.sql §2 & §8):

  MRR  — Monthly Recurring Revenue: total nilai langganan aktif dinormalisasi/bulan
  ARR  — Annual Recurring Revenue: MRR × 12
  Churn rate — proporsi pelanggan yang berhenti berlangganan dalam periode
  LTV  — Lifetime Value: ARPU ÷ churn rate (formula SaaS standar)
  CAC  — Customer Acquisition Cost: biaya marketing ÷ pelanggan baru pada periode
  Proyeksi pertumbuhan — regresi linear sederhana atas snapshot MRR historis

CATATAN AKSES: metrik ini adalah business intelligence milik OPERATOR PLATFORM
(BotNesia sendiri), BUKAN data per-tenant — karena itu endpoint di-gate dengan
`_require_platform_admin` (allowlist email via PLATFORM_ADMIN_EMAILS di .env)
alih-alih RBAC tenant biasa. Ganti dengan mekanisme superadmin yang lebih kuat
(role terpisah/SSO internal) sebelum go-to-market besar — lihat ARCHITECTURE.md §10.

Snapshot harian disimpan ke `revenue_snapshots` (org_id NULL = agregat platform)
agar tren bisa divisualisasikan tanpa menghitung ulang dari nol setiap saat.
"""
# from __future__ import annotations  # dihapus: menyebabkan Depends(closure_var) gagal di-resolve oleh FastAPI get_type_hints()

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status

from .config import cfg

logger = logging.getLogger("bn_platform.revenue_intel")

GetCurrentUser = Callable[..., Awaitable[dict]]
GetPool        = Callable[..., Awaitable[asyncpg.Pool]]

_ADMIN_EMAILS = {e.strip().lower() for e in cfg.platform_admin_emails.split(",") if e.strip()}
_MARKETING_SPEND_IDR = cfg.monthly_marketing_spend_idr


def _require_platform_admin(user: dict) -> None:
    email = (user.get("email") or "").lower()
    if not _ADMIN_EMAILS:
        logger.error("PLATFORM_ADMIN_EMAILS belum diset — Revenue Intelligence dinonaktifkan")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Revenue Intelligence belum dikonfigurasi.")
    if email not in _ADMIN_EMAILS:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Endpoint ini khusus operator platform.")


# ============================================================
# KALKULASI METRIK
# ============================================================

async def compute_mrr(pool: asyncpg.Pool) -> dict:
    row = await pool.fetchrow(
        """SELECT
             COUNT(*)                                                                        AS active_count,
             COALESCE(SUM(
               CASE WHEN s.billing_cycle = 'yearly'
                    THEN p.price_yearly_idr / 12.0
                    ELSE p.price_monthly_idr
               END), 0)                                                                      AS mrr_idr
           FROM subscriptions s JOIN plans p ON p.id = s.plan_id
           WHERE s.status = 'active'""",
    )
    mrr = float(row["mrr_idr"] or 0)
    return {"mrr_idr": round(mrr), "arr_idr": round(mrr * 12), "active_subscriptions": int(row["active_count"])}


async def compute_churn(pool: asyncpg.Pool, *, period_days: int = 30) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=period_days)
    row = await pool.fetchrow(
        """SELECT
             COUNT(*) FILTER (WHERE status = 'active')                                    AS active_now,
             COUNT(*) FILTER (WHERE status = 'canceled' AND canceled_at >= $1)            AS canceled_in_period,
             COUNT(*) FILTER (WHERE created_at >= $1 AND status != 'trialing')            AS new_in_period
           FROM subscriptions""",
        since,
    )
    active_now  = int(row["active_now"])
    canceled    = int(row["canceled_in_period"])
    new_subs    = int(row["new_in_period"])
    base        = active_now + canceled   # estimasi populasi awal periode
    churn_rate  = round(canceled / base, 4) if base > 0 else 0.0
    return {
        "period_days": period_days, "active_subscriptions": active_now,
        "canceled_in_period": canceled, "new_in_period": new_subs, "churn_rate": churn_rate,
    }


def compute_ltv(*, mrr_idr: float, active_subscriptions: int, churn_rate: float) -> int:
    """LTV = ARPU / churn_rate (formula SaaS standar; churn_rate bulanan)."""
    if active_subscriptions <= 0:
        return 0
    arpu = mrr_idr / active_subscriptions
    if churn_rate <= 0:
        # tanpa churn teramati: estimasi konservatif horizon 36 bulan
        return round(arpu * 36)
    return round(arpu / churn_rate)


def compute_cac(*, new_customers: int, marketing_spend_idr: int | None = None) -> int:
    """CAC = total biaya akuisisi ÷ jumlah pelanggan baru pada periode.
    `marketing_spend_idr` idealnya diintegrasikan dari sistem ads/marketing —
    untuk saat ini dibaca dari konfigurasi MONTHLY_MARKETING_SPEND_IDR (.env)
    atau dioper manual lewat parameter endpoint."""
    spend = _MARKETING_SPEND_IDR if marketing_spend_idr is None else marketing_spend_idr
    if new_customers <= 0:
        return spend
    return round(spend / new_customers)


def _linear_projection(points: list[tuple[int, float]], horizon_days: int) -> float:
    """Regresi linear sederhana (least squares) — proyeksi nilai `horizon_days` ke depan.
    `points`: list of (day_index, value). Tanpa numpy supaya tidak menambah dependency baru."""
    n = len(points)
    if n < 2:
        return points[-1][1] if points else 0.0
    sum_x  = sum(p[0] for p in points)
    sum_y  = sum(p[1] for p in points)
    sum_xy = sum(p[0] * p[1] for p in points)
    sum_xx = sum(p[0] * p[0] for p in points)
    denom = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return sum_y / n
    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    next_x = points[-1][0] + horizon_days
    return slope * next_x + intercept


async def project_mrr_growth(pool: asyncpg.Pool, *, lookback_days: int = 30, horizon_days: int = 30) -> dict:
    rows = await pool.fetch(
        """SELECT snapshot_date, mrr_idr FROM revenue_snapshots
           WHERE org_id IS NULL AND snapshot_date >= CURRENT_DATE - $1::int
           ORDER BY snapshot_date ASC""",
        lookback_days,
    )
    if len(rows) < 2:
        current = await compute_mrr(pool)
        return {
            "method": "insufficient_history", "lookback_days": lookback_days,
            "horizon_days": horizon_days, "current_mrr_idr": current["mrr_idr"],
            "projected_mrr_idr": current["mrr_idr"],
            "note": "Belum cukup snapshot historis (minimal 2 hari) untuk proyeksi tren — jalankan POST /revenue/snapshot/run setiap hari.",
        }
    base_date = rows[0]["snapshot_date"]
    points = [((r["snapshot_date"] - base_date).days, float(r["mrr_idr"])) for r in rows]
    projected = max(0.0, _linear_projection(points, horizon_days))
    current_mrr = points[-1][1]
    growth_pct = round(((projected - current_mrr) / current_mrr) * 100, 2) if current_mrr > 0 else 0.0
    return {
        "method": "linear_trend", "lookback_days": lookback_days, "horizon_days": horizon_days,
        "current_mrr_idr": round(current_mrr), "projected_mrr_idr": round(projected),
        "projected_growth_pct": growth_pct,
    }


async def generate_snapshot(pool: asyncpg.Pool, *, snapshot_date: date | None = None) -> dict:
    """Hitung & simpan snapshot harian metrik platform-wide (org_id NULL)."""
    snap_date = snapshot_date or datetime.now(timezone.utc).date()
    mrr_data   = await compute_mrr(pool)
    churn_data = await compute_churn(pool, period_days=30)
    ltv = compute_ltv(mrr_idr=mrr_data["mrr_idr"], active_subscriptions=mrr_data["active_subscriptions"],
                      churn_rate=churn_data["churn_rate"])
    cac = compute_cac(new_customers=churn_data["new_in_period"])
    projection = await project_mrr_growth(pool)

    raw_metrics_json = json.dumps({"mrr": mrr_data, "churn": churn_data, "projection": projection})
    # ON CONFLICT with nullable org_id requires manual upsert (PostgreSQL NULLs are distinct in UNIQUE)
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM revenue_snapshots WHERE org_id IS NULL AND snapshot_date = $1", snap_date
        )
        row = await conn.fetchrow(
            """INSERT INTO revenue_snapshots (org_id, snapshot_date, mrr_idr, arr_idr,
                                              active_subscriptions, new_subscriptions, canceled_subscriptions,
                                              churn_rate, ltv_idr, cac_idr, projected_mrr_idr, raw_metrics)
               VALUES (NULL, $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
               RETURNING *""",
            snap_date, mrr_data["mrr_idr"], mrr_data["arr_idr"], mrr_data["active_subscriptions"],
            churn_data["new_in_period"], churn_data["canceled_in_period"], churn_data["churn_rate"],
            ltv, cac, projection.get("projected_mrr_idr", mrr_data["mrr_idr"]),
            raw_metrics_json,
        )
    return dict(row)


async def revenue_trend(pool: asyncpg.Pool, *, days: int = 90) -> list[dict]:
    rows = await pool.fetch(
        """SELECT snapshot_date, mrr_idr, arr_idr, active_subscriptions,
                  new_subscriptions, canceled_subscriptions, churn_rate, ltv_idr, cac_idr
           FROM revenue_snapshots
           WHERE org_id IS NULL AND snapshot_date >= CURRENT_DATE - $1::int
           ORDER BY snapshot_date ASC""",
        days,
    )
    return [dict(r) for r in rows]


# ============================================================
# ROUTER
# ============================================================

def build_revenue_router(*, get_pool: GetPool, get_current_user: GetCurrentUser) -> APIRouter:
    router = APIRouter(prefix="/revenue", tags=["revenue-intelligence"])

    @router.get("/overview")
    async def overview(
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        _require_platform_admin(user)
        mrr_data   = await compute_mrr(pool)
        churn_data = await compute_churn(pool, period_days=30)
        ltv = compute_ltv(mrr_idr=mrr_data["mrr_idr"], active_subscriptions=mrr_data["active_subscriptions"],
                          churn_rate=churn_data["churn_rate"])
        cac = compute_cac(new_customers=churn_data["new_in_period"])
        projection = await project_mrr_growth(pool)
        return {
            "mrr_idr": mrr_data["mrr_idr"], "arr_idr": mrr_data["arr_idr"],
            "active_subscriptions": mrr_data["active_subscriptions"],
            "churn": churn_data, "ltv_idr": ltv, "cac_idr": cac,
            "ltv_to_cac_ratio": round(ltv / cac, 2) if cac > 0 else None,
            "growth_projection": projection,
        }

    @router.get("/trend")
    async def trend(
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        days: int = 90,
    ):
        _require_platform_admin(user)
        return {"trend": await revenue_trend(pool, days=days)}

    @router.post("/snapshot/run")
    async def run_snapshot(
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        _require_platform_admin(user)
        return {"snapshot": await generate_snapshot(pool)}

    return router
