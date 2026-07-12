"""Bot CRUD routes (/bots, /bots/{id}/config, PATCH /bots/{id}), from main.py.

Handlers verbatim (guarded by test_bot_permission.py). The three platform hooks
main sets lazily at startup (require_permission, check_limit, write_audit) are
injected as getters so they read their current value at request time — the
permission tests monkeypatch require_permission and check_limit. Document/
knowledge routes under /bots/{id}/documents are intentionally left in main for a
later slice.
"""
import uuid
from typing import Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException


def build_bots_router(
    *,
    get_pool: Callable[..., Awaitable],
    get_current_user: Callable[..., Awaitable[dict]],
    get_require_permission: Callable[[], object],
    get_check_limit: Callable[[], object],
    get_write_audit: Callable[[], object],
    BotCreateReq,
    BotUpdateReq,
) -> APIRouter:
    router = APIRouter()

    @router.get("/bots")
    async def list_bots(
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        rows = await pool.fetch(
            """SELECT id, name, status, primary_color, greeting, language,
                      system_prompt, temperature, reasoning_mode, computer_agent_enabled,
                      total_convs, total_msgs, created_at
               FROM bots WHERE org_id=$1 ORDER BY created_at DESC""",
            user["org_id"],
        )
        return [dict(r) for r in rows]

    @router.post("/bots", status_code=201)
    async def create_bot(
        body: BotCreateReq,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        require_permission = get_require_permission()
        if require_permission:
            await require_permission("bots.write")(user=user, pool=pool)

        # Cek limit plan (Phase 2: gunakan check_limit dari subscriptions/plans)
        check_limit = get_check_limit()
        if check_limit:
            ok, detail = await check_limit(pool, user["org_id"], "agents")
            if not ok:
                raise HTTPException(
                    402,
                    f"Limit jumlah AI agent paket '{detail['plan']}' tercapai "
                    f"({detail['used']}/{detail['limit']}). Upgrade di /api/billing/checkout.",
                )
        else:
            # Fallback ke logika lama (jika Phase 2 belum dimuat)
            count = await pool.fetchval(
                "SELECT COUNT(*) FROM bots WHERE org_id=$1 AND status != 'inactive'", user["org_id"]
            )
            limit = await pool.fetchval(
                "SELECT bot_limit FROM organizations WHERE id=$1", user["org_id"]
            )
            if count >= limit:
                raise HTTPException(402, f"Paket kamu hanya boleh {limit} bot aktif. Upgrade untuk tambah lebih.")

        bot_id = str(uuid.uuid4())
        status_val = body.status if body.status in {"active", "training", "inactive"} else "active"
        await pool.execute(
            """INSERT INTO bots (id, org_id, name, status, primary_color, greeting, language, system_prompt)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
            bot_id, user["org_id"], body.name,
            status_val,
            body.primary_color, body.greeting,
            body.language, body.system_prompt,
        )
        # Audit log (Phase 2)
        write_audit = get_write_audit()
        if write_audit:
            try:
                await write_audit(
                    pool, org_id=user["org_id"], actor_user_id=user["id"],
                    actor_email=user.get("email"), action="create",
                    resource_type="bot", resource_id=bot_id,
                    metadata={"name": body.name, "status": status_val},
                )
            except Exception:
                pass
        return {"bot_id": bot_id, "status": status_val, "message": "Bot berhasil dibuat"}

    @router.get("/bots/{bot_id}/config")
    async def get_bot_config(bot_id: str, pool=Depends(get_pool)):
        """
        Public endpoint — dipanggil oleh widget.js dari browser klien.
        Tidak butuh auth, tapi hanya return config tampilan (bukan system prompt).
        """
        row = await pool.fetchrow(
            """SELECT id, name, primary_color, greeting, language, status
               FROM bots WHERE id=$1""",
            bot_id,
        )
        if not row or row["status"] == "inactive":
            raise HTTPException(404, "Bot tidak ditemukan atau tidak aktif")
        return dict(row)

    @router.patch("/bots/{bot_id}")
    async def update_bot(
        bot_id: str,
        body:   BotUpdateReq,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        require_permission = get_require_permission()
        if require_permission:
            await require_permission("bots.write")(user=user, pool=pool)

        row = await pool.fetchrow(
            "SELECT id FROM bots WHERE id=$1 AND org_id=$2", bot_id, user["org_id"]
        )
        if not row:
            raise HTTPException(404, "Bot tidak ditemukan")

        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        if "status" in updates and updates["status"] not in {"active", "training", "inactive"}:
            raise HTTPException(400, "Status tidak valid")
        if "reasoning_mode" in updates and updates["reasoning_mode"] not in {"standard", "pro"}:
            raise HTTPException(400, "Reasoning mode tidak valid")
        if not updates:
            return {"message": "Tidak ada perubahan"}

        set_clause = ", ".join(f"{k}=${i+2}" for i, k in enumerate(updates))
        vals = list(updates.values())
        await pool.execute(
            f"UPDATE bots SET {set_clause}, updated_at=NOW() WHERE id=$1",
            bot_id, *vals,
        )
        return {"message": "Bot diperbarui"}

    return router
