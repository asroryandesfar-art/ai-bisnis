"""Per-agent ON/OFF toggle (per organisasi).

Setiap agent bisa dinyalakan/dimatikan sendiri. Key = kategori agent (mis.
'finance', 'marketing', 'hr', 'operations', 'computer'), yang memetakan 1:1 ke
endpoint run-task-nya sehingga gate benar-benar berlaku: agent OFF → HTTP 423.
Absen = ON (default, non-breaking). Berbeda dari AI master switch (yang menjeda
SEMUA otomatisasi); ini kontrol granular per-agent.
"""
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from .security import write_audit_log

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS org_agent_toggles (
    org_id     UUID NOT NULL,
    agent_key  TEXT NOT NULL,
    enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (org_id, agent_key)
);
"""


async def ensure_schema(pool: asyncpg.Pool) -> None:
    await pool.execute(SCHEMA_SQL)


async def get_agent_toggles(pool: asyncpg.Pool, org_id: str) -> dict:
    """Map agent_key → enabled untuk yang PERNAH di-set (absen = default ON)."""
    try:
        rows = await pool.fetch(
            "SELECT agent_key, enabled FROM org_agent_toggles WHERE org_id=$1", org_id,
        )
    except Exception:
        return {}
    return {r["agent_key"]: bool(r["enabled"]) for r in rows}


async def is_agent_enabled(pool: asyncpg.Pool, org_id: str, agent_key: str) -> bool:
    """True bila agent aktif. Absen / kolom belum ada / error → True (non-breaking)."""
    try:
        val = await pool.fetchval(
            "SELECT enabled FROM org_agent_toggles WHERE org_id=$1 AND agent_key=$2",
            org_id, agent_key,
        )
    except Exception:
        return True
    return True if val is None else bool(val)


async def set_agent_enabled(pool: asyncpg.Pool, org_id: str, agent_key: str, enabled: bool) -> bool:
    await pool.execute(
        """INSERT INTO org_agent_toggles (org_id, agent_key, enabled, updated_at)
           VALUES ($1,$2,$3,NOW())
           ON CONFLICT (org_id, agent_key) DO UPDATE SET enabled=EXCLUDED.enabled, updated_at=NOW()""",
        org_id, agent_key, enabled,
    )
    return enabled


async def require_agent_enabled(pool: asyncpg.Pool, org_id: str, agent_key: str) -> None:
    """Guard di jalur run-task agent. Raise 423 bila agent dimatikan."""
    if not await is_agent_enabled(pool, org_id, agent_key):
        raise HTTPException(
            status.HTTP_423_LOCKED,
            f"Agent '{agent_key}' sedang DIMATIKAN. Aktifkan toggle-nya di AI "
            f"Operations Center untuk menjalankan tugas agent ini.",
        )


class AgentToggleRequest(BaseModel):
    enabled: bool


def build_agent_toggles_router(*, get_pool, get_current_user, require_permission) -> APIRouter:
    router = APIRouter(tags=["Agent Toggles"])

    @router.get("/agents/toggles")
    async def list_toggles(
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        return {"toggles": await get_agent_toggles(pool, str(user["org_id"]))}

    @router.post("/agents/{agent_key}/toggle")
    async def set_toggle(
        agent_key: str,
        body: AgentToggleRequest,
        user=Depends(require_permission("settings.manage")),
        pool=Depends(get_pool),
    ):
        org_id = str(user["org_id"])
        await set_agent_enabled(pool, org_id, agent_key, body.enabled)
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user.get("id"), actor_email=user.get("email"),
            action="update", resource_type="agent_toggle", resource_id=agent_key,
            metadata={"enabled": body.enabled},
        )
        return {"agent_key": agent_key, "enabled": body.enabled}

    return router
