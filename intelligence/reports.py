"""
intelligence/reports.py — Generator laporan Auto-Learning harian.

Mengagregasi data H-1 dari conversation_analysis, faq_entries, sales_patterns
menjadi satu snapshot `learning_reports` (idempotent — upsert per bot+tanggal):

    - Top FAQ                  (FAQ paling sering muncul / paling sukses)
    - Top Complaint            (friction points & sentimen negatif terbanyak)
    - Top Sales Trigger        (pola sales dengan occurrence & conversion tinggi)
    - Top Conversion Path      (kombinasi topic→outcome yang paling sering closing)
    - Top Failed Conversation  (percakapan dengan outcome buruk / quality rendah)
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone

from .db import get_pool


def _day_bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime.combine(d, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


async def _top_faq(pool, bot_id: str, limit: int = 10) -> list[dict]:
    rows = await pool.fetch(
        """SELECT question, answer, frequency_score, success_score, conversion_score, updated_at
           FROM faq_entries
           WHERE bot_id = $1 AND status != 'archived'
           ORDER BY frequency_score DESC, conversion_score DESC
           LIMIT $2""",
        bot_id, limit,
    )
    return [
        {
            "question": r["question"],
            "answer": r["answer"][:300],
            "frequency_score": r["frequency_score"],
            "success_score": round(r["success_score"], 3),
            "conversion_score": round(r["conversion_score"], 3),
            "updated_at": r["updated_at"].isoformat(),
        }
        for r in rows
    ]


async def _top_complaint(pool, bot_id: str, start, end, limit: int = 10) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT jsonb_array_elements_text(COALESCE(raw_metrics -> 'friction_points', '[]'::jsonb)) AS complaint,
               COUNT(*) AS cnt
        FROM conversation_analysis
        WHERE bot_id = $1 AND analyzed_at >= $2 AND analyzed_at < $3
        GROUP BY complaint
        ORDER BY cnt DESC
        LIMIT $4
        """,
        bot_id, start, end, limit,
    )
    return [{"complaint": r["complaint"], "count": r["cnt"]} for r in rows]


async def _top_sales_trigger(pool, bot_id: str, limit: int = 10) -> list[dict]:
    rows = await pool.fetch(
        """SELECT pattern_type, COALESCE(trigger_text, objection_text) AS text,
                  occurrences, conversions, conversion_rate, confidence_score
           FROM sales_patterns
           WHERE bot_id = $1
           ORDER BY occurrences DESC, conversion_rate DESC
           LIMIT $2""",
        bot_id, limit,
    )
    return [
        {
            "pattern_type": r["pattern_type"],
            "text": r["text"],
            "occurrences": r["occurrences"],
            "conversions": r["conversions"],
            "conversion_rate": round(r["conversion_rate"], 3),
            "confidence_score": round(r["confidence_score"], 3),
        }
        for r in rows
    ]


async def _top_conversion_path(pool, bot_id: str, limit: int = 10) -> list[dict]:
    """
    "Path" disederhanakan sebagai kombinasi (intent → topics[0] → outcome) yang
    paling sering berakhir `purchased` — proxy ringan untuk customer journey
    tanpa perlu melacak urutan event lintas-sesi (yang butuh skema tambahan).
    """
    rows = await pool.fetch(
        """
        SELECT intent,
               COALESCE(topics[1], 'umum') AS primary_topic,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE purchase_status = 'purchased') AS purchased
        FROM conversation_analysis
        WHERE bot_id = $1
        GROUP BY intent, primary_topic
        HAVING COUNT(*) FILTER (WHERE purchase_status = 'purchased') > 0
        ORDER BY purchased DESC, total DESC
        LIMIT $2
        """,
        bot_id, limit,
    )
    return [
        {
            "path": f"{r['intent'] or 'unknown'} → {r['primary_topic']} → purchased",
            "total_conversations": r["total"],
            "purchased": r["purchased"],
            "conversion_rate": round(r["purchased"] / r["total"], 3) if r["total"] else 0,
        }
        for r in rows
    ]


async def _top_failed_conversation(pool, bot_id: str, start, end, limit: int = 10) -> list[dict]:
    rows = await pool.fetch(
        """SELECT conversation_id, intent, sentiment_label, outcome, escalation_status,
                  quality_score, summary
           FROM conversation_analysis
           WHERE bot_id = $1 AND analyzed_at >= $2 AND analyzed_at < $3
                 AND (outcome IN ('unresolved', 'escalated', 'abandoned') OR quality_score < 5)
           ORDER BY quality_score ASC NULLS FIRST, analyzed_at DESC
           LIMIT $4""",
        bot_id, start, end, limit,
    )
    return [
        {
            "conversation_id": str(r["conversation_id"]),
            "intent": r["intent"],
            "sentiment": r["sentiment_label"],
            "outcome": r["outcome"],
            "escalation_status": r["escalation_status"],
            "quality_score": r["quality_score"],
            "summary": r["summary"],
        }
        for r in rows
    ]


async def generate_daily_report(bot_id: str, org_id: str, *, report_date: date | None = None) -> dict:
    """Hitung & upsert satu snapshot `learning_reports` untuk (bot_id, report_date)."""
    report_date = report_date or (date.today() - timedelta(days=1))
    start, end = _day_bounds(report_date)
    pool = await get_pool()

    conv_count = await pool.fetchval(
        """SELECT COUNT(*) FROM conversation_analysis
           WHERE bot_id = $1 AND analyzed_at >= $2 AND analyzed_at < $3""",
        bot_id, start, end,
    )
    new_faq = await pool.fetchval(
        "SELECT COUNT(*) FROM faq_entries WHERE bot_id = $1 AND created_at >= $2 AND created_at < $3",
        bot_id, start, end,
    )
    new_patterns = await pool.fetchval(
        "SELECT COUNT(*) FROM sales_patterns WHERE bot_id = $1 AND created_at >= $2 AND created_at < $3",
        bot_id, start, end,
    )

    top_faq               = await _top_faq(pool, bot_id)
    top_complaint         = await _top_complaint(pool, bot_id, start, end)
    top_sales_trigger     = await _top_sales_trigger(pool, bot_id)
    top_conversion_path   = await _top_conversion_path(pool, bot_id)
    top_failed_conversation = await _top_failed_conversation(pool, bot_id, start, end)

    row = await pool.fetchrow(
        """
        INSERT INTO learning_reports (
            bot_id, org_id, report_date, conversations_analyzed,
            new_faq_count, new_pattern_count,
            top_faq, top_complaint, top_sales_trigger, top_conversion_path, top_failed_conversation
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
        ON CONFLICT (bot_id, report_date) DO UPDATE SET
            conversations_analyzed   = EXCLUDED.conversations_analyzed,
            new_faq_count            = EXCLUDED.new_faq_count,
            new_pattern_count        = EXCLUDED.new_pattern_count,
            top_faq                  = EXCLUDED.top_faq,
            top_complaint            = EXCLUDED.top_complaint,
            top_sales_trigger        = EXCLUDED.top_sales_trigger,
            top_conversion_path      = EXCLUDED.top_conversion_path,
            top_failed_conversation  = EXCLUDED.top_failed_conversation,
            generated_at             = NOW()
        RETURNING id, report_date, generated_at
        """,
        bot_id, org_id, report_date, conv_count or 0, new_faq or 0, new_patterns or 0,
        json.dumps(top_faq), json.dumps(top_complaint), json.dumps(top_sales_trigger),
        json.dumps(top_conversion_path), json.dumps(top_failed_conversation),
    )

    return {
        "id": str(row["id"]),
        "bot_id": bot_id,
        "report_date": row["report_date"].isoformat(),
        "generated_at": row["generated_at"].isoformat(),
        "conversations_analyzed": conv_count or 0,
        "new_faq_count": new_faq or 0,
        "new_pattern_count": new_patterns or 0,
        "top_faq": top_faq,
        "top_complaint": top_complaint,
        "top_sales_trigger": top_sales_trigger,
        "top_conversion_path": top_conversion_path,
        "top_failed_conversation": top_failed_conversation,
    }


async def get_latest_report(bot_id: str) -> dict | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        """SELECT * FROM learning_reports WHERE bot_id = $1 ORDER BY report_date DESC LIMIT 1""",
        bot_id,
    )
    if not row:
        return None
    d = dict(row)
    for k in ("top_faq", "top_complaint", "top_sales_trigger", "top_conversion_path", "top_failed_conversation"):
        if isinstance(d.get(k), str):
            d[k] = json.loads(d[k])
    d["id"] = str(d["id"])
    d["report_date"] = d["report_date"].isoformat()
    d["generated_at"] = d["generated_at"].isoformat()
    return d
