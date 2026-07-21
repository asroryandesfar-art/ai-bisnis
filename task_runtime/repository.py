"""task_runtime.repository — akses data durable job (P0-D D1).

Operasi atomik untuk agent_jobs / agent_job_steps. Klaim job pakai
`FOR UPDATE SKIP LOCKED` supaya banyak worker tak merebut job yang sama.
Pool utama TIDAK punya jsonb codec → kolom JSONB dibaca sebagai string →
di-parse via `_load_json` (pola sama casper_engineer_router)."""
from __future__ import annotations

import json
from typing import Any

import asyncpg


def _load_json(value: Any, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _job_row(row: asyncpg.Record | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    d["id"] = str(d["id"])
    d["org_id"] = str(d["org_id"])
    if d.get("bot_id") is not None:
        d["bot_id"] = str(d["bot_id"])
    if d.get("result_execution_id") is not None:
        d["result_execution_id"] = str(d["result_execution_id"])
    d["ctx"] = _load_json(d.get("ctx"), {})
    for k in ("created_at", "updated_at", "lease_until"):
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    return d


def _step_row(row: asyncpg.Record) -> dict:
    d = dict(row)
    d["id"] = str(d["id"])
    d["job_id"] = str(d["job_id"])
    d["checkpoint"] = _load_json(d.get("checkpoint"), None)
    d["output"] = _load_json(d.get("output"), None)
    d["tool_calls"] = _load_json(d.get("tool_calls"), None)
    for k in ("started_at", "ended_at"):
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    return d


_JOB_COLS = ("id, org_id, bot_id, agent_name, goal, ctx, status, priority, "
             "progress_pct, attempts, max_attempts, step_timeout_s, max_duration_s, "
             "lease_owner, lease_until, dlq_reason, last_error, idempotency_key, "
             "result_execution_id, created_at, updated_at")


class JobRepository:
    """Repository durable job. Semua method async; stateless (pool per-call)."""

    async def enqueue(self, pool: asyncpg.Pool, *, org_id: str, agent_name: str, goal: str,
                      ctx: dict | None = None, bot_id: str | None = None, priority: int = 5,
                      max_attempts: int = 3, step_timeout_s: int = 120, max_duration_s: int = 3600,
                      idempotency_key: str | None = None) -> dict:
        """Antre job baru. Bila idempotency_key sudah ada untuk org → kembalikan job
        yang lama (tak buat duplikat) — enqueue aman diulang."""
        if idempotency_key:
            existing = await pool.fetchrow(
                f"SELECT {_JOB_COLS} FROM agent_jobs WHERE org_id=$1 AND idempotency_key=$2",
                org_id, idempotency_key,
            )
            if existing:
                return _job_row(existing)
        row = await pool.fetchrow(
            f"""INSERT INTO agent_jobs
                (org_id, bot_id, agent_name, goal, ctx, priority, max_attempts,
                 step_timeout_s, max_duration_s, idempotency_key)
                VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9,$10)
                RETURNING {_JOB_COLS}""",
            org_id, bot_id, agent_name, goal, json.dumps(ctx or {}), priority,
            max_attempts, step_timeout_s, max_duration_s, idempotency_key,
        )
        return _job_row(row)

    async def get(self, pool: asyncpg.Pool, job_id: str, *, org_id: str | None = None) -> dict | None:
        if org_id is not None:
            row = await pool.fetchrow(
                f"SELECT {_JOB_COLS} FROM agent_jobs WHERE id=$1 AND org_id=$2", job_id, org_id)
        else:
            row = await pool.fetchrow(
                f"SELECT {_JOB_COLS} FROM agent_jobs WHERE id=$1", job_id)
        return _job_row(row)

    async def claim_next(self, pool: asyncpg.Pool, *, owner: str, lease_s: int) -> dict | None:
        """Ambil satu job berikutnya untuk dikerjakan (queued, atau running yang
        lease-nya kadaluarsa = recovery). Atomik via FOR UPDATE SKIP LOCKED →
        dua worker tak dapat job sama. Set running + lease + attempts+1."""
        async with pool.acquire() as con:
            async with con.transaction():
                row = await con.fetchrow(
                    """SELECT id FROM agent_jobs
                       WHERE status='queued'
                          OR (status='running' AND lease_until IS NOT NULL AND lease_until < NOW())
                       ORDER BY priority ASC, created_at ASC
                       FOR UPDATE SKIP LOCKED
                       LIMIT 1""")
                if row is None:
                    return None
                claimed = await con.fetchrow(
                    f"""UPDATE agent_jobs
                        SET status='running', lease_owner=$2,
                            lease_until=NOW() + ($3 || ' seconds')::interval,
                            attempts=attempts+1, updated_at=NOW()
                        WHERE id=$1
                        RETURNING {_JOB_COLS}""",
                    row["id"], owner, str(int(lease_s)),
                )
                return _job_row(claimed)

    async def renew_lease(self, pool: asyncpg.Pool, job_id: str, *, owner: str, lease_s: int) -> bool:
        """Perpanjang lease (heartbeat). Hanya bila owner cocok & masih running."""
        res = await pool.execute(
            """UPDATE agent_jobs
               SET lease_until=NOW() + ($3 || ' seconds')::interval, updated_at=NOW()
               WHERE id=$1 AND lease_owner=$2 AND status='running'""",
            job_id, owner, str(int(lease_s)))
        return res.endswith("1")

    async def find_expired(self, pool: asyncpg.Pool, *, limit: int = 20) -> list[dict]:
        """Job running dgn lease kadaluarsa (kandidat recovery)."""
        rows = await pool.fetch(
            f"""SELECT {_JOB_COLS} FROM agent_jobs
                WHERE status='running' AND lease_until IS NOT NULL AND lease_until < NOW()
                ORDER BY lease_until ASC LIMIT $1""", limit)
        return [_job_row(r) for r in rows]

    async def set_status(self, pool: asyncpg.Pool, job_id: str, status: str, *,
                         progress_pct: int | None = None, dlq_reason: str | None = None,
                         last_error: str | None = None, result_execution_id: str | None = None) -> dict | None:
        row = await pool.fetchrow(
            f"""UPDATE agent_jobs SET
                    status=$2,
                    progress_pct=COALESCE($3, progress_pct),
                    dlq_reason=COALESCE($4, dlq_reason),
                    last_error=COALESCE($5, last_error),
                    result_execution_id=COALESCE($6::uuid, result_execution_id),
                    updated_at=NOW()
                WHERE id=$1
                RETURNING {_JOB_COLS}""",
            job_id, status, progress_pct, dlq_reason, last_error, result_execution_id)
        return _job_row(row)

    async def request_control(self, pool: asyncpg.Pool, job_id: str, *, org_id: str, action: str) -> dict | None:
        """Minta cancel/pause/resume (cooperative — worker cek di boundary step).
        action: 'cancel' -> cancelling; 'pause' -> pausing; 'resume' -> queued (dari paused)."""
        target = {"cancel": "cancelling", "pause": "pausing", "resume": "queued"}[action]
        if action == "resume":
            row = await pool.fetchrow(
                f"UPDATE agent_jobs SET status='queued', updated_at=NOW() "
                f"WHERE id=$1 AND org_id=$2 AND status='paused' RETURNING {_JOB_COLS}",
                job_id, org_id)
        else:
            row = await pool.fetchrow(
                f"UPDATE agent_jobs SET status=$3, updated_at=NOW() "
                f"WHERE id=$1 AND org_id=$2 AND status IN ('queued','running','paused') "
                f"RETURNING {_JOB_COLS}",
                job_id, org_id, target)
        return _job_row(row)

    async def requeue_dlq(self, pool: asyncpg.Pool, job_id: str, *, org_id: str) -> dict | None:
        """Replay job dead_letter → antre ulang (reset attempts/dlq/error). Hanya
        bila status='dead_letter' & milik org. Return job atau None."""
        row = await pool.fetchrow(
            f"""UPDATE agent_jobs
                SET status='queued', attempts=0, dlq_reason=NULL, last_error=NULL, updated_at=NOW()
                WHERE id=$1 AND org_id=$2 AND status='dead_letter'
                RETURNING {_JOB_COLS}""",
            job_id, org_id)
        return _job_row(row)

    # ── steps / checkpoint ────────────────────────────────────────────────
    async def save_step(self, pool: asyncpg.Pool, *, job_id: str, seq: int, kind: str,
                        status: str = "done", checkpoint: dict | None = None,
                        output: dict | None = None, tool_calls: list | None = None,
                        step_idempotency_key: str | None = None) -> dict:
        """Simpan/replace satu step + checkpoint (UPSERT pada (job_id, seq))."""
        row = await pool.fetchrow(
            """INSERT INTO agent_job_steps
               (job_id, seq, kind, status, checkpoint, output, tool_calls,
                step_idempotency_key, ended_at)
               VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7::jsonb,$8,NOW())
               ON CONFLICT (job_id, seq) DO UPDATE SET
                   kind=EXCLUDED.kind, status=EXCLUDED.status,
                   checkpoint=EXCLUDED.checkpoint, output=EXCLUDED.output,
                   tool_calls=EXCLUDED.tool_calls, ended_at=NOW()
               RETURNING *""",
            job_id, seq, kind, status,
            json.dumps(checkpoint) if checkpoint is not None else None,
            json.dumps(output) if output is not None else None,
            json.dumps(tool_calls) if tool_calls is not None else None,
            step_idempotency_key)
        return _step_row(row)

    async def list_steps(self, pool: asyncpg.Pool, job_id: str) -> list[dict]:
        rows = await pool.fetch(
            "SELECT * FROM agent_job_steps WHERE job_id=$1 ORDER BY seq ASC", job_id)
        return [_step_row(r) for r in rows]

    async def latest_done_step(self, pool: asyncpg.Pool, job_id: str) -> dict | None:
        """Step 'done' terakhir (titik resume setelah crash)."""
        row = await pool.fetchrow(
            "SELECT * FROM agent_job_steps WHERE job_id=$1 AND status='done' "
            "ORDER BY seq DESC LIMIT 1", job_id)
        return _step_row(row) if row else None

    async def list_jobs(self, pool: asyncpg.Pool, org_id: str, *, status: str | None = None,
                        limit: int = 50) -> list[dict]:
        if status:
            rows = await pool.fetch(
                f"SELECT {_JOB_COLS} FROM agent_jobs WHERE org_id=$1 AND status=$2 "
                f"ORDER BY created_at DESC LIMIT $3", org_id, status, min(max(limit, 1), 200))
        else:
            rows = await pool.fetch(
                f"SELECT {_JOB_COLS} FROM agent_jobs WHERE org_id=$1 "
                f"ORDER BY created_at DESC LIMIT $2", org_id, min(max(limit, 1), 200))
        return [_job_row(r) for r in rows]
