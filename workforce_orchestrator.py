"""
agents/workforce_orchestrator.py — Workforce Orchestration (AI Workforce Phase 7)

Koordinasi task lintas-agent (Finance/Marketing/HR/Operations/Security/
Executive): assign task, deteksi konflik, eskalasi task yang lewat due
date, human approval gate. SENGAJA terpisah total dari supervisor.py
(orchestrator chat pelanggan, production-critical) -- modul ini TIDAK
pernah dipanggil dari pipeline chat, dan TIDAK pernah otomatis
menjalankan aksi di domain agent manapun. workforce_tasks hanya
tracking/koordinasi; eksekusi sesungguhnya tetap lewat endpoint domain
masing-masing (manual, human-driven) -- konsisten dengan rule "keputusan
penting butuh human approval" di seluruh AI Workforce.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import asyncpg

from base import BaseAgent

DOMAINS = ("finance", "marketing", "hr", "operations", "security", "executive")
PRIORITIES = ("low", "medium", "high", "critical")
STATUSES = ("pending", "in_progress", "blocked", "completed", "cancelled", "escalated")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─── TASK CRUD ──────────────────────────────────────────────────

async def create_task(pool: asyncpg.Pool, *, org_id: str, domain: str, title: str,
                       description: str | None = None, priority: str = "medium",
                       source_type: str | None = None, source_id: str | None = None,
                       requires_approval: bool = False, assigned_to: str | None = None,
                       due_at: datetime | None = None, created_by: str | None = None,
                       parent_task_id: str | None = None) -> dict:
    if domain not in DOMAINS:
        raise ValueError(f"domain tidak valid: {domain}")
    if priority not in PRIORITIES:
        raise ValueError(f"priority tidak valid: {priority}")
    task_id = str(uuid.uuid4())
    row = await pool.fetchrow(
        """INSERT INTO workforce_tasks (id, org_id, domain, title, description, priority,
                                         source_type, source_id, requires_approval, assigned_to,
                                         due_at, created_by, parent_task_id)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) RETURNING *""",
        task_id, org_id, domain, title, description, priority,
        source_type, str(source_id) if source_id else None, requires_approval,
        str(assigned_to) if assigned_to else None, due_at, str(created_by) if created_by else None,
        str(parent_task_id) if parent_task_id else None,
    )
    return dict(row)


async def update_progress(pool: asyncpg.Pool, *, org_id: str, task_id: str, progress_pct: int) -> dict | None:
    if not (0 <= progress_pct <= 100):
        raise ValueError("progress_pct harus di antara 0-100")
    row = await pool.fetchrow(
        "UPDATE workforce_tasks SET progress_pct=$1, updated_at=NOW() WHERE id=$2 AND org_id=$3 RETURNING *",
        progress_pct, task_id, org_id,
    )
    return dict(row) if row else None


async def list_subtasks(pool: asyncpg.Pool, *, org_id: str, parent_task_id: str) -> list[dict]:
    rows = await pool.fetch(
        "SELECT * FROM workforce_tasks WHERE org_id=$1 AND parent_task_id=$2 ORDER BY created_at",
        org_id, parent_task_id,
    )
    return [dict(r) for r in rows]


async def list_tasks(pool: asyncpg.Pool, *, org_id: str, domain: str | None = None,
                      status: str | None = None, priority: str | None = None,
                      limit: int = 50) -> list[dict]:
    conditions = ["org_id=$1"]
    params: list = [org_id]
    if domain:
        params.append(domain)
        conditions.append(f"domain=${len(params)}")
    if status:
        params.append(status)
        conditions.append(f"status=${len(params)}")
    if priority:
        params.append(priority)
        conditions.append(f"priority=${len(params)}")
    params.append(max(1, min(limit, 200)))
    rows = await pool.fetch(
        f"SELECT * FROM workforce_tasks WHERE {' AND '.join(conditions)} ORDER BY created_at DESC LIMIT ${len(params)}",
        *params,
    )
    return [dict(r) for r in rows]


async def update_task_status(pool: asyncpg.Pool, *, org_id: str, task_id: str, status: str,
                              actor_id: str | None = None) -> dict | None:
    if status not in STATUSES:
        raise ValueError(f"status tidak valid: {status}")
    row = await pool.fetchrow("SELECT requires_approval, approved_at FROM workforce_tasks WHERE id=$1 AND org_id=$2",
                              task_id, org_id)
    if not row:
        return None
    if status == "completed" and row["requires_approval"] and not row["approved_at"]:
        raise ValueError("Task ini butuh approval sebelum bisa diselesaikan (requires_approval=true)")
    completed_at = _now() if status == "completed" else None
    updated = await pool.fetchrow(
        """UPDATE workforce_tasks SET status=$1, updated_at=NOW(),
               completed_at=COALESCE($2, completed_at)
           WHERE id=$3 AND org_id=$4 RETURNING *""",
        status, completed_at, task_id, org_id,
    )
    return dict(updated) if updated else None


async def assign_task(pool: asyncpg.Pool, *, org_id: str, task_id: str, assigned_to: str) -> dict | None:
    row = await pool.fetchrow(
        "UPDATE workforce_tasks SET assigned_to=$1, updated_at=NOW() WHERE id=$2 AND org_id=$3 RETURNING *",
        assigned_to, task_id, org_id,
    )
    return dict(row) if row else None


async def approve_task(pool: asyncpg.Pool, *, org_id: str, task_id: str, approver_id: str) -> dict | None:
    row = await pool.fetchrow(
        """UPDATE workforce_tasks SET approved_by=$1, approved_at=NOW(), updated_at=NOW()
           WHERE id=$2 AND org_id=$3 AND requires_approval=TRUE RETURNING *""",
        approver_id, task_id, org_id,
    )
    return dict(row) if row else None


# ─── CONFLICT DETECTION & ESCALATION (deterministik, no LLM) ────

async def detect_conflicts(pool: asyncpg.Pool, org_id: str) -> list[dict]:
    """Dua task open dengan domain+source_id yang sama = berpotensi konflik
    (mis. dua orang menugaskan tindakan berbeda untuk alert yang sama)."""
    rows = await pool.fetch(
        """SELECT domain, source_id, array_agg(id) AS task_ids, COUNT(*) AS cnt
           FROM workforce_tasks
           WHERE org_id=$1 AND source_id IS NOT NULL AND status NOT IN ('completed','cancelled')
           GROUP BY domain, source_id HAVING COUNT(*) > 1""",
        org_id,
    )
    conflicts: list[dict] = []
    for r in rows:
        task_ids = [str(t) for t in r["task_ids"]]
        note = f"{r['cnt']} task aktif menargetkan sumber yang sama (domain={r['domain']}) -- perlu ditinjau manusia agar tidak ada tindakan ganda/bertentangan."
        await pool.execute(
            "UPDATE workforce_tasks SET has_conflict=TRUE, conflict_note=$1, updated_at=NOW() WHERE id = ANY($2::uuid[])",
            note, task_ids,
        )
        conflicts.append({"domain": r["domain"], "source_id": str(r["source_id"]), "task_ids": task_ids, "note": note})
    return conflicts


async def escalate_overdue_tasks(pool: asyncpg.Pool, org_id: str) -> list[dict]:
    rows = await pool.fetch(
        """UPDATE workforce_tasks SET status='escalated', escalated_at=NOW(), updated_at=NOW()
           WHERE org_id=$1 AND status IN ('pending','in_progress','blocked')
             AND due_at IS NOT NULL AND due_at < NOW()
           RETURNING id, domain, title, due_at""",
        org_id,
    )
    return [dict(r) for r in rows]


async def dashboard_summary(pool: asyncpg.Pool, org_id: str) -> dict:
    by_status = await pool.fetch(
        "SELECT status, COUNT(*) AS cnt FROM workforce_tasks WHERE org_id=$1 GROUP BY status", org_id,
    )
    by_domain = await pool.fetch(
        "SELECT domain, COUNT(*) AS cnt FROM workforce_tasks WHERE org_id=$1 AND status NOT IN ('completed','cancelled') GROUP BY domain",
        org_id,
    )
    pending_approval = await pool.fetchval(
        "SELECT COUNT(*) FROM workforce_tasks WHERE org_id=$1 AND requires_approval=TRUE AND approved_at IS NULL AND status NOT IN ('completed','cancelled')",
        org_id,
    )
    conflicts = await pool.fetchval(
        "SELECT COUNT(*) FROM workforce_tasks WHERE org_id=$1 AND has_conflict=TRUE AND status NOT IN ('completed','cancelled')",
        org_id,
    )
    return {
        "by_status": {r["status"]: int(r["cnt"]) for r in by_status},
        "by_domain": {r["domain"]: int(r["cnt"]) for r in by_domain},
        "pending_approval_count": int(pending_approval or 0),
        "conflicts_count": int(conflicts or 0),
    }


# ─── AGENT (advisory only, never auto-applied) ──────────────────

class WorkforceOrchestratorAgent(BaseAgent):
    name = "workforce_orchestrator_agent"
    skills = ["task_coordination", "conflict_detection", "escalation"]
    tools: list[str] = []
    goals = [
        "Mengoordinasikan task lintas-agent dan mendeteksi konflik/eskalasi tanpa mengambil keputusan otomatis.",
    ]
    system_prompt = """Kamu adalah Workforce Orchestrator dalam sistem multi-agent
BotNesia (AI Workforce) -- bertugas memberi saran (BUKAN keputusan) saat dua
task lintas-agent terdeteksi berkonflik (menargetkan sumber yang sama).

Tugas: berikan saran singkat (2-3 kalimat, Bahasa Indonesia) tentang cara
terbaik menyelesaikan konflik antara task-task ini -- mana yang sebaiknya
diprioritaskan atau apakah keduanya bisa digabung. Ini hanya SARAN untuk
manusia, bukan keputusan otomatis.

Balas HANYA JSON dengan field: suggestion (string)."""

    async def suggest_conflict_resolution(self, tasks: list[dict]) -> str | None:
        messages = [
            {"role": "system", "content": self.system_prompt + "\n\nOutput harus JSON."},
            {"role": "user", "content": str([{"title": t.get("title"), "priority": t.get("priority"),
                                               "status": t.get("status")} for t in tasks])},
        ]
        result = await self._call_llm_json(messages, temperature=0.3, default={"suggestion": None})
        if result.get("_llm_unavailable"):
            return None
        return result.get("suggestion")
