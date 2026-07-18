"""AI Power — master autonomy switch per organisasi.

"Jantung" AI Operations Center. Saat OFF, otomatisasi dijeda: eksekusi lokal
(local agent), computer agent, dan terminal/agent execute ditolak dengan
HTTP 423 (Locked). Saat ON, AI otonom. Default TRUE agar perilaku tenant lama
tidak berubah; mematikan benar-benar menjeda eksekusi.

Dipakai lewat `require_autonomy(pool, org_id)` di jalur otomatisasi nyata.
"""
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from .security import write_audit_log

AUTONOMY_OFF_MESSAGE = (
    "AI sedang DIMATIKAN (mode manual). Aktifkan sakelar AI di AI Operations "
    "Center untuk menjalankan otomatisasi & eksekusi."
)


async def get_autonomy(pool: asyncpg.Pool, org_id: str) -> bool:
    """True bila AI aktif (otonom). Org tanpa baris / kolom belum ada / error baca
    → default True (aman & non-breaking; aksi berisiko tetap lewat approval gate)."""
    try:
        val = await pool.fetchval(
            "SELECT autonomy_enabled FROM organizations WHERE id=$1", org_id,
        )
    except Exception:
        return True
    return True if val is None else bool(val)


async def set_autonomy(pool: asyncpg.Pool, org_id: str, enabled: bool) -> bool:
    await pool.execute(
        "UPDATE organizations SET autonomy_enabled=$2, updated_at=NOW() WHERE id=$1",
        org_id, enabled,
    )
    return enabled


async def require_autonomy(pool: asyncpg.Pool, org_id: str) -> None:
    """Guard untuk jalur otomatisasi. Raise 423 bila AI OFF."""
    if not await get_autonomy(pool, org_id):
        raise HTTPException(status.HTTP_423_LOCKED, AUTONOMY_OFF_MESSAGE)


class AiPowerRequest(BaseModel):
    enabled: bool


def build_ai_power_router(*, get_pool, get_current_user, require_permission) -> APIRouter:
    router = APIRouter(tags=["AI Power"])

    @router.get("/ai/power")
    async def ai_power_status(
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        enabled = await get_autonomy(pool, str(user["org_id"]))
        return {"enabled": enabled, "status": "active" if enabled else "paused"}

    @router.post("/ai/power")
    async def ai_power_set(
        body: AiPowerRequest,
        user=Depends(require_permission("settings.manage")),
        pool=Depends(get_pool),
    ):
        org_id = str(user["org_id"])
        await set_autonomy(pool, org_id, body.enabled)
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user.get("id"), actor_email=user.get("email"),
            action="update", resource_type="ai_power", resource_id=org_id,
            metadata={"enabled": body.enabled},
        )
        return {"enabled": body.enabled, "status": "active" if body.enabled else "paused"}

    return router
