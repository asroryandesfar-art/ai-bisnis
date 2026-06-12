"""Tenant-scoped user feedback analytics and actionable AI learning queue."""
from __future__ import annotations

from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

GetPool = Callable[..., Awaitable[asyncpg.Pool]]
GetCurrentUser = Callable[..., Awaitable[dict]]


class FeedbackRequest(BaseModel):
    message_id: str
    conversation_id: str
    rating: str
    comment: str | None = Field(default=None, max_length=2000)


class QueueUpdateRequest(BaseModel):
    status: str
    resolution_note: str | None = Field(default=None, max_length=4000)


def classify_learning_action(*, answer: str, model: str | None,
                             source_chunks: list | None) -> tuple[str, str]:
    text = (answer or "").lower()
    model_name = (model or "").lower()
    unknown_markers = (
        "saya tidak tahu", "saya belum tahu", "tidak memiliki informasi",
        "informasi tersebut tidak tersedia", "di luar pengetahuan saya",
    )
    if "handoff" in model_name or "error" in model_name:
        return "workflow", "Alur agent/provider perlu diperbaiki agar request tidak gagal."
    if any(marker in text for marker in unknown_markers) or not source_chunks:
        return "knowledge", "Jawaban memerlukan sumber knowledge yang lebih lengkap."
    return "prompt", "Instruksi atau contoh jawaban perlu diperbaiki berdasarkan feedback pengguna."


async def record_feedback(pool: asyncpg.Pool, *, tenant_id: str, body: FeedbackRequest) -> dict:
    rating = body.rating.strip().lower()
    if rating not in {"helpful", "not_helpful"}:
        raise HTTPException(422, "rating harus helpful atau not_helpful")

    message = await pool.fetchrow(
        """SELECT m.id, m.content AS answer, m.model, m.source_chunks,
                  c.id AS conversation_id, c.bot_id, c.org_id,
                  (SELECT content FROM messages q
                   WHERE q.conversation_id=c.id AND q.role='user' AND q.created_at <= m.created_at
                   ORDER BY q.created_at DESC LIMIT 1) AS question
           FROM messages m
           JOIN conversations c ON c.id=m.conversation_id
           WHERE m.id=$1 AND m.conversation_id=$2 AND c.org_id=$3 AND m.role='assistant'""",
        body.message_id, body.conversation_id, tenant_id,
    )
    if not message:
        raise HTTPException(404, "Jawaban AI tidak ditemukan")

    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """INSERT INTO feedback_records
                   (tenant_id, conversation_id, message_id, bot_id, rating, comment, question, answer)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                   ON CONFLICT (message_id) DO UPDATE SET
                     rating=EXCLUDED.rating, comment=EXCLUDED.comment,
                     question=EXCLUDED.question, answer=EXCLUDED.answer, created_at=NOW()
                   RETURNING id, tenant_id, conversation_id, message_id, rating, comment, created_at""",
                tenant_id, body.conversation_id, body.message_id, message["bot_id"],
                rating, body.comment, message["question"] or "", message["answer"] or "",
            )
            if rating == "not_helpful":
                action_type, gap_reason = classify_learning_action(
                    answer=message["answer"] or "", model=message["model"],
                    source_chunks=message["source_chunks"],
                )
                await conn.execute(
                    """INSERT INTO feedback_learning_queue
                       (tenant_id, bot_id, conversation_id, message_id, feedback_id,
                        question, answer, failure_reason, action_type, status, occurrence_count)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'pending',1)
                       ON CONFLICT (message_id) DO UPDATE SET
                         feedback_id=EXCLUDED.feedback_id, question=EXCLUDED.question,
                         answer=EXCLUDED.answer, failure_reason=EXCLUDED.failure_reason,
                         action_type=EXCLUDED.action_type, status='pending',
                         updated_at=NOW()""",
                    tenant_id, message["bot_id"], body.conversation_id, body.message_id,
                    row["id"], message["question"] or "", message["answer"] or "",
                    body.comment or gap_reason, action_type,
                )
            else:
                await conn.execute(
                    """UPDATE feedback_learning_queue SET status='dismissed', updated_at=NOW()
                       WHERE message_id=$1 AND tenant_id=$2 AND status='pending'""",
                    body.message_id, tenant_id,
                )
    return dict(row)


def build_feedback_learning_router(*, get_pool: GetPool,
                                   get_current_user: GetCurrentUser) -> APIRouter:
    router = APIRouter(prefix="/feedback-learning", tags=["feedback-learning"])

    @router.post("/feedback")
    async def submit_feedback(
        body: FeedbackRequest,
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        return {"feedback": await record_feedback(pool, tenant_id=user["org_id"], body=body)}

    @router.post("/public/{bot_id}")
    async def submit_public_feedback(
        bot_id: str, body: FeedbackRequest,
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        tenant_id = await pool.fetchval(
            """SELECT c.org_id FROM messages m
               JOIN conversations c ON c.id=m.conversation_id
               JOIN bots b ON b.id=c.bot_id
               WHERE b.id=$1 AND b.status <> 'inactive' AND c.id=$2 AND m.id=$3""",
            bot_id, body.conversation_id, body.message_id,
        )
        if not tenant_id:
            raise HTTPException(404, "Jawaban AI tidak ditemukan")
        return {"feedback": await record_feedback(pool, tenant_id=str(tenant_id), body=body)}

    @router.get("/summary")
    async def summary(
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        days: int = 30,
    ):
        days = max(1, min(365, days))
        tenant_id = user["org_id"]
        totals = await pool.fetchrow(
            """SELECT COUNT(*)::int AS total,
                      COUNT(*) FILTER (WHERE rating='helpful')::int AS helpful,
                      COUNT(*) FILTER (WHERE rating='not_helpful')::int AS not_helpful
               FROM feedback_records
               WHERE tenant_id=$1 AND created_at >= NOW()-($2::int * INTERVAL '1 day')""",
            tenant_id, days,
        )
        top_positive = await pool.fetch(
            """SELECT question, answer, comment, COUNT(*)::int AS feedback_count, MAX(created_at) AS last_seen
               FROM feedback_records WHERE tenant_id=$1 AND rating='helpful'
                 AND created_at >= NOW()-($2::int * INTERVAL '1 day')
               GROUP BY question, answer, comment ORDER BY feedback_count DESC, last_seen DESC LIMIT 10""",
            tenant_id, days,
        )
        top_negative = await pool.fetch(
            """SELECT question, answer, comment, COUNT(*)::int AS feedback_count, MAX(created_at) AS last_seen
               FROM feedback_records WHERE tenant_id=$1 AND rating='not_helpful'
                 AND created_at >= NOW()-($2::int * INTERVAL '1 day')
               GROUP BY question, answer, comment ORDER BY feedback_count DESC, last_seen DESC LIMIT 10""",
            tenant_id, days,
        )
        failed_questions = await pool.fetch(
            """SELECT question, COUNT(*)::int AS failure_count, MAX(created_at) AS last_failed
               FROM feedback_records WHERE tenant_id=$1 AND rating='not_helpful'
                 AND created_at >= NOW()-($2::int * INTERVAL '1 day')
               GROUP BY question ORDER BY failure_count DESC, last_failed DESC LIMIT 10""",
            tenant_id, days,
        )
        gaps = await pool.fetch(
            """SELECT action_type, question, failure_reason, occurrence_count, status, updated_at
               FROM feedback_learning_queue WHERE tenant_id=$1 AND action_type='knowledge'
                 AND status IN ('pending','in_progress')
               ORDER BY occurrence_count DESC, updated_at DESC LIMIT 20""",
            tenant_id,
        )
        queue_stats = await pool.fetchrow(
            """SELECT COUNT(*) FILTER (WHERE status='pending')::int AS pending,
                      COUNT(*) FILTER (WHERE status='in_progress')::int AS in_progress,
                      COUNT(*) FILTER (WHERE status='resolved')::int AS resolved
               FROM feedback_learning_queue WHERE tenant_id=$1""",
            tenant_id,
        )
        total = int(totals["total"] or 0)
        helpful = int(totals["helpful"] or 0)
        return {
            "days": days, "total_feedback": total, "helpful": helpful,
            "not_helpful": int(totals["not_helpful"] or 0),
            "helpful_rate": round(100 * helpful / total, 1) if total else 0,
            "top_positive_feedback": [dict(row) for row in top_positive],
            "top_negative_feedback": [dict(row) for row in top_negative],
            "most_failed_questions": [dict(row) for row in failed_questions],
            "knowledge_gaps": [dict(row) for row in gaps],
            "queue": dict(queue_stats),
        }

    @router.get("/queue")
    async def queue(
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        status: str | None = None,
    ):
        conditions = ["tenant_id=$1"]
        args: list = [user["org_id"]]
        if status:
            if status not in {"pending", "in_progress", "resolved", "dismissed"}:
                raise HTTPException(422, "Status learning queue tidak valid")
            args.append(status)
            conditions.append(f"status=${len(args)}")
        rows = await pool.fetch(
            f"""SELECT id, bot_id, conversation_id, message_id, question, answer,
                       failure_reason, action_type, status, occurrence_count,
                       resolution_note, created_at, updated_at
                FROM feedback_learning_queue WHERE {' AND '.join(conditions)}
                ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END,
                         occurrence_count DESC, updated_at DESC LIMIT 100""",
            *args,
        )
        return {"queue": [dict(row) for row in rows]}

    @router.patch("/queue/{item_id}")
    async def update_queue(
        item_id: str, body: QueueUpdateRequest,
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        if body.status not in {"pending", "in_progress", "resolved", "dismissed"}:
            raise HTTPException(422, "Status learning queue tidak valid")
        row = await pool.fetchrow(
            """UPDATE feedback_learning_queue
               SET status=$3, resolution_note=$4, updated_at=NOW(),
                   resolved_at=CASE WHEN $3='resolved' THEN NOW() ELSE resolved_at END
               WHERE id=$1 AND tenant_id=$2
               RETURNING id, status, resolution_note, updated_at, resolved_at""",
            item_id, user["org_id"], body.status, body.resolution_note,
        )
        if not row:
            raise HTTPException(404, "Learning item tidak ditemukan")
        return {"item": dict(row)}

    return router
