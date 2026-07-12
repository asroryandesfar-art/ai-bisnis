"""Read-only reporting routes (analytics, conversations, messages, routing logs,
message sources), extracted verbatim from main.py.

All are authenticated GETs that only need get_pool + get_current_user; no
platform hooks, no background work — a low-risk combined slice of the main.py
strangler split. Handlers are re-exposed by main for tests that call them
directly (e.g. test_analytics_org_isolation).
"""
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException


def build_reporting_router(
    *,
    get_pool: Callable[..., Awaitable],
    get_current_user: Callable[..., Awaitable[dict]],
) -> APIRouter:
    router = APIRouter()

    @router.get("/bots/{bot_id}/analytics")
    async def get_analytics(
        bot_id: str,
        days:   int = 30,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        bot = await pool.fetchrow(
            "SELECT id FROM bots WHERE id=$1 AND org_id=$2", bot_id, user["org_id"]
        )
        if not bot:
            raise HTTPException(404, "Bot tidak ditemukan")

        since = datetime.now(timezone.utc) - timedelta(days=days)

        # Summary
        summary = await pool.fetchrow(
            """SELECT
                 COUNT(DISTINCT c.id)                    AS total_convs,
                 COUNT(m.id)                             AS total_msgs,
                 ROUND(AVG(c.rating) FILTER
                   (WHERE c.rating IS NOT NULL), 2)      AS avg_rating,
                 AVG(m.latency_ms) FILTER
                   (WHERE m.role='assistant')            AS avg_latency_ms,
                 COUNT(c.id) FILTER
                   (WHERE c.handoff_needed)              AS handoff_count
               FROM conversations c
               LEFT JOIN messages m ON m.conversation_id = c.id
               WHERE c.bot_id=$1 AND c.org_id=$2 AND c.started_at >= $3""",
            bot_id, user["org_id"], since,
        )

        # Volume harian
        daily = await pool.fetch(
            """SELECT DATE(started_at) AS date, COUNT(*) AS convs
               FROM conversations WHERE bot_id=$1 AND org_id=$2 AND started_at >= $3
               GROUP BY DATE(started_at) ORDER BY date""",
            bot_id, user["org_id"], since,
        )

        # Top pertanyaan
        top_q = await pool.fetch(
            """SELECT m.content, COUNT(*) AS frequency
               FROM messages m
               JOIN conversations c ON c.id = m.conversation_id
               WHERE c.bot_id=$1 AND c.org_id=$2 AND m.role='user' AND m.created_at >= $3
               GROUP BY m.content ORDER BY frequency DESC LIMIT 10""",
            bot_id, user["org_id"], since,
        )

        return {
            "summary":       dict(summary),
            "daily_volume":  [dict(r) for r in daily],
            "top_questions": [dict(r) for r in top_q],
        }

    @router.get("/bots/{bot_id}/conversations")
    async def list_conversations(
        bot_id: str,
        limit:  int = 20,
        offset: int = 0,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        rows = await pool.fetch(
            """SELECT id, end_user_name, end_user_email, msg_count,
                      resolved, handoff_needed, rating, started_at, last_msg_at
               FROM conversations WHERE bot_id=$1 AND org_id=$2
               ORDER BY last_msg_at DESC LIMIT $3 OFFSET $4""",
            bot_id, user["org_id"], limit, offset,
        )
        return [dict(r) for r in rows]

    @router.get("/conversations/{conv_id}/messages")
    async def get_messages(
        conv_id: str,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        # Verifikasi kepemilikan
        conv = await pool.fetchrow(
            "SELECT id FROM conversations WHERE id=$1 AND org_id=$2",
            conv_id, user["org_id"],
        )
        if not conv:
            raise HTTPException(404, "Conversation tidak ditemukan")

        rows = await pool.fetch(
            """SELECT m.id, m.role, m.content, m.model, m.latency_ms, m.created_at, m.source_chunks,
                      m.intent, m.selected_agent, m.routing_confidence, m.handoff_status, m.allow_human_handoff,
                      fr.rating AS feedback_rating, fr.comment AS feedback_comment
               FROM messages m
               LEFT JOIN feedback_records fr ON fr.message_id=m.id AND fr.tenant_id=$2
               WHERE m.conversation_id=$1 ORDER BY m.created_at""",
            conv_id, user["org_id"],
        )
        return [dict(r) for r in rows]

    @router.get("/bots/{bot_id}/routing-logs")
    async def get_routing_logs(
        bot_id: str,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
        limit: int = 50,
        offset: int = 0,
    ):
        bot = await pool.fetchrow(
            "SELECT id FROM bots WHERE id=$1 AND org_id=$2",
            bot_id, user["org_id"],
        )
        if not bot:
            raise HTTPException(404, "Bot tidak ditemukan")
        rows = await pool.fetch(
            """SELECT m.id, m.conversation_id, m.content, m.intent, m.selected_agent,
                      m.routing_confidence, m.handoff_status, m.allow_human_handoff, m.created_at,
                      c.end_user_name, c.end_user_email
               FROM messages m
               JOIN conversations c ON c.id = m.conversation_id
               WHERE c.bot_id=$1 AND c.org_id=$2 AND m.role='assistant' AND m.intent IS NOT NULL
               ORDER BY m.created_at DESC LIMIT $3 OFFSET $4""",
            bot_id, user["org_id"], limit, offset,
        )
        return {"logs": [dict(r) for r in rows]}

    @router.get("/messages/{message_id}/sources")
    async def get_message_sources(
        message_id: str,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        msg = await pool.fetchrow(
            """
            SELECT m.id, m.source_chunks, c.org_id
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE m.id=$1 AND c.org_id=$2
            """,
            message_id,
            user["org_id"],
        )
        if not msg:
            raise HTTPException(404, "Message tidak ditemukan")

        chunk_ids = msg["source_chunks"] or []
        if not chunk_ids:
            return []

        rows = await pool.fetch(
            """
            SELECT id, content, document_id, chunk_index, created_at
            FROM doc_chunks
            WHERE org_id=$1 AND id = ANY($2::uuid[])
            ORDER BY chunk_index ASC
            """,
            user["org_id"],
            chunk_ids,
        )
        # Attach filename
        doc_ids = list({str(r["document_id"]) for r in rows if r.get("document_id")})
        name_map = {}
        if doc_ids:
            docs = await pool.fetch(
                "SELECT id, filename FROM documents WHERE org_id=$1 AND id = ANY($2::uuid[])",
                user["org_id"],
                doc_ids,
            )
            name_map = {str(d["id"]): d["filename"] for d in docs}

        out = []
        for r in rows:
            d_id = str(r["document_id"])
            out.append(
                {
                    "chunk_id": str(r["id"]),
                    "document_id": d_id,
                    "filename": name_map.get(d_id),
                    "chunk_index": int(r["chunk_index"]),
                    "content": (r["content"] or "")[:1200],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
            )
        return out

    return router
