"""
bn_platform/marketplace.py — Agent Marketplace

Tenant dapat meng-install, memperbarui, dan menonaktifkan agent template
without rebuild. Canonical storage tetap memakai `marketplace_templates` dan
`tenant_template_installs`; `agent_templates` adalah compatibility view.
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
                  install_count, version, sample_faqs,
                  CASE WHEN is_active THEN 'active' ELSE 'inactive' END AS status
           FROM marketplace_templates
          WHERE is_active=TRUE
          ORDER BY category, install_count DESC, name""",
    )
    return [dict(r) for r in rows]


async def get_template(pool: asyncpg.Pool, key: str) -> dict | None:
    row = await pool.fetchrow(
        """SELECT id, key, category, name, description, preview_image, system_prompt,
                  greeting, primary_color, sample_faqs, install_count, version,
                  CASE WHEN is_active THEN 'active' ELSE 'inactive' END AS status,
                  is_active
           FROM marketplace_templates
          WHERE key=$1 AND is_active=TRUE""",
        key,
    )
    return dict(row) if row else None


async def _parse_sample_faqs(template: dict) -> list[dict]:
    raw_faqs = template.get("sample_faqs") or []
    if isinstance(raw_faqs, str):
        import json as _json
        raw_faqs = _json.loads(raw_faqs)
    return raw_faqs if isinstance(raw_faqs, list) else []


async def _seed_template_faqs(pool: asyncpg.Pool, *, bot_id: str, org_id: str, template: dict) -> int:
    seeded = 0
    for item in await _parse_sample_faqs(template):
        question = (item.get("question") or "").strip()
        answer   = (item.get("answer") or "").strip()
        if not question or not answer:
            continue
        await pool.execute(
            """INSERT INTO faq_entries (bot_id, org_id, question, answer, topic, status,
                                        frequency_score, success_score)
               VALUES ($1, $2, $3, $4, $5, 'published', 1, 0.8)""",
            bot_id, org_id, question, answer, template["category"],
        )
        seeded += 1
    return seeded


async def _sync_bot_from_template(
    pool: asyncpg.Pool,
    *,
    bot_id: str,
    template: dict,
    bot_name: str | None = None,
) -> dict:
    current = await pool.fetchrow("SELECT name FROM bots WHERE id=$1", bot_id)
    resolved_name = (bot_name or (current["name"] if current else None) or template["name"]).strip()
    row = await pool.fetchrow(
        """UPDATE bots
              SET name=$2, status='active', primary_color=$3, position='bottom-right',
                  greeting=$4, language='id', system_prompt=$5, temperature=0.3,
                  updated_at=NOW()
            WHERE id=$1
         RETURNING id, name, primary_color, greeting, system_prompt, status, created_at""",
        bot_id, resolved_name, template["primary_color"], template["greeting"], template["system_prompt"],
    )
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bot instalasi tidak ditemukan")
    return dict(row)


async def _fetch_install(pool: asyncpg.Pool, *, org_id: str, install_id: str) -> dict | None:
    row = await pool.fetchrow(
        """SELECT ti.id, ti.org_id, ti.template_id, ti.bot_id, ti.installed_by, ti.installed_at,
                  mt.key AS template_key, mt.category AS template_category, mt.name AS template_name,
                  mt.description AS template_description, mt.version AS template_version,
                  mt.primary_color AS template_primary_color,
                  CASE WHEN mt.is_active THEN 'active' ELSE 'inactive' END AS template_status,
                  b.name AS bot_name, b.status AS bot_status, b.primary_color AS bot_primary_color
             FROM tenant_template_installs ti
             JOIN marketplace_templates mt ON mt.id = ti.template_id
             JOIN bots b ON b.id = ti.bot_id
            WHERE ti.org_id = $1 AND ti.id = $2""",
        org_id, install_id,
    )
    return dict(row) if row else None


async def _fetch_install_by_template(pool: asyncpg.Pool, *, org_id: str, template_id: str) -> dict | None:
    row = await pool.fetchrow(
        """SELECT ti.id, ti.org_id, ti.template_id, ti.bot_id, ti.installed_by, ti.installed_at,
                  mt.key AS template_key, mt.category AS template_category, mt.name AS template_name,
                  mt.description AS template_description, mt.version AS template_version,
                  mt.primary_color AS template_primary_color,
                  CASE WHEN mt.is_active THEN 'active' ELSE 'inactive' END AS template_status,
                  b.name AS bot_name, b.status AS bot_status, b.primary_color AS bot_primary_color
             FROM tenant_template_installs ti
             JOIN marketplace_templates mt ON mt.id = ti.template_id
             JOIN bots b ON b.id = ti.bot_id
            WHERE ti.org_id = $1 AND ti.template_id = $2""",
        org_id, template_id,
    )
    return dict(row) if row else None


async def install_template(pool: asyncpg.Pool, *, org_id: str, user_id: str,
                           template_key: str, bot_name: str | None = None) -> dict:
    template = await get_template(pool, template_key)
    if not template:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Template '{template_key}' tidak ditemukan")

    existing = await _fetch_install_by_template(pool, org_id=org_id, template_id=template["id"])
    if existing:
        bot = await _sync_bot_from_template(
            pool,
            bot_id=existing["bot_id"],
            template=template,
            bot_name=bot_name or existing.get("bot_name"),
        )
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user_id, actor_email=None, action="update",
            resource_type="marketplace_install", resource_id=str(existing["id"]),
            metadata={"template_key": template_key, "bot_id": str(existing["bot_id"]), "mode": "reinstall"},
        )
        return {
            "install_id": str(existing["id"]),
            "installed_at": existing["installed_at"],
            "template_key": template_key,
            "template_version": existing.get("template_version"),
            "bot": bot,
            "faqs_seeded": 0,
            "status": bot["status"],
        }

    name = bot_name or f"{template['name']} (dari Marketplace)"
    bot_row = await pool.fetchrow(
        """INSERT INTO bots (org_id, name, status, primary_color, position, greeting,
                             language, system_prompt, temperature)
           VALUES ($1, $2, 'active', $3, 'bottom-right', $4, 'id', $5, 0.3)
           RETURNING id, name, primary_color, greeting, system_prompt, status, created_at""",
        org_id, name, template["primary_color"], template["greeting"], template["system_prompt"],
    )
    bot = dict(bot_row)

    seeded = await _seed_template_faqs(pool, bot_id=bot["id"], org_id=org_id, template=template)

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
        "install_id": str(install_row["id"]),
        "installed_at": install_row["installed_at"],
        "template_key": template_key,
        "template_version": template["version"],
        "bot": bot,
        "faqs_seeded": seeded,
        "status": bot["status"],
    }


async def list_installs(pool: asyncpg.Pool, org_id: str) -> list[dict]:
    rows = await pool.fetch(
        """SELECT ti.id, ti.installed_at, mt.key AS template_key, mt.name AS template_name,
                  mt.category AS template_category, mt.version AS template_version,
                  b.id AS bot_id, b.name AS bot_name, b.status AS bot_status,
                  b.primary_color AS bot_primary_color
           FROM tenant_template_installs ti
           JOIN marketplace_templates mt ON mt.id = ti.template_id
           JOIN bots b                   ON b.id = ti.bot_id
           WHERE ti.org_id = $1 ORDER BY ti.installed_at DESC""",
        org_id,
    )
    return [dict(r) for r in rows]


async def update_install(pool: asyncpg.Pool, *, org_id: str, user_id: str, install_id: str,
                         bot_name: str | None = None) -> dict:
    install = await _fetch_install(pool, org_id=org_id, install_id=install_id)
    if not install:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Instalasi tidak ditemukan")
    template = await get_template(pool, install["template_key"])
    if not template:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Template '{install['template_key']}' tidak ditemukan")

    bot = await _sync_bot_from_template(pool, bot_id=install["bot_id"], template=template, bot_name=bot_name)
    await write_audit_log(
        pool, org_id=org_id, actor_user_id=user_id, actor_email=None, action="update",
        resource_type="marketplace_install", resource_id=str(install_id),
        metadata={"template_key": install["template_key"], "bot_id": str(install["bot_id"]), "mode": "update"},
    )
    return {
        "install_id": install_id,
        "installed_at": install["installed_at"],
        "template_key": install["template_key"],
        "template_version": template["version"],
        "bot": bot,
        "faqs_seeded": 0,
        "status": bot["status"],
    }


async def uninstall_install(pool: asyncpg.Pool, *, org_id: str, user_id: str, install_id: str) -> dict:
    install = await _fetch_install(pool, org_id=org_id, install_id=install_id)
    if not install:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Instalasi tidak ditemukan")
    bot = await pool.fetchrow(
        """UPDATE bots
              SET status='inactive', updated_at=NOW()
            WHERE id=$1
         RETURNING id, name, status, primary_color, greeting, system_prompt, created_at""",
        install["bot_id"],
    )
    if not bot:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bot instalasi tidak ditemukan")
    bot_dict = dict(bot)
    await write_audit_log(
        pool, org_id=org_id, actor_user_id=user_id, actor_email=None, action="delete",
        resource_type="marketplace_install", resource_id=str(install_id),
        metadata={"template_key": install["template_key"], "bot_id": str(install["bot_id"]), "mode": "uninstall"},
    )
    return {
        "install_id": install_id,
        "template_key": install["template_key"],
        "template_version": install["template_version"],
        "bot": bot_dict,
        "status": bot_dict["status"],
    }


# ============================================================
# ROUTER
# ============================================================

class InstallReq(BaseModel):
    template_key: str
    bot_name: str | None = None


class InstallUpdateReq(BaseModel):
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
            existing = await _fetch_install_by_template(pool, org_id=user["org_id"], template_id=(await get_template(pool, body.template_key) or {}).get("id"))
            if not existing:
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

    @router.post("/installs/{install_id}/update")
    async def update_installation(
        install_id: str,
        body: InstallUpdateReq,
        user: Annotated[dict, Depends(require_permission("marketplace.install"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        return await update_install(pool, org_id=user["org_id"], user_id=user["id"],
                                    install_id=install_id, bot_name=body.bot_name)

    @router.post("/installs/{install_id}/uninstall")
    async def uninstall_installation(
        install_id: str,
        user: Annotated[dict, Depends(require_permission("marketplace.install"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        return await uninstall_install(pool, org_id=user["org_id"], user_id=user["id"], install_id=install_id)

    return router
