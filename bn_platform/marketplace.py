"""
bn_platform/marketplace.py — Marketplace Template (instal 1-klik)

6 template siap pakai (Toko Online, Travel, Klinik, Pesantren, Properti,
UMKM) — katalog & isi (system_prompt, greeting, sample FAQ) di-seed lewat
schema_platform.sql §11 (`marketplace_templates`). Instal 1-klik akan:

  1. Validasi limit paket (`max_agents`, lihat bn_platform.billing.check_limit)
  2. Membuat bot baru terisi system_prompt/greeting/warna dari template
  3. Mem-publish sample FAQ langsung ke `faq_entries` (status='published')
     sehingga bot punya basis pengetahuan awal tanpa menunggu siklus
     cluster nightly job Intelligence Platform
  4. Mencatat instalasi di `tenant_template_installs` + audit log
"""
# from __future__ import annotations  # dihapus: menyebabkan Depends(closure_var) gagal di-resolve oleh FastAPI get_type_hints()

import logging
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from .security import write_audit_log

logger = logging.getLogger("bn_platform.marketplace")

GetCurrentUser = Callable[..., Awaitable[dict]]
GetPool        = Callable[..., Awaitable[asyncpg.Pool]]
CheckLimit     = Callable[[asyncpg.Pool, str, str], Awaitable[tuple[bool, dict]]]


async def list_templates(pool: asyncpg.Pool) -> list[dict]:
    rows = await pool.fetch(
        """SELECT id, key, category, name, description, preview_image, primary_color,
                  install_count, sample_faqs
           FROM marketplace_templates WHERE is_active=TRUE ORDER BY install_count DESC, name""",
    )
    return [dict(r) for r in rows]


async def get_template(pool: asyncpg.Pool, key: str) -> dict | None:
    row = await pool.fetchrow("SELECT * FROM marketplace_templates WHERE key=$1 AND is_active=TRUE", key)
    return dict(row) if row else None


async def install_template(pool: asyncpg.Pool, *, org_id: str, user_id: str,
                           template_key: str, bot_name: str | None = None) -> dict:
    template = await get_template(pool, template_key)
    if not template:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Template '{template_key}' tidak ditemukan")

    name = bot_name or f"{template['name']} (dari Marketplace)"
    bot_row = await pool.fetchrow(
        """INSERT INTO bots (org_id, name, status, primary_color, position, greeting,
                             language, system_prompt, temperature)
           VALUES ($1, $2, 'active', $3, 'bottom-right', $4, 'id', $5, 0.3)
           RETURNING id, name, primary_color, greeting, system_prompt, status, created_at""",
        org_id, name, template["primary_color"], template["greeting"], template["system_prompt"],
    )
    bot = dict(bot_row)

    raw_faqs = template["sample_faqs"] or []
    if isinstance(raw_faqs, str):
        import json as _json
        raw_faqs = _json.loads(raw_faqs)
    faqs = raw_faqs if isinstance(raw_faqs, list) else []
    seeded = 0
    for item in faqs:
        question = (item.get("question") or "").strip()
        answer   = (item.get("answer") or "").strip()
        if not question or not answer:
            continue
        await pool.execute(
            """INSERT INTO faq_entries (bot_id, org_id, question, answer, topic, status,
                                        frequency_score, success_score)
               VALUES ($1, $2, $3, $4, $5, 'published', 1, 0.8)""",
            bot["id"], org_id, question, answer, template["category"],
        )
        seeded += 1

    install_row = await pool.fetchrow(
        """INSERT INTO tenant_template_installs (org_id, template_id, bot_id, installed_by)
           VALUES ($1, $2, $3, $4) RETURNING id, installed_at""",
        org_id, template["id"], bot["id"], user_id,
    )
    await pool.execute("UPDATE marketplace_templates SET install_count = install_count + 1 WHERE id=$1", template["id"])
    await write_audit_log(
        pool, org_id=org_id, actor_user_id=user_id, actor_email=None, action="create",
        resource_type="marketplace_install", resource_id=str(install_row["id"]),
        metadata={"template_key": template_key, "bot_id": str(bot["id"]), "faqs_seeded": seeded},
    )
    return {
        "install_id": str(install_row["id"]), "installed_at": install_row["installed_at"],
        "template_key": template_key, "bot": bot, "faqs_seeded": seeded,
    }


async def list_installs(pool: asyncpg.Pool, org_id: str) -> list[dict]:
    rows = await pool.fetch(
        """SELECT ti.id, ti.installed_at, mt.key AS template_key, mt.name AS template_name,
                  b.id AS bot_id, b.name AS bot_name, b.status AS bot_status
           FROM tenant_template_installs ti
           JOIN marketplace_templates mt ON mt.id = ti.template_id
           JOIN bots b                   ON b.id = ti.bot_id
           WHERE ti.org_id = $1 ORDER BY ti.installed_at DESC""",
        org_id,
    )
    return [dict(r) for r in rows]


# ============================================================
# ROUTER
# ============================================================

class InstallReq(BaseModel):
    template_key: str
    bot_name: str | None = None


def build_marketplace_router(*, get_pool: GetPool, get_current_user: GetCurrentUser,
                              require_permission, check_limit: CheckLimit | None = None) -> APIRouter:
    router = APIRouter(prefix="/marketplace", tags=["marketplace"])

    @router.get("/templates")
    async def get_templates(pool: Annotated[asyncpg.Pool, Depends(get_pool)]):
        return {"templates": await list_templates(pool)}

    @router.get("/templates/{key}")
    async def get_template_detail(key: str, pool: Annotated[asyncpg.Pool, Depends(get_pool)]):
        template = await get_template(pool, key)
        if not template:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Template tidak ditemukan")
        return {"template": template}

    @router.post("/install", status_code=status.HTTP_201_CREATED)
    async def install(
        body: InstallReq,
        user: Annotated[dict, Depends(require_permission("marketplace.install"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        if check_limit:
            ok, detail = await check_limit(pool, user["org_id"], "agents")
            if not ok:
                raise HTTPException(
                    status.HTTP_402_PAYMENT_REQUIRED,
                    f"Limit jumlah AI agent paket '{detail['plan']}' tercapai "
                    f"({detail['used']}/{detail['limit']}). Upgrade paket untuk menambah agent.",
                )
        return await install_template(pool, org_id=user["org_id"], user_id=user["id"],
                                       template_key=body.template_key, bot_name=body.bot_name)

    @router.get("/installs")
    async def get_installs(
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        return {"installs": await list_installs(pool, user["org_id"])}

    return router
