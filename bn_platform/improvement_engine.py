"""AI Improvement Engine — BotNesia mengevaluasi performanya sendiri.

Menganalisis:
  - failed answers      (conversation_analysis.outcome bermasalah / verifikasi gagal)
  - low confidence       (raw_metrics.confidence_score di bawah ambang)
  - negative feedback    (feedback_records rating='not_helpful')
  - repeated questions   (feedback_learning_queue.occurrence_count tinggi)
  - handoff frequency    (human_queue per alasan)

...dan menghasilkan rekomendasi (knowledge_gap / prompt_improvement /
workflow_improvement / agent_improvement) yang disimpan di
ai_improvement_recommendations.

PENTING: engine ini HANYA mendeteksi & merekomendasikan. Tidak pernah
mengubah prompt, knowledge, workflow, atau konfigurasi agent secara
otomatis — admin yang memutuskan via endpoint PATCH status.
"""
from __future__ import annotations

import json
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .security import _check_rate_limit, write_audit_log

GetPool = Callable[..., Awaitable[asyncpg.Pool]]
GetCurrentUser = Callable[..., Awaitable[dict]]

LOW_CONFIDENCE_THRESHOLD = 60       # confidence_score (0-100) di bawah ini dianggap rendah
LOW_QUALITY_THRESHOLD = 5.0         # quality_score (0-10) di bawah ini dianggap lemah
MIN_OCCURRENCES = 2                 # minimal kemunculan sebelum jadi rekomendasi

RECOMMENDATION_CATEGORIES = {"knowledge_gap", "prompt_improvement", "workflow_improvement", "agent_improvement"}
RECOMMENDATION_STATUSES = {"new", "reviewed", "applied", "dismissed"}


def _jsonb(value, default=None):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default if default is not None else {}
    if value is None:
        return default if default is not None else {}
    return value


def _severity_for_count(count: int) -> str:
    if count >= 10:
        return "critical"
    if count >= 5:
        return "high"
    if count >= MIN_OCCURRENCES:
        return "medium"
    return "low"


# ============================================================
# ANALYSIS — query agregat read-only
# ============================================================

async def analyze_failed_answers(pool: asyncpg.Pool, *, org_id: str, days: int = 30) -> list[dict]:
    """Percakapan dgn outcome bermasalah atau verifikasi jawaban gagal, per bot+intent."""
    rows = await pool.fetch(
        """SELECT bot_id, COALESCE(intent, 'unknown') AS intent, outcome, COUNT(*)::int AS count
           FROM conversation_analysis
           WHERE org_id=$1 AND analyzed_at >= NOW() - ($2::int * INTERVAL '1 day')
             AND (outcome IN ('unresolved','abandoned','escalated')
                  OR raw_metrics->>'verification_passed' = 'false')
           GROUP BY bot_id, intent, outcome
           ORDER BY count DESC LIMIT 20""",
        org_id, days,
    )
    return [dict(r) for r in rows]


async def analyze_low_confidence(pool: asyncpg.Pool, *, org_id: str, days: int = 30,
                                  threshold: int = LOW_CONFIDENCE_THRESHOLD) -> list[dict]:
    """Percakapan dgn confidence_score (Pro mode) di bawah ambang, per bot+intent."""
    rows = await pool.fetch(
        """SELECT bot_id, COALESCE(intent, 'unknown') AS intent, COUNT(*)::int AS count,
                  ROUND(AVG((raw_metrics->>'confidence_score')::numeric), 1) AS avg_confidence
           FROM conversation_analysis
           WHERE org_id=$1 AND analyzed_at >= NOW() - ($2::int * INTERVAL '1 day')
             AND raw_metrics->>'confidence_score' IS NOT NULL
             AND (raw_metrics->>'confidence_score')::numeric < $3
           GROUP BY bot_id, intent
           ORDER BY count DESC LIMIT 20""",
        org_id, days, threshold,
    )
    return [dict(r) for r in rows]


async def analyze_negative_feedback(pool: asyncpg.Pool, *, org_id: str, days: int = 30) -> list[dict]:
    """Pertanyaan dgn feedback 'tidak membantu' berulang."""
    rows = await pool.fetch(
        """SELECT bot_id, question, COUNT(*)::int AS count, MAX(created_at) AS last_seen
           FROM feedback_records
           WHERE tenant_id=$1 AND rating='not_helpful'
             AND created_at >= NOW() - ($2::int * INTERVAL '1 day')
           GROUP BY bot_id, question
           ORDER BY count DESC, last_seen DESC LIMIT 20""",
        org_id, days,
    )
    return [dict(r) for r in rows]


async def analyze_repeated_questions(pool: asyncpg.Pool, *, org_id: str, days: int = 30,
                                      min_occurrences: int = MIN_OCCURRENCES) -> list[dict]:
    """Item learning queue yang sudah berulang kali muncul tanpa terselesaikan."""
    rows = await pool.fetch(
        """SELECT bot_id, question, answer, failure_reason, action_type, occurrence_count, status
           FROM feedback_learning_queue
           WHERE tenant_id=$1 AND occurrence_count >= $2 AND status IN ('pending','in_progress')
             AND updated_at >= NOW() - ($3::int * INTERVAL '1 day')
           ORDER BY occurrence_count DESC LIMIT 20""",
        org_id, min_occurrences, days,
    )
    return [dict(r) for r in rows]


async def analyze_handoff_frequency(pool: asyncpg.Pool, *, org_id: str, days: int = 30) -> list[dict]:
    """Frekuensi human handoff per bot+alasan."""
    rows = await pool.fetch(
        """SELECT c.bot_id, hq.reason, COUNT(*)::int AS count
           FROM human_queue hq
           JOIN conversations c ON c.id = hq.conversation_id
           WHERE hq.org_id=$1 AND hq.created_at >= NOW() - ($2::int * INTERVAL '1 day')
           GROUP BY c.bot_id, hq.reason
           ORDER BY count DESC LIMIT 20""",
        org_id, days,
    )
    return [dict(r) for r in rows]


async def analyze_agent_weaknesses(pool: asyncpg.Pool, *, org_id: str, days: int = 30) -> list[dict]:
    """Rollup per-bot: rata-rata quality/confidence, tingkat verifikasi gagal & outcome buruk."""
    rows = await pool.fetch(
        """SELECT ca.bot_id, b.name AS bot_name,
                  COUNT(*)::int AS conversations,
                  ROUND(AVG(ca.quality_score), 2) AS avg_quality_score,
                  ROUND(AVG((ca.raw_metrics->>'confidence_score')::numeric), 1) AS avg_confidence,
                  COUNT(*) FILTER (WHERE ca.raw_metrics->>'verification_passed'='false')::int AS failed_verifications,
                  COUNT(*) FILTER (WHERE ca.outcome IN ('unresolved','abandoned','escalated'))::int AS bad_outcomes
           FROM conversation_analysis ca
           JOIN bots b ON b.id = ca.bot_id
           WHERE ca.org_id=$1 AND ca.analyzed_at >= NOW() - ($2::int * INTERVAL '1 day')
           GROUP BY ca.bot_id, b.name
           ORDER BY bad_outcomes DESC, failed_verifications DESC""",
        org_id, days,
    )
    return [dict(r) for r in rows]


# ============================================================
# RECOMMENDATION ENGINE
# ============================================================

async def generate_recommendations(pool: asyncpg.Pool, *, org_id: str, days: int = 30) -> list[dict]:
    """Hasilkan daftar rekomendasi (belum disimpan) berdasarkan hasil analisis."""
    recommendations: list[dict] = []

    for row in await analyze_low_confidence(pool, org_id=org_id, days=days):
        recommendations.append({
            "category": "knowledge_gap",
            "bot_id": row["bot_id"],
            "severity": _severity_for_count(row["count"]),
            "title": f"Confidence rendah untuk intent '{row['intent']}'",
            "description": (
                f"{row['count']} percakapan dengan intent '{row['intent']}' punya confidence "
                f"rata-rata {row['avg_confidence']} (di bawah ambang {LOW_CONFIDENCE_THRESHOLD}). "
                f"Tambahkan dokumen/FAQ yang membahas topik ini agar agent lebih yakin menjawab."
            ),
            "evidence": row,
            "dedup_key": f"knowledge_gap:low_confidence:{row['bot_id']}:{row['intent']}",
            "occurrence_count": row["count"],
        })

    for row in await analyze_negative_feedback(pool, org_id=org_id, days=days):
        recommendations.append({
            "category": "knowledge_gap",
            "bot_id": row["bot_id"],
            "severity": _severity_for_count(row["count"]),
            "title": "Pertanyaan dengan feedback negatif berulang",
            "description": (
                f"Pertanyaan \"{row['question']}\" mendapat feedback 'tidak membantu' "
                f"{row['count']}x. Tinjau & lengkapi knowledge base untuk pertanyaan ini."
            ),
            "evidence": row,
            "dedup_key": f"knowledge_gap:negative_feedback:{row['bot_id']}:{row['question'][:200]}",
            "occurrence_count": row["count"],
        })

    queue_category = {
        "knowledge": "knowledge_gap",
        "prompt": "prompt_improvement",
        "workflow": "workflow_improvement",
    }
    for row in await analyze_repeated_questions(pool, org_id=org_id, days=days):
        category = queue_category.get(row["action_type"], "knowledge_gap")
        recommendations.append({
            "category": category,
            "bot_id": row["bot_id"],
            "severity": _severity_for_count(row["occurrence_count"]),
            "title": f"Pertanyaan berulang belum terselesaikan ({row['occurrence_count']}x)",
            "description": row["failure_reason"] or (
                f"\"{row['question']}\" sudah {row['occurrence_count']}x masuk learning queue "
                f"tanpa diselesaikan."
            ),
            "evidence": row,
            "dedup_key": f"{category}:learning_queue:{row['bot_id']}:{row['question'][:200]}",
            "occurrence_count": row["occurrence_count"],
        })

    for row in await analyze_agent_weaknesses(pool, org_id=org_id, days=days):
        if row["conversations"] >= MIN_OCCURRENCES and row["failed_verifications"] >= MIN_OCCURRENCES:
            recommendations.append({
                "category": "prompt_improvement",
                "bot_id": row["bot_id"],
                "severity": _severity_for_count(row["failed_verifications"]),
                "title": f"Banyak jawaban gagal verifikasi kualitas — {row['bot_name']}",
                "description": (
                    f"{row['failed_verifications']} dari {row['conversations']} percakapan gagal "
                    f"verifikasi otomatis. Tinjau system prompt & instruksi agent '{row['bot_name']}'."
                ),
                "evidence": row,
                "dedup_key": f"prompt_improvement:verification:{row['bot_id']}",
                "occurrence_count": row["failed_verifications"],
            })

        avg_quality = row.get("avg_quality_score")
        if row["conversations"] >= MIN_OCCURRENCES and avg_quality is not None and float(avg_quality) < LOW_QUALITY_THRESHOLD:
            recommendations.append({
                "category": "agent_improvement",
                "bot_id": row["bot_id"],
                "severity": "high" if float(avg_quality) < 3 else "medium",
                "title": f"Skor kualitas agent di bawah rata-rata — {row['bot_name']}",
                "description": (
                    f"Rata-rata quality_score {avg_quality}/10 dari {row['conversations']} percakapan. "
                    f"Pertimbangkan tinjau reasoning_mode, model, atau tambah contoh percakapan untuk "
                    f"agent '{row['bot_name']}'."
                ),
                "evidence": row,
                "dedup_key": f"agent_improvement:quality:{row['bot_id']}",
                "occurrence_count": row["conversations"],
            })

    for row in await analyze_handoff_frequency(pool, org_id=org_id, days=days):
        if row["count"] >= MIN_OCCURRENCES:
            recommendations.append({
                "category": "workflow_improvement",
                "bot_id": row["bot_id"],
                "severity": _severity_for_count(row["count"]),
                "title": f"Frekuensi handoff tinggi: {row['reason']}",
                "description": (
                    f"{row['count']}x percakapan di-handoff ke manusia dengan alasan '{row['reason']}'. "
                    f"Pertimbangkan menambah/menyesuaikan workflow otomatis untuk skenario ini."
                ),
                "evidence": row,
                "dedup_key": f"workflow_improvement:handoff:{row['bot_id']}:{row['reason']}",
                "occurrence_count": row["count"],
            })

    for row in await analyze_failed_answers(pool, org_id=org_id, days=days):
        if row["count"] >= MIN_OCCURRENCES:
            recommendations.append({
                "category": "agent_improvement",
                "bot_id": row["bot_id"],
                "severity": _severity_for_count(row["count"]),
                "title": f"Pola jawaban gagal: intent '{row['intent']}' -> {row['outcome']}",
                "description": (
                    f"{row['count']}x percakapan dengan intent '{row['intent']}' berakhir "
                    f"'{row['outcome']}'. Tinjau alur agent (prompt/workflow) untuk intent ini."
                ),
                "evidence": row,
                "dedup_key": f"agent_improvement:outcome:{row['bot_id']}:{row['intent']}:{row['outcome']}",
                "occurrence_count": row["count"],
            })

    return recommendations


async def save_recommendations(pool: asyncpg.Pool, *, org_id: str, recommendations: list[dict]) -> int:
    """Upsert rekomendasi (idempotent via dedup_key). Status admin (reviewed/applied/dismissed) tidak ditimpa."""
    for rec in recommendations:
        await pool.execute(
            """INSERT INTO ai_improvement_recommendations
               (org_id, bot_id, category, severity, title, description, evidence, dedup_key, occurrence_count)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
               ON CONFLICT (org_id, dedup_key) DO UPDATE SET
                 severity=EXCLUDED.severity, title=EXCLUDED.title, description=EXCLUDED.description,
                 evidence=EXCLUDED.evidence, occurrence_count=EXCLUDED.occurrence_count, updated_at=NOW()""",
            org_id, rec.get("bot_id"), rec["category"], rec["severity"], rec["title"], rec["description"],
            json.dumps(rec["evidence"], default=str), rec["dedup_key"], rec["occurrence_count"],
        )
    return len(recommendations)


async def run_improvement_scan(pool: asyncpg.Pool, *, org_id: str, days: int = 30) -> dict:
    """Jalankan analisis penuh, simpan rekomendasi, dan catat di audit log."""
    recommendations = await generate_recommendations(pool, org_id=org_id, days=days)
    saved = await save_recommendations(pool, org_id=org_id, recommendations=recommendations)
    await write_audit_log(
        pool, org_id=org_id, actor_user_id=None, actor_email="system",
        action="create", resource_type="improvement_scan",
        metadata={"days": days, "recommendations_generated": saved},
    )
    return {"days": days, "recommendations_generated": saved, "recommendations": recommendations}


# ============================================================
# ROUTER
# ============================================================

class RecommendationUpdateRequest(BaseModel):
    status: str
    resolution_note: str | None = Field(default=None, max_length=4000)


def build_improvement_router(*, get_pool: GetPool, get_current_user: GetCurrentUser,
                              require_permission) -> APIRouter:
    router = APIRouter(prefix="/improvement", tags=["improvement"])

    @router.get("/dashboard")
    async def dashboard(
        user: Annotated[dict, Depends(require_permission("analytics.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        days: int = 30,
    ):
        days = max(1, min(365, days))
        org_id = user["org_id"]

        failed_answers = await analyze_failed_answers(pool, org_id=org_id, days=days)
        low_confidence = await analyze_low_confidence(pool, org_id=org_id, days=days)
        negative_feedback = await analyze_negative_feedback(pool, org_id=org_id, days=days)
        repeated_questions = await analyze_repeated_questions(pool, org_id=org_id, days=days)
        handoff_frequency = await analyze_handoff_frequency(pool, org_id=org_id, days=days)
        agent_weaknesses = await analyze_agent_weaknesses(pool, org_id=org_id, days=days)

        top_issues: list[dict] = []
        for row in failed_answers:
            top_issues.append({
                "type": "failed_answer", "bot_id": row["bot_id"], "count": row["count"],
                "title": f"Intent '{row['intent']}' berakhir '{row['outcome']}'",
            })
        for row in low_confidence:
            top_issues.append({
                "type": "low_confidence", "bot_id": row["bot_id"], "count": row["count"],
                "title": f"Confidence rendah pada intent '{row['intent']}' (avg {row['avg_confidence']})",
            })
        for row in negative_feedback:
            top_issues.append({
                "type": "negative_feedback", "bot_id": row["bot_id"], "count": row["count"],
                "title": f"Feedback negatif: \"{row['question'][:80]}\"",
            })
        for row in repeated_questions:
            top_issues.append({
                "type": "repeated_question", "bot_id": row["bot_id"], "count": row["occurrence_count"],
                "title": f"Pertanyaan berulang: \"{row['question'][:80]}\"",
            })
        for row in handoff_frequency:
            top_issues.append({
                "type": "handoff", "bot_id": row["bot_id"], "count": row["count"],
                "title": f"Handoff berulang: {row['reason']}",
            })
        top_issues.sort(key=lambda i: i["count"], reverse=True)

        rec_rows = await pool.fetch(
            """SELECT id, bot_id, category, severity, title, description, evidence,
                      occurrence_count, status, resolution_note, created_at, updated_at
               FROM ai_improvement_recommendations
               WHERE org_id=$1 ORDER BY
                 CASE status WHEN 'new' THEN 0 WHEN 'reviewed' THEN 1 ELSE 2 END,
                 CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                 occurrence_count DESC LIMIT 100""",
            org_id,
        )
        recommendations = [{**dict(r), "evidence": _jsonb(r["evidence"])} for r in rec_rows]
        knowledge_gaps = [r for r in recommendations if r["category"] == "knowledge_gap"]
        suggested_improvements = [r for r in recommendations if r["status"] in ("new", "reviewed")]

        last_scan = await pool.fetchrow(
            """SELECT created_at FROM audit_logs
               WHERE org_id=$1 AND resource_type='improvement_scan'
               ORDER BY created_at DESC LIMIT 1""",
            org_id,
        )

        return {
            "days": days,
            "summary": {
                "failed_answers": sum(r["count"] for r in failed_answers),
                "low_confidence": sum(r["count"] for r in low_confidence),
                "negative_feedback": sum(r["count"] for r in negative_feedback),
                "repeated_questions": len(repeated_questions),
                "handoffs": sum(r["count"] for r in handoff_frequency),
            },
            "top_issues": top_issues[:10],
            "knowledge_gaps": knowledge_gaps,
            "agent_weaknesses": agent_weaknesses,
            "suggested_improvements": suggested_improvements,
            "last_scan_at": last_scan["created_at"] if last_scan else None,
        }

    @router.get("/recommendations")
    async def list_recommendations(
        user: Annotated[dict, Depends(require_permission("analytics.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        category: str | None = None,
        status: str | None = None,
    ):
        conditions = ["org_id=$1"]
        args: list = [user["org_id"]]
        if category:
            if category not in RECOMMENDATION_CATEGORIES:
                raise HTTPException(422, "Kategori rekomendasi tidak valid")
            args.append(category)
            conditions.append(f"category=${len(args)}")
        if status:
            if status not in RECOMMENDATION_STATUSES:
                raise HTTPException(422, "Status rekomendasi tidak valid")
            args.append(status)
            conditions.append(f"status=${len(args)}")
        rows = await pool.fetch(
            f"""SELECT id, bot_id, category, severity, title, description, evidence,
                       occurrence_count, status, resolution_note, created_at, updated_at
                FROM ai_improvement_recommendations WHERE {' AND '.join(conditions)}
                ORDER BY CASE status WHEN 'new' THEN 0 WHEN 'reviewed' THEN 1 ELSE 2 END,
                         occurrence_count DESC LIMIT 100""",
            *args,
        )
        return {"recommendations": [{**dict(r), "evidence": _jsonb(r["evidence"])} for r in rows]}

    @router.patch("/recommendations/{rec_id}")
    async def update_recommendation(
        rec_id: str, body: RecommendationUpdateRequest,
        user: Annotated[dict, Depends(require_permission("settings.manage"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        if body.status not in RECOMMENDATION_STATUSES:
            raise HTTPException(422, "Status rekomendasi tidak valid")
        row = await pool.fetchrow(
            """UPDATE ai_improvement_recommendations
               SET status=$3, resolution_note=$4, reviewed_by=$5, reviewed_at=NOW(), updated_at=NOW()
               WHERE id=$1 AND org_id=$2
               RETURNING id, category, status, resolution_note, updated_at""",
            rec_id, user["org_id"], body.status, body.resolution_note, user.get("id"),
        )
        if not row:
            raise HTTPException(404, "Rekomendasi tidak ditemukan")
        await write_audit_log(
            pool, org_id=user["org_id"], actor_user_id=user.get("id"), actor_email=user.get("email"),
            action="update", resource_type="improvement_recommendation", resource_id=rec_id,
            metadata={"status": body.status},
        )
        return {"recommendation": dict(row)}

    @router.post("/scan")
    async def trigger_scan(
        user: Annotated[dict, Depends(require_permission("settings.manage"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        days: int = 30,
    ):
        _check_rate_limit(f"improvement:{user['org_id']}", 5)   # maks 5 scan/menit
        days = max(1, min(365, days))
        return await run_improvement_scan(pool, org_id=user["org_id"], days=days)

    return router
