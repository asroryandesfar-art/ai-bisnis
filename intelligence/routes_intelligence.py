"""
intelligence/routes_intelligence.py — FastAPI router `/intel/*`

Diregistrasi ke `agent_api.py` lewat:
    from intelligence.routes_intelligence import intel_router
    app.include_router(intel_router)

Semua endpoint memakai header `x-agent-secret` yang sama dengan `/process`
(satu sumber otorisasi — lihat intelligence/config.py: agent_secret dibaca
dari env AGENT_SECRET yang sama).
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from . import knowledge_agent, reports
from .config import cfg
from .conversation_memory import persist_conversation, search_similar_conversations
from .db import get_pool

intel_router = APIRouter(prefix="/intel", tags=["intelligence"])


def _check_secret(x_agent_secret: str) -> None:
    if not cfg.agent_secret or x_agent_secret != cfg.agent_secret:
        raise HTTPException(401, "Secret tidak valid")


# ════════════════════════════════════════════════════════════════
# CONVERSATION MEMORY
# ════════════════════════════════════════════════════════════════

class PersistConversationRequest(BaseModel):
    """
    Dipakai untuk backfill/replay (bukan jalur realtime — itu dipanggil
    in-process dari agent_api.process_message). Bentuknya sengaja mengikuti
    parameter `conversation_memory.persist_conversation`.
    """
    context: dict
    bot_response: str
    sentiment: dict = {"label": "neutral", "score": 0.0}
    intent: str = "unknown"
    topics: list[str] = []
    resolved: bool = False
    should_escalate: bool = False
    friction_points: list[str] = []
    quality_score: float = 0.0


@intel_router.post("/conversations/{conv_id}/persist")
async def persist_conversation_route(
    conv_id: str,
    body: PersistConversationRequest,
    x_agent_secret: str = Header(default=""),
):
    _check_secret(x_agent_secret)
    body.context.setdefault("conversation_id", conv_id)
    try:
        result = await persist_conversation(
            body.context,
            bot_response=body.bot_response,
            sentiment=body.sentiment,
            intent=body.intent,
            topics=body.topics,
            resolved=body.resolved,
            should_escalate=body.should_escalate,
            friction_points=body.friction_points,
            quality_score=body.quality_score,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return result


@intel_router.get("/conversations/search")
async def search_conversations_route(
    bot_id: str = Query(...),
    q: str = Query(..., min_length=2),
    limit: int = Query(default=5, ge=1, le=50),
    x_agent_secret: str = Header(default=""),
):
    """Semantic search percakapan mirip — query bahasa natural -> embedding -> pgvector ANN."""
    _check_secret(x_agent_secret)
    results = await search_similar_conversations(bot_id, q, limit=limit)
    return {"bot_id": bot_id, "query": q, "total": len(results), "results": results}


# ════════════════════════════════════════════════════════════════
# FAQ ENGINE
# ════════════════════════════════════════════════════════════════

@intel_router.get("/faq/{bot_id}")
async def list_faq_route(
    bot_id: str,
    sort: str = Query(default="frequency", pattern="^(frequency|success|conversion|recent)$"),
    limit: int = Query(default=50, ge=1, le=200),
    x_agent_secret: str = Header(default=""),
):
    _check_secret(x_agent_secret)
    order_by = {
        "frequency":  "frequency_score DESC",
        "success":    "success_score DESC",
        "conversion": "conversion_score DESC",
        "recent":     "updated_at DESC",
    }[sort]
    pool = await get_pool()
    rows = await pool.fetch(
        f"""SELECT id, question, answer, topic, frequency_score, success_score,
                   conversion_score, status, last_seen_at, updated_at
            FROM faq_entries
            WHERE bot_id = $1 AND status != 'archived'
            ORDER BY {order_by}
            LIMIT $2""",
        bot_id, limit,
    )
    return {"bot_id": bot_id, "total": len(rows), "faqs": [dict(r) for r in rows]}


@intel_router.post("/faq/{bot_id}/rebuild")
async def rebuild_faq_route(bot_id: str, x_agent_secret: str = Header(default="")):
    """Trigger manual clustering FAQ (selain berjalan otomatis tiap malam)."""
    _check_secret(x_agent_secret)
    from . import faq_agent
    pool = await get_pool()
    org_row = await pool.fetchrow("SELECT org_id FROM bots WHERE id = $1", bot_id)
    if not org_row:
        raise HTTPException(404, "Bot tidak ditemukan")
    cluster_result = await faq_agent.cluster_new_questions(bot_id, str(org_row["org_id"]))
    rescored = await faq_agent.recompute_scores(bot_id)
    return {"bot_id": bot_id, **cluster_result, "rescored": rescored}


# ════════════════════════════════════════════════════════════════
# SALES INTELLIGENCE
# ════════════════════════════════════════════════════════════════

@intel_router.get("/sales/{bot_id}/patterns")
async def list_sales_patterns_route(
    bot_id: str,
    pattern_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    x_agent_secret: str = Header(default=""),
):
    _check_secret(x_agent_secret)
    pool = await get_pool()
    if pattern_type:
        rows = await pool.fetch(
            """SELECT id, pattern_type, trigger_text, objection_text, solution_text,
                      occurrences, conversions, conversion_rate, confidence_score, last_seen_at
               FROM sales_patterns WHERE bot_id = $1 AND pattern_type = $2
               ORDER BY occurrences DESC LIMIT $3""",
            bot_id, pattern_type, limit,
        )
    else:
        rows = await pool.fetch(
            """SELECT id, pattern_type, trigger_text, objection_text, solution_text,
                      occurrences, conversions, conversion_rate, confidence_score, last_seen_at
               FROM sales_patterns WHERE bot_id = $1
               ORDER BY occurrences DESC LIMIT $2""",
            bot_id, limit,
        )
    return {"bot_id": bot_id, "total": len(rows), "patterns": [dict(r) for r in rows]}


@intel_router.get("/sales/{bot_id}/objections")
async def top_objections_route(
    bot_id: str,
    limit: int = Query(default=10, ge=1, le=50),
    x_agent_secret: str = Header(default=""),
):
    _check_secret(x_agent_secret)
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT pattern_type, objection_text, solution_text,
                  occurrences, conversion_rate, confidence_score
           FROM sales_patterns
           WHERE bot_id = $1 AND pattern_type LIKE 'objection_%'
           ORDER BY occurrences DESC LIMIT $2""",
        bot_id, limit,
    )
    return {"bot_id": bot_id, "total": len(rows), "objections": [dict(r) for r in rows]}


# ════════════════════════════════════════════════════════════════
# KNOWLEDGE GRAPH
# ════════════════════════════════════════════════════════════════

@intel_router.get("/knowledge-graph/{bot_id}")
async def knowledge_graph_route(
    bot_id: str,
    node_type: str | None = Query(default=None),
    limit: int = Query(default=200, ge=10, le=1000),
    x_agent_secret: str = Header(default=""),
):
    _check_secret(x_agent_secret)
    return {"bot_id": bot_id, **(await knowledge_agent.get_subgraph(bot_id, node_type=node_type, limit=limit))}


@intel_router.get("/knowledge-graph/{bot_id}/related/{node_id}")
async def knowledge_graph_related_route(
    bot_id: str,
    node_id: str,
    hops: int = Query(default=1, ge=1, le=2),
    limit: int = Query(default=50, ge=1, le=200),
    x_agent_secret: str = Header(default=""),
):
    _check_secret(x_agent_secret)
    return {"bot_id": bot_id, **(await knowledge_agent.get_related_nodes(bot_id, node_id, hops=hops, limit=limit))}


# ════════════════════════════════════════════════════════════════
# ANALYTICS DASHBOARD
# ════════════════════════════════════════════════════════════════

@intel_router.get("/dashboard/{bot_id}")
async def dashboard_route(bot_id: str, x_agent_secret: str = Header(default="")):
    _check_secret(x_agent_secret)
    pool = await get_pool()

    total_conversations = await pool.fetchval(
        "SELECT COUNT(*) FROM conversation_analysis WHERE bot_id = $1", bot_id,
    )
    faq_generated = await pool.fetchval(
        "SELECT COUNT(*) FROM faq_entries WHERE bot_id = $1 AND status != 'archived'", bot_id,
    )
    top_intents = await pool.fetch(
        """SELECT intent, COUNT(*) AS cnt FROM conversation_analysis
           WHERE bot_id = $1 AND intent IS NOT NULL
           GROUP BY intent ORDER BY cnt DESC LIMIT 10""",
        bot_id,
    )
    satisfaction = await pool.fetchrow(
        """SELECT
               COUNT(*) FILTER (WHERE outcome = 'resolved')::FLOAT / NULLIF(COUNT(*), 0) AS satisfaction_rate,
               COUNT(*) FILTER (WHERE purchase_status = 'purchased')::FLOAT / NULLIF(COUNT(*), 0) AS conversion_rate,
               COUNT(*) FILTER (WHERE purchase_status = 'purchased') AS purchased_count
           FROM conversation_analysis WHERE bot_id = $1""",
        bot_id,
    )

    # Revenue impact: jumlah percakapan converted × rata-rata nilai transaksi
    # tercatat (conversations.revenue_amount). Fallback 0 bila data tak ada.
    avg_revenue = await pool.fetchval(
        """SELECT AVG(revenue_amount) FROM conversations
           WHERE bot_id = $1 AND revenue_amount IS NOT NULL""",
        bot_id,
    )
    purchased_count = (satisfaction["purchased_count"] if satisfaction else 0) or 0
    revenue_impact_estimate = round(float(avg_revenue or 0) * purchased_count, 2)

    week_ago = date.today() - timedelta(days=7)
    faq_new_week = await pool.fetchval(
        "SELECT COUNT(*) FROM faq_entries WHERE bot_id = $1 AND created_at >= $2", bot_id, week_ago,
    )
    patterns_new_week = await pool.fetchval(
        "SELECT COUNT(*) FROM sales_patterns WHERE bot_id = $1 AND created_at >= $2", bot_id, week_ago,
    )
    kg_nodes_total = await pool.fetchval("SELECT COUNT(*) FROM kg_nodes WHERE bot_id = $1", bot_id)
    kg_edges_total = await pool.fetchval("SELECT COUNT(*) FROM kg_edges WHERE bot_id = $1", bot_id)

    return {
        "bot_id": bot_id,
        "total_conversations": total_conversations or 0,
        "faq_generated": faq_generated or 0,
        "top_intents": [{"intent": r["intent"], "count": r["cnt"]} for r in top_intents],
        "satisfaction_rate": round(float(satisfaction["satisfaction_rate"] or 0), 3) if satisfaction else 0,
        "conversion_rate": round(float(satisfaction["conversion_rate"] or 0), 3) if satisfaction else 0,
        "revenue_impact_estimate": revenue_impact_estimate,
        "knowledge_growth": {
            "faq_new_this_week": faq_new_week or 0,
            "sales_patterns_new_this_week": patterns_new_week or 0,
            "kg_nodes_total": kg_nodes_total or 0,
            "kg_edges_total": kg_edges_total or 0,
        },
    }


# ════════════════════════════════════════════════════════════════
# AUTO-LEARNING REPORTS
# ════════════════════════════════════════════════════════════════

@intel_router.get("/reports/{bot_id}/daily")
async def daily_report_route(bot_id: str, x_agent_secret: str = Header(default="")):
    _check_secret(x_agent_secret)
    report = await reports.get_latest_report(bot_id)
    if not report:
        return {"bot_id": bot_id, "report": None, "message": "Belum ada laporan — job malam belum berjalan."}
    return {"bot_id": bot_id, "report": report}


@intel_router.post("/learning/run")
async def trigger_learning_route(
    bot_id: str | None = Query(default=None),
    x_agent_secret: str = Header(default=""),
):
    """Trigger manual job Auto-Learning (admin/debug) — tidak menunggu jadwal Celery beat."""
    _check_secret(x_agent_secret)
    from .nightly_jobs import run_daily_learning
    return await run_daily_learning(bot_id)


# ════════════════════════════════════════════════════════════════
# CUSTOMER INTELLIGENCE
# ════════════════════════════════════════════════════════════════

@intel_router.get("/customers/{bot_id}/{end_user_id}")
async def customer_profile_route(bot_id: str, end_user_id: str, x_agent_secret: str = Header(default="")):
    _check_secret(x_agent_secret)
    pool = await get_pool()
    profile = await pool.fetchrow(
        "SELECT * FROM customer_profiles WHERE bot_id = $1 AND end_user_id = $2",
        bot_id, end_user_id,
    )
    if not profile:
        raise HTTPException(404, "Profil pelanggan belum tersedia")
    facts = await pool.fetch(
        "SELECT fact_key, fact_value, confidence, source, times_used FROM customer_facts WHERE profile_id = $1",
        profile["id"],
    )
    recent = await pool.fetch(
        """SELECT conversation_id, intent, sentiment_label, outcome, purchase_status, summary, analyzed_at
           FROM conversation_analysis
           WHERE bot_id = $1 AND end_user_id = $2
           ORDER BY analyzed_at DESC LIMIT 10""",
        bot_id, end_user_id,
    )
    d = dict(profile)
    d["id"] = str(d["id"])
    return {
        "profile": d,
        "facts": [dict(f) for f in facts],
        "recent_conversations": [dict(r) for r in recent],
    }
