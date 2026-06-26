"""
audit_logger.py — Audit Trail untuk semua aksi AI Agent (AI Agent Platform).

Log setiap aksi ke tabel `agent_audit_log`:
  - agent_name: siapa yang melakukan
  - action_type: jenis aksi (terminal_execute, file_write, browser_write, dll)
  - target: target aksi (path file, URL, command, dll)
  - status: pending_approval | approved | rejected | completed | failed
  - permission_grant_id: referensi ke grant yang dipakai
  - metadata: detail tambahan

Modul ini TIDAK pernah raise exception ke caller — fail-open selalu.
Setiap write dijalankan via fire-and-forget asyncio.create_task() supaya
tidak memperlambat jalur utama.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


async def log_action(
    pool: asyncpg.Pool,
    *,
    org_id: str,
    agent_name: str,
    action_type: str,
    target: str = "",
    status: str = "completed",
    permission_grant_id: str | None = None,
    initiated_by: str = "agent",
    approved_by: str | None = None,
    metadata: dict | None = None,
    error: str | None = None,
    duration_ms: int | None = None,
) -> str | None:
    """
    Catat satu aksi ke audit log.

    status: pending_approval | approved | rejected | completed | failed | skipped
    Return: audit_log_id atau None kalau gagal.
    """
    try:
        row = await pool.fetchrow(
            """INSERT INTO agent_audit_log
               (org_id, agent_name, action_type, target, status,
                permission_grant_id, initiated_by, approved_by,
                metadata, error, duration_ms)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11)
               RETURNING id""",
            org_id, agent_name, action_type, target, status,
            permission_grant_id, initiated_by, approved_by,
            json.dumps(metadata or {}), error, duration_ms,
        )
        return str(row["id"]) if row else None
    except Exception as e:
        logger.debug("audit_logger: gagal menulis log: %s", e)
        return None


async def update_log(
    pool: asyncpg.Pool,
    log_id: str,
    *,
    status: str,
    approved_by: str | None = None,
    error: str | None = None,
    duration_ms: int | None = None,
    metadata: dict | None = None,
) -> None:
    """Update status entry audit log yang sudah ada."""
    if not log_id:
        return
    try:
        updates = ["status=$2", "updated_at=NOW()"]
        params: list[Any] = [log_id, status]

        if approved_by is not None:
            params.append(approved_by)
            updates.append(f"approved_by=${len(params)}")
        if error is not None:
            params.append(error)
            updates.append(f"error=${len(params)}")
        if duration_ms is not None:
            params.append(duration_ms)
            updates.append(f"duration_ms=${len(params)}")
        if metadata is not None:
            params.append(json.dumps(metadata))
            updates.append(f"metadata=${len(params)}::jsonb")

        await pool.execute(
            f"UPDATE agent_audit_log SET {', '.join(updates)} WHERE id=$1",
            *params,
        )
    except Exception as e:
        logger.debug("audit_logger.update_log: %s", e)


async def list_logs(
    pool: asyncpg.Pool,
    *,
    org_id: str,
    action_type: str | None = None,
    agent_name: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Ambil riwayat audit log dengan filter opsional."""
    try:
        conditions = ["org_id=$1"]
        params: list[Any] = [org_id]
        if action_type:
            params.append(action_type)
            conditions.append(f"action_type=${len(params)}")
        if agent_name:
            params.append(agent_name)
            conditions.append(f"agent_name=${len(params)}")
        if status:
            params.append(status)
            conditions.append(f"status=${len(params)}")
        params.append(max(1, min(limit, 500)))
        rows = await pool.fetch(
            f"""SELECT id, agent_name, action_type, target, status,
                       initiated_by, approved_by, error, duration_ms,
                       created_at, updated_at
                FROM agent_audit_log
                WHERE {' AND '.join(conditions)}
                ORDER BY created_at DESC LIMIT ${len(params)}""",
            *params,
        )
        return [dict(r) for r in rows]
    except Exception:
        return []


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_audit_log (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id               UUID NOT NULL,
    agent_name           TEXT NOT NULL,
    action_type          TEXT NOT NULL,
    target               TEXT,
    status               TEXT NOT NULL DEFAULT 'completed',
    permission_grant_id  UUID,
    initiated_by         TEXT NOT NULL DEFAULT 'agent',
    approved_by          TEXT,
    metadata             JSONB DEFAULT '{}',
    error                TEXT,
    duration_ms          INT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_audit_log_org
    ON agent_audit_log(org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_audit_log_type
    ON agent_audit_log(org_id, action_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_audit_log_status
    ON agent_audit_log(org_id, status, created_at DESC);
"""


async def ensure_schema(pool: asyncpg.Pool) -> None:
    try:
        await pool.execute(SCHEMA_SQL)
    except Exception as e:
        logger.warning("audit_logger.ensure_schema: %s", e)
