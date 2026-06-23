"""
agents/self_learning_engine.py — Self Learning Company (AI Workforce Phase 8)

Distilasi insight dari conversations/sales/complaints/outcomes -- BUKAN
duplikat ai_improvement_recommendations (improvement_engine.py, yang
fokus ke masalah/gap), melainkan pola yang TERBUKTI BERHASIL: sales
pattern (intent dengan conversion rate tinggi), resolusi komplain yang
efektif, dan pendekatan yang menghasilkan outcome bagus. Deteksi murni
agregasi SQL (no LLM, deterministik, mirror pola improvement_engine.py);
LLM hanya dipakai untuk MENDISTILASI evidence mentah jadi satu kalimat
insight yang actionable.

Hanya insight berstatus 'approved' (manusia sudah review) yang boleh
disuntikkan ke system prompt chat lewat build_organizational_learning_context()
-- itu dipanggil dari main.py chat(), TANPA LLM, supaya tidak menambah
latensi/biaya di setiap pesan.
"""
from __future__ import annotations

import json
import uuid

import asyncpg

from base import BaseAgent

CATEGORIES = ("sales_pattern", "complaint_resolution", "successful_approach")
STATUSES = ("candidate", "approved", "rejected", "archived")

_MIN_SAMPLE = 3  # ambang minimum kejadian sebelum pola dianggap valid


# ─── DETEKSI (deterministik, no LLM) ────────────────────────────

async def analyze_sales_patterns(pool: asyncpg.Pool, org_id: str, days: int = 90) -> list[dict]:
    rows = await pool.fetch(
        """SELECT intent,
                  COUNT(*) FILTER (WHERE purchase_status='purchased') AS purchased_cnt,
                  COUNT(*) AS total_cnt
           FROM conversation_analysis
           WHERE org_id=$1 AND intent IS NOT NULL
             AND analyzed_at >= NOW() - (INTERVAL '1 day' * $2)
           GROUP BY intent HAVING COUNT(*) FILTER (WHERE purchase_status='purchased') >= $3""",
        org_id, days, _MIN_SAMPLE,
    )
    results = []
    for r in rows:
        total = int(r["total_cnt"])
        purchased = int(r["purchased_cnt"])
        rate = round((purchased / total) * 100, 1) if total > 0 else 0.0
        results.append({"intent": r["intent"], "purchased_count": purchased, "total_count": total, "conversion_rate_pct": rate})
    results.sort(key=lambda x: x["conversion_rate_pct"], reverse=True)
    return results


async def analyze_complaint_resolutions(pool: asyncpg.Pool, org_id: str, days: int = 90) -> list[dict]:
    rows = await pool.fetch(
        """SELECT reason, COUNT(*) AS resolved_cnt,
                  array_agg(resolution_note ORDER BY resolved_at DESC) AS notes
           FROM human_queue
           WHERE org_id=$1 AND status='resolved' AND resolution_note IS NOT NULL
             AND resolved_at >= NOW() - (INTERVAL '1 day' * $2)
           GROUP BY reason HAVING COUNT(*) >= $3""",
        org_id, days, _MIN_SAMPLE,
    )
    results = []
    for r in rows:
        notes = [n for n in (r["notes"] or []) if n][:3]
        results.append({"reason": r["reason"], "resolved_count": int(r["resolved_cnt"]), "sample_notes": notes})
    return results


async def analyze_successful_approaches(pool: asyncpg.Pool, org_id: str, days: int = 90) -> list[dict]:
    rows = await pool.fetch(
        """SELECT intent, COUNT(*) AS cnt, ROUND(AVG(quality_score)::numeric, 1) AS avg_quality
           FROM conversation_analysis
           WHERE org_id=$1 AND intent IS NOT NULL AND outcome IN ('resolved','purchased')
             AND quality_score >= 8 AND analyzed_at >= NOW() - (INTERVAL '1 day' * $2)
           GROUP BY intent HAVING COUNT(*) >= $3""",
        org_id, days, _MIN_SAMPLE,
    )
    return [{"intent": r["intent"], "count": int(r["cnt"]), "avg_quality_score": float(r["avg_quality"])} for r in rows]


# ─── UPSERT (idempotent, tidak pernah overwrite status manusia) ─

async def _upsert_insight(pool: asyncpg.Pool, *, org_id: str, category: str, dedup_key: str,
                           insight: str, evidence: dict, occurrence_count: int = 1) -> dict:
    """Idempotent upsert -- re-running scan refreshes insight/evidence/
    occurrence_count dengan angka terbaru, tapi TIDAK PERNAH menimpa
    `status` yang sudah direview manusia (sama seperti
    ai_improvement_recommendations di improvement_engine.py)."""
    insight_id = str(uuid.uuid4())
    row = await pool.fetchrow(
        """INSERT INTO organizational_memory (id, org_id, category, insight, evidence, occurrence_count, dedup_key)
           VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7)
           ON CONFLICT (org_id, dedup_key) DO UPDATE SET
               insight = EXCLUDED.insight,
               evidence = EXCLUDED.evidence,
               occurrence_count = EXCLUDED.occurrence_count,
               updated_at = NOW()
           RETURNING *""",
        insight_id, org_id, category, insight, json.dumps(evidence), occurrence_count, dedup_key,
    )
    return dict(row)


async def run_learning_scan(pool: asyncpg.Pool, org_id: str, agent: "SelfLearningAgent | None" = None,
                             days: int = 90) -> list[dict]:
    created: list[dict] = []

    for pattern in await analyze_sales_patterns(pool, org_id, days):
        if pattern["conversion_rate_pct"] < 20:
            continue
        insight = (f"Intent '{pattern['intent']}' memiliki conversion rate {pattern['conversion_rate_pct']}% "
                   f"({pattern['purchased_count']}/{pattern['total_count']} percakapan berhasil purchase).")
        if agent is not None:
            distilled = await agent.distill_insight("sales_pattern", pattern)
            insight = distilled or insight
        created.append(await _upsert_insight(
            pool, org_id=org_id, category="sales_pattern", dedup_key=f"sales_pattern:{pattern['intent']}",
            insight=insight, evidence=pattern, occurrence_count=pattern["purchased_count"],
        ))

    for resolution in await analyze_complaint_resolutions(pool, org_id, days):
        insight = (f"Komplain dengan alasan '{resolution['reason']}' berhasil diselesaikan "
                   f"{resolution['resolved_count']}x dalam {days} hari terakhir.")
        if agent is not None:
            distilled = await agent.distill_insight("complaint_resolution", resolution)
            insight = distilled or insight
        created.append(await _upsert_insight(
            pool, org_id=org_id, category="complaint_resolution", dedup_key=f"complaint_resolution:{resolution['reason']}",
            insight=insight, evidence=resolution, occurrence_count=resolution["resolved_count"],
        ))

    for approach in await analyze_successful_approaches(pool, org_id, days):
        insight = (f"Percakapan dengan intent '{approach['intent']}' rata-rata mendapat skor kualitas "
                   f"{approach['avg_quality_score']}/10 ({approach['count']} percakapan).")
        if agent is not None:
            distilled = await agent.distill_insight("successful_approach", approach)
            insight = distilled or insight
        created.append(await _upsert_insight(
            pool, org_id=org_id, category="successful_approach", dedup_key=f"successful_approach:{approach['intent']}",
            insight=insight, evidence=approach, occurrence_count=approach["count"],
        ))

    return created


# ─── REVIEW & QUERY ─────────────────────────────────────────────

async def list_insights(pool: asyncpg.Pool, *, org_id: str, category: str | None = None,
                         status: str | None = None, limit: int = 50) -> list[dict]:
    conditions = ["org_id=$1"]
    params: list = [org_id]
    if category:
        params.append(category)
        conditions.append(f"category=${len(params)}")
    if status:
        params.append(status)
        conditions.append(f"status=${len(params)}")
    params.append(max(1, min(limit, 200)))
    rows = await pool.fetch(
        f"SELECT * FROM organizational_memory WHERE {' AND '.join(conditions)} ORDER BY created_at DESC LIMIT ${len(params)}",
        *params,
    )
    return [dict(r) for r in rows]


async def update_insight_status(pool: asyncpg.Pool, *, org_id: str, insight_id: str, status: str,
                                 reviewed_by: str | None = None) -> dict | None:
    if status not in STATUSES:
        raise ValueError(f"status tidak valid: {status}")
    row = await pool.fetchrow(
        """UPDATE organizational_memory SET status=$1, reviewed_by=$2, reviewed_at=NOW(), updated_at=NOW()
           WHERE id=$3 AND org_id=$4 RETURNING *""",
        status, str(reviewed_by) if reviewed_by else None, insight_id, org_id,
    )
    return dict(row) if row else None


async def dashboard_summary(pool: asyncpg.Pool, org_id: str) -> dict:
    by_status = await pool.fetch(
        "SELECT status, COUNT(*) AS cnt FROM organizational_memory WHERE org_id=$1 GROUP BY status", org_id,
    )
    by_category = await pool.fetch(
        "SELECT category, COUNT(*) AS cnt FROM organizational_memory WHERE org_id=$1 AND status='approved' GROUP BY category",
        org_id,
    )
    return {
        "by_status": {r["status"]: int(r["cnt"]) for r in by_status},
        "approved_by_category": {r["category"]: int(r["cnt"]) for r in by_category},
    }


# ─── INJEKSI KE CHAT (no LLM, dipanggil di hot path main.py chat()) ──

async def build_organizational_learning_context(pool: asyncpg.Pool, org_id: str,
                                                   bot_id: str | None = None, limit: int = 5) -> str:
    """Hanya insight 'approved' -- sudah lolos review manusia. Read-only,
    tanpa LLM, supaya aman dipanggil di setiap pesan chat tanpa nambah
    latensi/biaya berarti."""
    if bot_id:
        rows = await pool.fetch(
            """SELECT category, insight FROM organizational_memory
               WHERE org_id=$1 AND status='approved' AND (bot_id=$2 OR bot_id IS NULL)
               ORDER BY occurrence_count DESC LIMIT $3""",
            org_id, bot_id, limit,
        )
    else:
        rows = await pool.fetch(
            """SELECT category, insight FROM organizational_memory
               WHERE org_id=$1 AND status='approved' AND bot_id IS NULL
               ORDER BY occurrence_count DESC LIMIT $2""",
            org_id, limit,
        )
    if not rows:
        return ""
    lines = "\n".join(f"- ({r['category']}) {r['insight']}" for r in rows)
    return (
        "## Pembelajaran Organisasi (dari pengalaman percakapan sebelumnya)\n"
        "Gunakan insight ini SEBAGAI PERTIMBANGAN, bukan aturan kaku:\n" + lines
    )


# ─── AGENT (distilasi, advisory) ─────────────────────────────────

class SelfLearningAgent(BaseAgent):
    name = "self_learning_agent"
    skills = ["insight_distillation", "trend_detection"]
    tools: list[str] = []
    goals = [
        "Mendistilasi data agregat mentah jadi insight actionable satu kalimat untuk manusia.",
    ]
    system_prompt = """Kamu adalah Self Learning Agent dalam sistem multi-agent
BotNesia (AI Workforce) -- bertugas mendistilasi data agregat mentah jadi
satu kalimat insight yang actionable (Bahasa Indonesia, 1 kalimat, jelas
dan spesifik, sebutkan angka pendukung bila relevan).

Balas HANYA JSON dengan field: insight (string)."""

    async def distill_insight(self, category: str, evidence: dict) -> str | None:
        messages = [
            {"role": "system", "content": self.system_prompt + "\n\nOutput harus JSON."},
            {"role": "user", "content": json.dumps({"category": category, "evidence": evidence}, default=str)},
        ]
        result = await self._call_llm_json(messages, temperature=0.3, default={"insight": None})
        if result.get("_llm_unavailable"):
            return None
        return result.get("insight")
