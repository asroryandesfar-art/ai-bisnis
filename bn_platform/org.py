"""Organization / subscription routes (/org, /org/plan), extracted from main.py.

Handlers are copied verbatim (guarded by test_org_plan_permission.py). The RBAC
checker main sets lazily at startup (_platform_require_permission) is injected as
a getter so the router reads its current value at request time, preserving main's
late-binding behavior — the permission tests monkeypatch it.
"""
from typing import Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException, status


def build_org_router(
    *,
    get_pool: Callable[..., Awaitable],
    get_current_user: Callable[..., Awaitable[dict]],
    should_use_cloud: Callable[[str, str], bool],
    cfg,
    get_require_permission: Callable[[], object],
    plan_limits: dict,
    plan_rank: dict,
    OrgPlanUpdateReq,
) -> APIRouter:
    router = APIRouter()

    @router.get("/org")
    async def get_org(
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        org = await pool.fetchrow(
            """SELECT id, name, slug, plan, billing_status, trial_ends_at,
                      bot_limit, conv_limit, doc_limit
               FROM organizations WHERE id=$1""",
            user["org_id"],
        )
        if not org:
            raise HTTPException(404, "Organisasi tidak ditemukan")

        use_cloud = should_use_cloud(org["plan"], org["billing_status"])
        # Same provider priority as base.py's BaseAgent._call_llm() fallback chain:
        # Gemini -> DeepSeek -> OpenRouter -> Groq.
        if cfg.effective_gemini_api_key:
            provider, cloud_model = "gemini", cfg.gemini_model
        elif cfg.deepseek_api_key:
            provider, cloud_model = "deepseek", "deepseek-chat"
        elif cfg.openrouter_api_key:
            provider, cloud_model = "openrouter", "openai/gpt-4o-mini"
        elif cfg.groq_api_key:
            provider, cloud_model = "groq", cfg.groq_model
        else:
            provider, cloud_model = None, None
        cloud_ready = provider is not None
        effective_mode = "cloud" if cloud_ready else "offline"

        return {
            "id": str(org["id"]),
            "name": org["name"],
            "slug": org["slug"],
            "plan": org["plan"],
            "billing_status": org["billing_status"],
            "trial_ends_at": org["trial_ends_at"].isoformat() if org["trial_ends_at"] else None,
            "limits": {
                "bot_limit": org["bot_limit"],
                "conv_limit": org["conv_limit"],
                "doc_limit": org["doc_limit"],
            },
            "ai": {
                "requested_mode": "cloud" if use_cloud else "local",
                "effective_mode": effective_mode,
                "cloud_ready": cloud_ready,
                "cloud_provider": provider,
                "cloud_model": cloud_model,
            },
        }

    @router.patch("/org/plan")
    async def update_org_plan(
        body: OrgPlanUpdateReq,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        require_permission = get_require_permission()
        if require_permission:
            await require_permission("billing.manage")(user=user, pool=pool)

        plan = (body.plan or "").strip().lower()
        if plan not in plan_limits:
            raise HTTPException(400, "Plan tidak valid (starter/growth/scale)")

        # H-01/H-02: endpoint legacy ini TIDAK boleh dipakai untuk upgrade ke tier
        # berbayar lebih tinggi tanpa pembayaran. `organizations.plan` hanya bisa
        # NAIK lewat alur checkout terverifikasi (invoice + webhook Midtrans di
        # bn_platform/billing.py). Di sini hanya izinkan downgrade / tetap sama;
        # upgrade diarahkan ke /api/billing/checkout.
        current_plan = ((await pool.fetchval(
            "SELECT plan FROM organizations WHERE id=$1", user["org_id"]
        )) or "starter").strip().lower()
        if plan_rank.get(plan, 0) > plan_rank.get(current_plan, 0):
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED,
                "Upgrade paket harus melalui pembayaran. Gunakan /api/billing/checkout.",
            )

        # Cegah downgrade kalau resource sekarang melebihi limit baru.
        active_bots = await pool.fetchval(
            "SELECT COUNT(*) FROM bots WHERE org_id=$1 AND status != 'inactive'",
            user["org_id"],
        )
        docs_count = await pool.fetchval(
            "SELECT COUNT(*) FROM documents WHERE org_id=$1",
            user["org_id"],
        )
        limits = plan_limits[plan]
        if active_bots > limits["bot_limit"]:
            raise HTTPException(
                409,
                f"Terlalu banyak bot aktif ({active_bots}). Hapus/nonaktifkan sampai ≤ {limits['bot_limit']} untuk downgrade.",
            )
        if docs_count > limits["doc_limit"]:
            raise HTTPException(
                409,
                f"Terlalu banyak dokumen ({docs_count}). Hapus sampai ≤ {limits['doc_limit']} untuk downgrade.",
            )

        await pool.execute(
            """UPDATE organizations
               SET plan=$2, bot_limit=$3, conv_limit=$4, doc_limit=$5, updated_at=NOW()
               WHERE id=$1""",
            user["org_id"],
            plan,
            limits["bot_limit"],
            limits["conv_limit"],
            limits["doc_limit"],
        )

        return {"message": "Plan diperbarui", "plan": plan, "limits": limits}

    return router
