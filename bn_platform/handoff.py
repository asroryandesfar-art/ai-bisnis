"""
bn_platform/handoff.py — Human Handoff Queue

Memutuskan kapan percakapan harus dialihkan dari AI ke agent manusia, lalu
mengelola antreannya (assign, prioritas, SLA, resolusi).

Kebijakan global (NEVER OFFER HUMAN HANDOFF UNLESS USER REQUESTS IT): AI
TIDAK PERNAH menawarkan handoff ke manusia kecuali salah satu dari 5
kategori di `handoff_guard.py` benar — permintaan eksplisit ke
manusia/admin/supervisor, refund, legal, billing dispute, atau masalah
kepemilikan/akses akun. Keputusan ini dibuat SATU KALI oleh Intent Router
(`supervisor.py::route_intent`, yang memanggil `handoff_guard.is_handoff_allowed()`)
dan diekspos sebagai `SupervisorResult.intent_routing["allow_human_handoff"]`
— fungsi `evaluate_handoff_trigger` di bawah ini HANYA menerjemahkan
keputusan itu menjadi prioritas antrean, dan TIDAK menduplikasi/menge-derive
ulang trigger-nya sendiri. confidence rendah, "AI tidak tahu", error
internal, user marah, urgency tinggi, atau banyak friction point BERTURUT-TURUT
TANPA salah satu dari 5 kategori itu BUKAN alasan untuk handoff — termasuk
backstop "heavy_complaint" yang DIHAPUS karena melanggar aturan ini (AI wajib
solve/explain/recommend/clarify dulu, bukan langsung handoff hanya karena
banyak friction point).

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

def evaluate_handoff_trigger(*, allow_human_handoff: bool,
                             handoff_reason: str | None,
                             escalation_urgency: str | None,
                             friction_points: list[str] | None) -> tuple[bool, str, str]:
    """
    Tentukan apakah percakapan ini perlu di-handoff ke manusia.
    Return (should_handoff, reason, priority).

    `allow_human_handoff` (dari Intent Router, lihat
    `supervisor.py::route_intent` -> `handoff_guard.is_handoff_allowed()`)
    adalah satu-satunya sumber kebenaran untuk "apakah user boleh ditawarkan
    handoff ke manusia" — true HANYA untuk salah satu dari 5 kategori di
    `handoff_guard.py` (permintaan eksplisit manusia/admin/supervisor,
    refund, legal, billing dispute, account ownership).

    confidence rendah, AI menjawab "tidak tahu", error internal, user marah,
    urgency tinggi, dan banyak friction point (`friction_points`, diterima
    untuk kompatibilitas pemanggil lama tapi TIDAK DIPAKAI lagi sebagai
    trigger) BUKAN alasan untuk menawarkan handoff.
    """
    if allow_human_handoff:
        priority = _URGENCY_TO_PRIORITY.get((escalation_urgency or "medium").lower(), "medium")
        if priority == "low":
            priority = "medium"
        return True, handoff_reason or "handoff_requested", priority

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

    conversation_id divalidasi dulu milik org_id yang sama sebelum ditulis --
    tanpa ini, caller yang salah pasangkan org_id/conversation_id (mis. lewat
    workflow_engine.py's "human_handoff" action node, dimana conversation_id
    bisa datang dari trigger_payload yang user-controlled lewat endpoint
    test-run) bisa menulis baris human_queue milik org lain dan menandai
    conversations.handoff_needed pada percakapan tenant lain.
    """
    conversation = await pool.fetchrow(
        "SELECT id FROM conversations WHERE id=$1 AND org_id=$2", conversation_id, org_id,
    )
    if not conversation:
        logger.warning(
            "enqueue_handoff: conversation_id=%s tidak ditemukan untuk org_id=%s, dilewati",
            conversation_id, org_id,
        )
        return None

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
    await pool.execute(
        "UPDATE conversations SET handoff_needed=TRUE WHERE id=$1 AND org_id=$2", conversation_id, org_id,
    )
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
