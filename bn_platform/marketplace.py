"""
bn_platform/marketplace.py — Agent Marketplace

Tenant dapat meng-install, memperbarui, dan menonaktifkan agent template
without rebuild. Canonical storage tetap memakai `marketplace_templates` dan
`tenant_template_installs`; `agent_templates` adalah compatibility view.
"""
# from __future__ import annotations  # dihapus: menyebabkan Depends(closure_var) gagal di-resolve oleh FastAPI get_type_hints()

import json
import logging
from collections import Counter
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from .security import write_audit_log

logger = logging.getLogger("bn_platform.marketplace")

GetCurrentUser = Callable[..., Awaitable[dict]]
GetPool        = Callable[..., Awaitable[asyncpg.Pool]]
CheckLimit     = Callable[[asyncpg.Pool, str, str], Awaitable[tuple[bool, dict]]]


def _json_value(value, default):
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value


def _enrich_template(row: dict) -> dict:
    item = dict(row)
    item["tools"] = _json_value(item.get("tools"), [])
    item["knowledge_sources"] = _json_value(item.get("knowledge_sources"), [])
    item["starter_questions"] = _json_value(item.get("starter_questions"), [])
    item["visibility"] = _json_value(item.get("visibility"), {"public": True, "featured": False, "recommended": True})
    item["featured"] = bool(item["visibility"].get("featured"))
    item["recommended"] = bool(item["visibility"].get("recommended", True))
    item["rating"] = float(item.get("rating") or 0)
    item["popularity_score"] = int(item.get("popularity_score") or 0)
    item["icon"] = item.get("icon") or "agents"
    return item


async def list_templates(pool: asyncpg.Pool) -> list[dict]:
    rows = await pool.fetch(
        """SELECT id, key, category, name, description, preview_image, primary_color,
                  install_count, version, sample_faqs, icon, tools, knowledge_sources,
                  starter_questions, visibility, rating, popularity_score, created_at, updated_at,
                  CASE WHEN is_active THEN 'active' ELSE 'inactive' END AS status
           FROM marketplace_templates
          WHERE is_active=TRUE
          ORDER BY (visibility->>'featured')::boolean DESC, popularity_score DESC, install_count DESC, name""",
    )
    return [_enrich_template(dict(r)) for r in rows]


async def get_template(pool: asyncpg.Pool, key: str) -> dict | None:
    row = await pool.fetchrow(
        """SELECT id, key, category, name, description, preview_image, system_prompt,
                  greeting, primary_color, sample_faqs, install_count, version, icon, tools,
                  knowledge_sources, starter_questions, visibility, rating, popularity_score,
                  CASE WHEN is_active THEN 'active' ELSE 'inactive' END AS status,
                  is_active
           FROM marketplace_templates
          WHERE key=$1 AND is_active=TRUE""",
        key,
    )
    return _enrich_template(dict(row)) if row else None


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
    await pool.execute(
        """INSERT INTO agent_installs (org_id, agent_id, template_id, bot_id, installed_by, status)
           SELECT $1, a.id, $2, $3, $4, 'active'
             FROM agents a WHERE a.template_id=$2
           ON CONFLICT DO NOTHING""",
        org_id, template["id"], bot["id"], user_id,
    )
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



async def list_categories(pool: asyncpg.Pool) -> list[dict]:
    try:
        rows = await pool.fetch(
            """SELECT ac.key, ac.name, ac.description, ac.icon, ac.color, ac.sort_order,
                      COUNT(mt.id)::int AS template_count
                 FROM agent_categories ac
                 LEFT JOIN marketplace_templates mt ON mt.category = ac.name AND mt.is_active=TRUE
                WHERE ac.is_active=TRUE
                GROUP BY ac.key, ac.name, ac.description, ac.icon, ac.color, ac.sort_order
                ORDER BY ac.sort_order, ac.name"""
        )
        return [dict(r) for r in rows]
    except Exception:
        templates = await list_templates(pool)
        counts = Counter(t["category"] for t in templates)
        return [{"key": k.lower().replace(" ", "-"), "name": k, "description": "", "icon": "agents", "color": "#2563EB", "template_count": v} for k, v in counts.items()]


async def marketplace_analytics(pool: asyncpg.Pool, org_id: str) -> dict:
    templates = await list_templates(pool)
    installs = await list_installs(pool, org_id)
    categories = Counter(t["category"] for t in templates)
    featured = [t for t in templates if t.get("featured")]
    return {
        "template_count": len(templates),
        "category_count": len(categories),
        "featured_count": len(featured),
        "installed_count": len(installs),
        "active_installs": sum(1 for item in installs if item.get("bot_status") == "active"),
        "total_install_count": sum(int(t.get("install_count") or 0) for t in templates),
        "average_rating": round(sum(float(t.get("rating") or 0) for t in templates) / max(1, len(templates)), 2),
        "category_breakdown": dict(categories),
        "handoff_policy": "NEVER_OFFER_UNLESS_USER_REQUESTS",
    }


async def agent_health_report(pool: asyncpg.Pool) -> dict:
    """Audit kualitas seluruh 100+ agent marketplace: prompt valid, category
    valid (ada di agent_categories), knowledge attached (knowledge_sources
    tidak kosong), starter_questions tidak kosong, dan agent aktif."""
    rows = await pool.fetch(
        """SELECT key, category, name, system_prompt, knowledge_sources,
                  starter_questions, is_active
             FROM marketplace_templates ORDER BY name"""
    )
    valid_categories = {
        r["name"] for r in await pool.fetch("SELECT name FROM agent_categories WHERE is_active=TRUE")
    }

    agents_with_issues = []
    issue_counts: Counter = Counter()
    for row in rows:
        issues: list[str] = []
        if not (row["system_prompt"] or "").strip():
            issues.append("missing_prompt")
        if valid_categories and row["category"] not in valid_categories:
            issues.append("invalid_category")
        if not _json_value(row["knowledge_sources"], []):
            issues.append("no_knowledge_sources")
        if not _json_value(row["starter_questions"], []):
            issues.append("no_starter_questions")
        if not row["is_active"]:
            issues.append("inactive")
        if issues:
            agents_with_issues.append({"key": row["key"], "name": row["name"], "issues": issues})
            issue_counts.update(issues)

    total = len(rows)
    healthy = total - len(agents_with_issues)
    return {
        "total_agents": total,
        "healthy_agents": healthy,
        "agents_with_issues_count": len(agents_with_issues),
        "health_score_pct": round((healthy / total) * 100, 1) if total else 0.0,
        "issue_summary": dict(issue_counts),
        "agents_with_issues": agents_with_issues,
    }


def _score_template_for_query(template: dict, query: str) -> float:
    if not query:
        return float(template.get("popularity_score") or 0) / 1000
    haystack = " ".join([template.get("name", ""), template.get("category", ""), template.get("description", "")]).lower()
    terms = [term for term in query.lower().split() if len(term) > 2]
    hits = sum(1 for term in terms if term in haystack)
    return hits + (float(template.get("rating") or 0) / 10) + (float(template.get("popularity_score") or 0) / 5000)


async def recommended_templates(pool: asyncpg.Pool, *, query: str = "", limit: int = 12) -> list[dict]:
    templates = await list_templates(pool)
    rows = sorted(templates, key=lambda item: _score_template_for_query(item, query), reverse=True)
    return rows[: max(1, min(limit, 50))]


async def supervisor_route(pool: asyncpg.Pool, message: str) -> dict:
    recommendations = await recommended_templates(pool, query=message, limit=3)
    selected = recommendations[0] if recommendations else None
    confidence = min(0.95, 0.45 + _score_template_for_query(selected or {}, message) / 4) if selected else 0.3
    if not selected or confidence < 0.55:
        general = await get_template(pool, "general-ai")
        selected = general or selected
        confidence = max(confidence, 0.55)
    return {
        "assistant": "BotNesia Assistant",
        "selected_agent": selected,
        "confidence": round(confidence, 2),
        "fallback": selected and selected.get("key") == "general-ai",
        "policy": "solve_explain_recommend_clarify_escalate; never offer human handoff unless user requests it",
        "candidates": recommendations,
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

    @router.get("/categories")
    async def get_categories(pool: Annotated[asyncpg.Pool, Depends(get_pool)]):
        return {"categories": await list_categories(pool)}

    @router.get("/analytics")
    async def get_marketplace_analytics(
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        return await marketplace_analytics(pool, user["org_id"])

    @router.get("/recommended")
    async def get_recommended_templates(
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        q: str = "",
        limit: int = 12,
    ):
        return {"templates": await recommended_templates(pool, query=q, limit=limit)}

    @router.post("/supervisor/route")
    async def route_with_supervisor(
        body: dict,
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        _user: Annotated[dict, Depends(get_current_user)],
    ):
        return await supervisor_route(pool, str(body.get("message") or ""))

    @router.get("/health")
    async def get_agent_health(
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        _user: Annotated[dict, Depends(get_current_user)],
    ):
        return await agent_health_report(pool)

    return router
