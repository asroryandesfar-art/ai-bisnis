"""
intelligence/nightly_jobs.py — AUTO LEARNING

Tiap malam (lihat jadwal di celery_app.py, default 19:00 UTC ≈ 02:00 WIB):
  1. Tarik & analisis seluruh percakapan H-1 (sudah tersimpan realtime di
     `conversation_analysis` oleh ConversationMemory — di sini kita AGREGASI).
  2. FAQ Engine    — cluster pertanyaan baru, refresh skor FAQ existing.
  3. Sales Intel   — tambang pola Trigger/Objection/Solution dari sinyal mentah.
  4. Knowledge Graph — (graf sudah di-upsert realtime; di sini hanya housekeeping
     ringan — lihat `_decay_stale_edges`).
  5. Generate laporan harian (Top FAQ, Top Complaint, Top Sales Trigger,
     Top Conversion Path, Top Failed Conversation) → `learning_reports`.

Fungsi-fungsi di sini bersifat ASYNC (dipanggil via asyncio.run dari Celery task
sinkron di celery_app.py — Celery worker tidak punya event loop sendiri).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from . import faq_agent, reports, sales_agent
from .db import get_pool

logger = logging.getLogger("intelligence.nightly")


async def _active_bots() -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch("SELECT id AS bot_id, org_id FROM bots WHERE status IN ('active', 'training')")
    return [dict(r) for r in rows]


async def _decay_stale_edges(bot_id: str, *, older_than_days: int = 90, decay_factor: float = 0.9) -> int:
    """
    Housekeeping graf: relasi yang sudah lama tidak "disebut lagi" perlahan
    diturunkan bobotnya (bukan dihapus — tetap berguna untuk historis), supaya
    visualisasi & rekomendasi mengikuti tren terbaru, bukan tumpukan data lama.
    """
    pool = await get_pool()
    cutoff = date.today() - timedelta(days=older_than_days)
    result = await pool.execute(
        """UPDATE kg_edges SET weight = GREATEST(1, FLOOR(weight * $2))
           WHERE bot_id = $1 AND updated_at < $3 AND weight > 1""",
        bot_id, decay_factor, cutoff,
    )
    # asyncpg execute() balikin string "UPDATE n"
    try:
        return int(result.split()[-1])
    except Exception:
        return 0


async def run_daily_learning(bot_id: str | None = None, *, report_date: date | None = None) -> dict:
    """
    Job utama. `bot_id=None` -> proses semua bot aktif (dipakai jadwal malam).
    `bot_id` spesifik -> dipakai untuk trigger manual (`POST /intel/learning/run`).
    """
    report_date = report_date or (date.today() - timedelta(days=1))
    if bot_id is None:
        bots = await _active_bots()
    else:
        pool = await get_pool()
        row = await pool.fetchrow("SELECT id AS bot_id, org_id FROM bots WHERE id = $1", bot_id)
        bots = [dict(row)] if row else []

    summary: list[dict] = []
    for b in bots:
        bid, oid = str(b["bot_id"]), str(b["org_id"])
        try:
            faq_result = await faq_agent.cluster_new_questions(bid, oid)
            faq_rescored = await faq_agent.recompute_scores(bid)

            sales_result = await sales_agent.mine_patterns(bid, oid)
            solutions_attached = await sales_agent.attach_solutions(bid)

            edges_decayed = await _decay_stale_edges(bid)

            report = await reports.generate_daily_report(bid, oid, report_date=report_date)

            summary.append({
                "bot_id": bid,
                "report_date": report_date.isoformat(),
                "faq": {**faq_result, "rescored": faq_rescored},
                "sales": {**sales_result, "solutions_attached": solutions_attached},
                "knowledge_graph": {"edges_decayed": edges_decayed},
                "report_id": report["id"],
            })
        except Exception as e:
            logger.exception("run_daily_learning gagal untuk bot %s", bid)
            summary.append({"bot_id": bid, "error": str(e)})

    return {"processed_bots": len(summary), "results": summary}
