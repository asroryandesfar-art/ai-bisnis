"""
bn_platform/lead_engine.py — Lead Generation Engine

AI mengidentifikasi prospek, memberi skor 0-100, dan merekomendasikan
tindak lanjut — diklasifikasikan Cold / Warm / Hot. Dibangun DI ATAS data
yang sudah dikumpulkan Intelligence Platform (Phase 1):

  • intelligence.customer_profiles  — lead_score (EMA), churn_risk, lifetime_value
  • intelligence.sales_signals      — sinyal niat beli / objection per percakapan

Skor komposit (0-100) = kombinasi terbobot dari:
  - lead_score existing (EMA dari ConversationMemory, 0..1)         bobot 50
  - jumlah pembelian historis                                        bobot ≤25
  - sinyal pra-pembelian terbaru (pre_purchase_question/reason_buy)  bobot ≤15
  - kebaruan interaksi (recency)                                     bobot ≤10
  - dikurangi risiko churn                                           penalti ≤15

Hasil disimpan sbg snapshot di `lead_scores` (riwayat, bukan overwrite)
sehingga tren minat bisa dianalisis dari waktu ke waktu — lihat
schema_platform.sql §6.

Dijalankan: (a) batch nightly via Celery beat, atau (b) on-demand lewat
endpoint POST /leads/recompute (mis. dipanggil manager sebelum sesi follow-up).
"""
# from __future__ import annotations  # dihapus: menyebabkan Depends(closure_var) gagal di-resolve oleh FastAPI get_type_hints()

import logging
from datetime import datetime, timezone
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status

logger = logging.getLogger("bn_platform.lead_engine")

GetCurrentUser = Callable[..., Awaitable[dict]]
GetPool        = Callable[..., Awaitable[asyncpg.Pool]]

HOT_THRESHOLD  = 70.0
WARM_THRESHOLD = 40.0

_PRE_PURCHASE_TYPES = ("pre_purchase_question", "reason_buy")
_OBJECTION_TYPES    = ("objection_price", "objection_product", "objection_service", "reason_cancel")


def _categorize(score: float) -> str:
    if score >= HOT_THRESHOLD:
        return "hot"
    if score >= WARM_THRESHOLD:
        return "warm"
    return "cold"


def _recency_boost(last_interaction_at) -> float:
    if not last_interaction_at:
        return 0.0
    delta = datetime.now(timezone.utc) - last_interaction_at.replace(tzinfo=timezone.utc) \
        if last_interaction_at.tzinfo is None else datetime.now(timezone.utc) - last_interaction_at
    days = delta.total_seconds() / 86400.0
    if days <= 7:
        return 10.0
    if days <= 30:
        return 5.0
    return 0.0


def compute_lead_score(*, lead_score_ema: float, total_purchases: int, churn_risk: float,
                       last_interaction_at, pre_purchase_count: int, objection_count: int) -> tuple[float, str, dict]:
    """Hitung skor komposit 0-100 + kategori. Return (score, category, breakdown)."""
    base          = max(0.0, min(1.0, lead_score_ema)) * 50.0
    purchase_part = min(total_purchases, 5) * 5.0
    intent_part   = min(pre_purchase_count, 5) * 3.0
    recency_part  = _recency_boost(last_interaction_at)
    churn_penalty = max(0.0, min(1.0, churn_risk)) * 15.0
    objection_drag = min(objection_count, 3) * 2.0

    raw = base + purchase_part + intent_part + recency_part - churn_penalty - objection_drag
    score = round(max(0.0, min(100.0, raw)), 2)
    breakdown = {
        "base_from_lead_score": round(base, 2),
        "purchase_history": round(purchase_part, 2),
        "purchase_intent_signals": round(intent_part, 2),
        "recency": round(recency_part, 2),
        "churn_penalty": -round(churn_penalty, 2),
        "objection_drag": -round(objection_drag, 2),
    }
    return score, _categorize(score), breakdown


def recommend_follow_up(*, category: str, breakdown: dict, pre_purchase_count: int,
                        objection_count: int, total_purchases: int) -> str:
    """Rekomendasi tindak lanjut heuristik (deterministik, tanpa panggilan LLM —
    bisa diganti/disempurnakan dgn intelligence.llm.call_llm bila ingin narasi
    yang lebih personal, lihat ARCHITECTURE.md §9 catatan ekstensi)."""
    if category == "hot":
        if objection_count > 0:
            return ("Prospek HOT tapi masih ada keberatan — hubungi dalam 24 jam, "
                    "siapkan jawaban untuk objection (lihat /sales/objections), dan tawarkan insentif penutup (diskon/bonus).")
        return ("Prospek HOT siap dikonversi — segera follow-up personal (telepon/WA) "
                "dalam 24 jam dengan penawaran konkret & batas waktu (urgency).")
    if category == "warm":
        if pre_purchase_count > 0:
            return ("Prospek WARM menunjukkan minat aktif — kirim informasi produk relevan, "
                    "studi kasus/testimoni, dan jadwalkan follow-up dalam 3-5 hari.")
        return ("Prospek WARM — pertahankan engagement dengan konten edukatif & FAQ relevan, "
                "pantau sinyal pembelian berikutnya sebelum melakukan hard-sell.")
    if total_purchases > 0:
        return ("Prospek COLD namun pernah membeli — pertimbangkan kampanye reaktivasi "
                "(promo loyalitas/cross-sell) daripada follow-up langsung.")
    return ("Prospek COLD — masukkan ke nurturing campaign (newsletter/broadcast edukatif), "
            "jangan prioritaskan follow-up manual saat ini.")


# ============================================================
# REPOSITORY
# ============================================================

async def _signal_counts(pool: asyncpg.Pool, *, bot_id: str, end_user_id: str) -> tuple[int, int]:
    row = await pool.fetchrow(
        """SELECT
             COUNT(*) FILTER (WHERE ss.signal_type = ANY($3))                          AS pre_purchase,
             COUNT(*) FILTER (WHERE ss.signal_type = ANY($4))                          AS objection
           FROM sales_signals ss
           JOIN conversations c ON c.id = ss.conversation_id
           WHERE ss.bot_id = $1 AND c.end_user_id = $2
             AND ss.created_at >= NOW() - INTERVAL '60 days'""",
        bot_id, end_user_id, list(_PRE_PURCHASE_TYPES), list(_OBJECTION_TYPES),
    )
    return int(row["pre_purchase"]), int(row["objection"])


async def recompute_leads(pool: asyncpg.Pool, *, org_id: str, bot_id: str | None = None,
                          limit: int = 500) -> dict:
    """Hitung ulang skor untuk semua customer_profiles tenant ini & simpan snapshot baru."""
    if bot_id:
        profiles = await pool.fetch(
            """SELECT * FROM customer_profiles WHERE org_id=$1 AND bot_id=$2
               ORDER BY last_interaction_at DESC NULLS LAST LIMIT $3""",
            org_id, bot_id, limit,
        )
    else:
        profiles = await pool.fetch(
            """SELECT * FROM customer_profiles WHERE org_id=$1
               ORDER BY last_interaction_at DESC NULLS LAST LIMIT $2""",
            org_id, limit,
        )

    counts = {"cold": 0, "warm": 0, "hot": 0}
    for p in profiles:
        pre_purchase_count, objection_count = await _signal_counts(
            pool, bot_id=str(p["bot_id"]), end_user_id=p["end_user_id"],
        )
        score, category, breakdown = compute_lead_score(
            lead_score_ema=p["lead_score"], total_purchases=p["total_purchases"],
            churn_risk=p["churn_risk"], last_interaction_at=p["last_interaction_at"],
            pre_purchase_count=pre_purchase_count, objection_count=objection_count,
        )
        recommendation = recommend_follow_up(
            category=category, breakdown=breakdown, pre_purchase_count=pre_purchase_count,
            objection_count=objection_count, total_purchases=p["total_purchases"],
        )
        await pool.execute(
            """INSERT INTO lead_scores (org_id, bot_id, end_user_id, score, category,
                                        signals, recommended_action)
               VALUES ($1,$2,$3,$4,$5,$6,$7)""",
            org_id, p["bot_id"], p["end_user_id"], score, category,
            {**breakdown, "pre_purchase_signals": pre_purchase_count, "objection_signals": objection_count},
            recommendation,
        )
        counts[category] += 1

    return {"processed": len(profiles), "by_category": counts}


async def list_leads(pool: asyncpg.Pool, *, org_id: str, category: str | None = None,
                      bot_id: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    """Ambil skor TERBARU per (bot_id, end_user_id) — distinct on snapshot terbaru."""
    conditions = ["ls.org_id = $1"]
    params: list = [org_id]
    if category:
        params.append(category)
        conditions.append(f"ls.category = ${len(params)}")
    if bot_id:
        params.append(bot_id)
        conditions.append(f"ls.bot_id = ${len(params)}")
    where = " AND ".join(conditions)
    params.extend([limit, offset])
    rows = await pool.fetch(
        f"""SELECT DISTINCT ON (ls.bot_id, ls.end_user_id)
                   ls.id, ls.bot_id, ls.end_user_id, ls.score, ls.category,
                   ls.signals, ls.recommended_action, ls.computed_at,
                   cp.display_name, cp.email, cp.lifetime_value, cp.total_purchases
            FROM lead_scores ls
            LEFT JOIN customer_profiles cp ON cp.bot_id = ls.bot_id AND cp.end_user_id = ls.end_user_id
            WHERE {where}
            ORDER BY ls.bot_id, ls.end_user_id, ls.computed_at DESC
            LIMIT ${len(params)-1} OFFSET ${len(params)}""",
        *params,
    )
    rows = [dict(r) for r in rows]
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


async def lead_funnel_summary(pool: asyncpg.Pool, *, org_id: str) -> dict:
    row = await pool.fetchrow(
        """SELECT DISTINCT ON (bot_id, end_user_id) category
           FROM lead_scores WHERE org_id=$1
           ORDER BY bot_id, end_user_id, computed_at DESC""",
        org_id,
    )
    rows = await pool.fetch(
        """SELECT category, COUNT(*) AS total FROM (
             SELECT DISTINCT ON (bot_id, end_user_id) bot_id, end_user_id, category
             FROM lead_scores WHERE org_id=$1
             ORDER BY bot_id, end_user_id, computed_at DESC
           ) t GROUP BY category""",
        org_id,
    )
    summary = {"cold": 0, "warm": 0, "hot": 0}
    for r in rows:
        summary[r["category"]] = r["total"]
    return summary


# ============================================================
# ROUTER
# ============================================================

def build_lead_router(*, get_pool: GetPool, get_current_user: GetCurrentUser, require_permission) -> APIRouter:
    router = APIRouter(prefix="/leads", tags=["leads"])

    @router.get("")
    async def get_leads(
        user: Annotated[dict, Depends(require_permission("analytics.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        category: str | None = None, bot_id: str | None = None, limit: int = 50, offset: int = 0,
    ):
        if category and category not in ("cold", "warm", "hot"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "category harus salah satu dari cold/warm/hot")
        leads = await list_leads(pool, org_id=user["org_id"], category=category, bot_id=bot_id,
                                 limit=limit, offset=offset)
        return {"leads": leads}

    @router.get("/summary")
    async def get_summary(
        user: Annotated[dict, Depends(require_permission("analytics.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        return {"funnel": await lead_funnel_summary(pool, org_id=user["org_id"])}

    @router.post("/recompute")
    async def recompute(
        user: Annotated[dict, Depends(require_permission("analytics.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        bot_id: str | None = None,
    ):
        return await recompute_leads(pool, org_id=user["org_id"], bot_id=bot_id)

    return router
