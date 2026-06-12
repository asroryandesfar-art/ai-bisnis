"""
bn_platform/handoff.py — Human Handoff Queue

Memutuskan kapan percakapan harus dialihkan dari AI ke agent manusia, lalu
mengelola antreannya (assign, prioritas, SLA, resolusi). Trigger dievaluasi
dari hasil SupervisorResult (lihat supervisor.py) — TIDAK menduplikasi logic
EscalationAgent, hanya menambah lapisan keputusan "perlu antre ke manusia atau
tidak" + queue management yang EscalationAgent existing belum punya.

Trigger handoff (sesuai spesifikasi Phase 2 §3):
  • confidence rendah        -> cs_confidence < HANDOFF_CONFIDENCE_THRESHOLD
  • customer marah           -> sentiment.label in {"negative"} dgn score ekstrem,
                                atau urgency escalation >= "high"
  • komplain berat           -> EscalationAgent.should_escalate = True dgn
                                urgency "high"/"critical", atau banyak friction_points

Prioritas SLA (lihat bn_platform/config.py):
  urgent  -> respon dlm HANDOFF_SLA_MINUTES_URGENT menit (default 15)
  high    -> ... (default 60)
  medium  -> ... (default 240)
  low     -> ... (default 1440 / 1 hari)
"""
# from __future__ import annotations  # dihapus: menyebabkan Depends(closure_var) gagal di-resolve oleh FastAPI get_type_hints()

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from .config import cfg as platform_cfg

logger = logging.getLogger("bn_platform.handoff")

GetCurrentUser  = Callable[..., Awaitable[dict]]
GetPool         = Callable[..., Awaitable[asyncpg.Pool]]
DispatchWebhook = Callable[..., Awaitable[None]]

HANDOFF_CONFIDENCE_THRESHOLD = 0.45

_URGENCY_TO_PRIORITY = {
    "critical": "urgent",
    "high":     "high",
    "medium":   "medium",
    "low":      "low",
}

_SLA_MINUTES = {
    "urgent": "handoff_sla_minutes_urgent",
    "high":   "handoff_sla_minutes_high",
    "medium": "handoff_sla_minutes_medium",
    "low":    "handoff_sla_minutes_low",
}


# ============================================================
# TRIGGER EVALUATION
# ============================================================

def evaluate_handoff_trigger(*, confidence: float | None, sentiment: dict | None,
                             should_escalate: bool, escalation_urgency: str | None,
                             escalation_reason: str | None,
                             friction_points: list[str] | None,
                             user_message: str = "", final_answer: str = "",
                             errors: list[str] | None = None) -> tuple[bool, str, str]:
    """
    Tentukan apakah percakapan ini perlu di-handoff ke manusia.
    Return (should_handoff, reason, priority).
    """
    sentiment = sentiment or {}
    friction_points = friction_points or []
    errors = errors or []
    label = str(sentiment.get("label", "neutral")).lower()
    score = float(sentiment.get("score", 0.0) or 0.0)
    message = user_message.lower()
    answer = final_answer.lower()

    if errors:
        return True, "ai_error", "high"

    human_requests = (
        "minta manusia", "bicara dengan manusia", "bicara manusia",
        "hubungkan ke manusia", "cs manusia", "customer service",
        "live agent", "human agent", "tidak mau bot",
    )
    if any(term in message for term in human_requests):
        return True, "user_requested_human", "medium"

    unknown_answers = (
        "saya tidak tahu", "saya belum tahu", "tidak memiliki informasi",
        "informasi tersebut tidak tersedia", "saya tidak dapat memastikan",
        "saya tidak bisa memastikan", "di luar pengetahuan saya",
    )
    if any(term in answer for term in unknown_answers):
        return True, "ai_does_not_know", "medium"

    # 1) confidence rendah
    if confidence is not None and confidence < HANDOFF_CONFIDENCE_THRESHOLD:
        priority = "high" if confidence < 0.25 else "medium"
        return True, "low_confidence", priority

    # 2) customer marah (sentiment atau kata eksplisit)
    angry_terms = ("marah", "kecewa", "parah", "bodoh", "brengsek", "penipuan", "bohong")
    if any(term in message for term in angry_terms):
        return True, "angry_user", "high"
    if label in ("negative", "angry", "frustrated") and abs(score) >= 0.6:
        return True, "angry_sentiment", "high"

    # 3) komplain berat -> ikuti urgency dari EscalationAgent
    if should_escalate and escalation_urgency:
        priority = _URGENCY_TO_PRIORITY.get(escalation_urgency.lower(), "medium")
        if escalation_urgency.lower() in ("high", "critical"):
            return True, escalation_reason or "heavy_complaint", priority

    # 4) banyak friction point berturut -> indikasi komplain berat meski urgency belum tinggi
    if len(friction_points) >= 3:
        return True, "heavy_complaint", "medium"

    return False, "", "low"


def _sla_due_at(priority: str) -> datetime:
    minutes = getattr(platform_cfg, _SLA_MINUTES.get(priority, "handoff_sla_minutes_medium"))
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


# ============================================================
# REPOSITORY
# ============================================================

async def enqueue_handoff(pool: asyncpg.Pool, *, org_id: str, conversation_id: str,
                          reason: str, priority: str = "medium",
                          dispatch_webhook: DispatchWebhook | None = None) -> dict | None:
    """
    Masukkan percakapan ke antrean human handoff (idempotent — satu
    percakapan hanya boleh punya satu entri antrean aktif, lihat UNIQUE
    constraint di human_queue). Dipanggil fire-and-forget dari agent_api.py
    setelah SupervisorResult menyatakan should_escalate / confidence rendah.
    """
    sla_due = _sla_due_at(priority)
    row = await pool.fetchrow(
        """INSERT INTO human_queue (org_id, conversation_id, reason, priority, status, sla_due_at)
           VALUES ($1, $2, $3, $4, 'waiting', $5)
           ON CONFLICT (conversation_id) DO UPDATE SET
               reason = CASE WHEN human_queue.status IN ('resolved','cancelled') THEN EXCLUDED.reason
                             WHEN human_queue.status = 'waiting' THEN EXCLUDED.reason ELSE human_queue.reason END,
               priority = CASE
                   WHEN human_queue.status IN ('resolved','cancelled') THEN EXCLUDED.priority
                   WHEN CASE human_queue.priority WHEN 'urgent' THEN 4 WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END
                      >= CASE EXCLUDED.priority WHEN 'urgent' THEN 4 WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END
                   THEN human_queue.priority ELSE EXCLUDED.priority END,
               status = CASE WHEN human_queue.status IN ('resolved','cancelled') THEN 'waiting' ELSE human_queue.status END,
               assigned_agent_id = CASE WHEN human_queue.status IN ('resolved','cancelled') THEN NULL ELSE human_queue.assigned_agent_id END,
               assigned_at = CASE WHEN human_queue.status IN ('resolved','cancelled') THEN NULL ELSE human_queue.assigned_at END,
               resolved_at = CASE WHEN human_queue.status IN ('resolved','cancelled') THEN NULL ELSE human_queue.resolved_at END,
               resolution_note = CASE WHEN human_queue.status IN ('resolved','cancelled') THEN NULL ELSE human_queue.resolution_note END,
               sla_due_at = CASE WHEN human_queue.status IN ('resolved','cancelled') THEN EXCLUDED.sla_due_at ELSE human_queue.sla_due_at END
           RETURNING *""",
        org_id, conversation_id, reason, priority, sla_due,
    )
    await pool.execute("UPDATE conversations SET handoff_needed=TRUE WHERE id=$1", conversation_id)
    if row and dispatch_webhook:
        await dispatch_webhook(org_id, "handoff.created", {
            "queue_id": str(row["id"]), "conversation_id": conversation_id,
            "reason": reason, "priority": priority,
        }, pool)
    return dict(row) if row else None


async def list_queue(pool: asyncpg.Pool, *, org_id: str, status_filter: str | None = None,
                      assigned_to: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    conditions = ["hq.org_id = $1"]
    params: list = [org_id]
    if status_filter:
        params.append(status_filter)
        conditions.append(f"hq.status = ${len(params)}")
    if assigned_to:
        params.append(assigned_to)
        conditions.append(f"hq.assigned_agent_id = ${len(params)}")
    where = " AND ".join(conditions)
    params.extend([limit, offset])
    rows = await pool.fetch(
        f"""SELECT hq.*, c.end_user_name, c.end_user_id, c.last_msg_at, c.bot_id,
                   u.full_name AS assigned_agent_name, u.email AS assigned_agent_email
            FROM human_queue hq
            JOIN conversations c ON c.id = hq.conversation_id
            LEFT JOIN users u    ON u.id = hq.assigned_agent_id
            WHERE {where}
            ORDER BY
                CASE hq.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                hq.created_at ASC
            LIMIT ${len(params)-1} OFFSET ${len(params)}""",
        *params,
    )
    return [dict(r) for r in rows]


async def queue_stats(pool: asyncpg.Pool, *, org_id: str) -> dict:
    row = await pool.fetchrow(
        """SELECT
             COUNT(*) FILTER (WHERE status='waiting')                           AS waiting,
             COUNT(*) FILTER (WHERE status='assigned')                          AS assigned,
             COUNT(*) FILTER (WHERE status='resolved'
                              AND resolved_at >= NOW() - INTERVAL '24 hours')   AS resolved_24h,
             COUNT(*) FILTER (WHERE status='waiting' AND priority='urgent')     AS urgent_waiting,
             COUNT(*) FILTER (WHERE status IN ('waiting','assigned')
                              AND sla_due_at < NOW())                           AS sla_breached,
             ROUND(AVG(EXTRACT(EPOCH FROM (resolved_at - created_at))/60.0)
                   FILTER (WHERE status='resolved'
                           AND resolved_at >= NOW() - INTERVAL '7 days'), 1)    AS avg_resolution_minutes_7d
           FROM human_queue WHERE org_id=$1""",
        org_id,
    )
    return dict(row)


async def claim_item(pool: asyncpg.Pool, *, org_id: str, queue_id: str, agent_id: str,
                      dispatch_webhook: DispatchWebhook | None = None) -> dict:
    row = await pool.fetchrow(
        """UPDATE human_queue SET status='assigned', assigned_agent_id=$3, assigned_at=NOW()
           WHERE id=$1 AND org_id=$2 AND status='waiting'
           RETURNING *""",
        queue_id, org_id, agent_id,
    )
    if not row:
        raise HTTPException(status.HTTP_409_CONFLICT, "Item sudah ditangani agent lain atau tidak ditemukan")
    await pool.execute(
        "UPDATE conversations SET assigned_agent_id=$1 WHERE id=$2", agent_id, row["conversation_id"],
    )
    if dispatch_webhook:
        await dispatch_webhook(org_id, "handoff.assigned", {
            "queue_id": str(row["id"]), "conversation_id": str(row["conversation_id"]), "agent_id": agent_id,
        }, pool)
    return dict(row)


async def assign_item(pool: asyncpg.Pool, *, org_id: str, queue_id: str, agent_id: str,
                       dispatch_webhook: DispatchWebhook | None = None) -> dict:
    agent = await pool.fetchrow("SELECT id FROM users WHERE id=$1 AND org_id=$2 AND is_active", agent_id, org_id)
    if not agent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent tidak ditemukan di organisasi ini")
    row = await pool.fetchrow(
        """UPDATE human_queue SET status='assigned', assigned_agent_id=$3, assigned_at=NOW()
           WHERE id=$1 AND org_id=$2 AND status IN ('waiting','assigned')
           RETURNING *""",
        queue_id, org_id, agent_id,
    )
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item antrean tidak ditemukan")
    await pool.execute(
        "UPDATE conversations SET assigned_agent_id=$1 WHERE id=$2", agent_id, row["conversation_id"],
    )
    if dispatch_webhook:
        await dispatch_webhook(org_id, "handoff.assigned", {
            "queue_id": str(row["id"]), "conversation_id": str(row["conversation_id"]), "agent_id": agent_id,
        }, pool)
    return dict(row)


async def resolve_item(pool: asyncpg.Pool, *, org_id: str, queue_id: str, note: str | None,
                        dispatch_webhook: DispatchWebhook | None = None) -> dict:
    row = await pool.fetchrow(
        """UPDATE human_queue SET status='resolved', resolved_at=NOW(), resolution_note=$3
           WHERE id=$1 AND org_id=$2 AND status IN ('waiting','assigned')
           RETURNING *""",
        queue_id, org_id, note,
    )
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item antrean tidak ditemukan")
    await pool.execute(
        """UPDATE conversations
           SET handoff_needed=FALSE, assigned_agent_id=NULL, resolved=FALSE, closed_at=NULL
           WHERE id=$1""",
        row["conversation_id"],
    )
    if dispatch_webhook:
        await dispatch_webhook(org_id, "handoff.resolved", {
            "queue_id": str(row["id"]), "conversation_id": str(row["conversation_id"]),
        }, pool)
    return dict(row)


async def reply_to_item(pool: asyncpg.Pool, *, org_id: str, queue_id: str,
                        agent_id: str, message: str) -> dict:
    """Persist a human response while the conversation is assigned."""
    item = await pool.fetchrow(
        """SELECT id, conversation_id, status, assigned_agent_id
           FROM human_queue WHERE id=$1 AND org_id=$2""",
        queue_id, org_id,
    )
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item antrean tidak ditemukan")
    if item["status"] != "assigned" or str(item["assigned_agent_id"]) != str(agent_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Claim handoff sebelum mengirim balasan")
    row = await pool.fetchrow(
        """INSERT INTO messages (conversation_id, role, content, model)
           VALUES ($1, 'assistant', $2, $3)
           RETURNING id, conversation_id, role, content, model, created_at""",
        item["conversation_id"], message.strip(), f"human:{agent_id}",
    )
    await pool.execute(
        "UPDATE conversations SET msg_count=msg_count+1, last_msg_at=NOW() WHERE id=$1",
        item["conversation_id"],
    )
    return dict(row)


# ============================================================
# ROUTER
# ============================================================

class AssignReq(BaseModel):
    agent_id: str

class ResolveReq(BaseModel):
    note: str | None = None

class ReplyReq(BaseModel):
    message: str


def build_handoff_router(*, get_pool: GetPool, get_current_user: GetCurrentUser,
                          require_permission, dispatch_webhook: DispatchWebhook | None = None) -> APIRouter:
    router = APIRouter(prefix="/handoff", tags=["handoff"])

    @router.get("/queue")
    async def get_queue(
        user: Annotated[dict, Depends(require_permission("conversations.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        status_filter: str | None = None, assigned_to: str | None = None,
        limit: int = 50, offset: int = 0,
    ):
        items = await list_queue(pool, org_id=user["org_id"], status_filter=status_filter,
                                 assigned_to=assigned_to, limit=limit, offset=offset)
        return {"queue": items}

    @router.get("/stats")
    async def get_stats(
        user: Annotated[dict, Depends(require_permission("conversations.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        return {"stats": await queue_stats(pool, org_id=user["org_id"])}

    @router.get("/mine")
    async def my_queue(
        user: Annotated[dict, Depends(require_permission("conversations.reply"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        items = await list_queue(pool, org_id=user["org_id"], assigned_to=user["id"])
        return {"queue": items}

    @router.post("/{queue_id}/claim")
    async def claim(
        queue_id: str,
        user: Annotated[dict, Depends(require_permission("conversations.reply"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        item = await claim_item(pool, org_id=user["org_id"], queue_id=queue_id, agent_id=user["id"],
                                dispatch_webhook=dispatch_webhook)
        return {"queue_item": item}

    @router.post("/{queue_id}/assign")
    async def assign(
        queue_id: str, body: AssignReq,
        user: Annotated[dict, Depends(require_permission("conversations.assign"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        item = await assign_item(pool, org_id=user["org_id"], queue_id=queue_id, agent_id=body.agent_id,
                                 dispatch_webhook=dispatch_webhook)
        return {"queue_item": item}

    @router.post("/{queue_id}/resolve")
    async def resolve(
        queue_id: str, body: ResolveReq,
        user: Annotated[dict, Depends(require_permission("conversations.reply"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        item = await resolve_item(pool, org_id=user["org_id"], queue_id=queue_id, note=body.note,
                                  dispatch_webhook=dispatch_webhook)
        return {"queue_item": item}

    @router.post("/{queue_id}/reply")
    async def reply(
        queue_id: str, body: ReplyReq,
        user: Annotated[dict, Depends(require_permission("conversations.reply"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        if not body.message.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Pesan tidak boleh kosong")
        message = await reply_to_item(
            pool, org_id=user["org_id"], queue_id=queue_id,
            agent_id=user["id"], message=body.message,
        )
        return {"message": message}

    return router
