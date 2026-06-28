"""bn_platform/marketing.py — Marketing Center router (AI Workforce Phase 2).

Campaign, content calendar (IG/TikTok/Facebook/Blog/Email/WhatsApp), dan
engagement/konversi (dicatat manual -- lihat docstring marketing_agent.py
untuk keterbatasan publish API). Semua endpoint org-scoped, RBAC-gated
(marketing.read/marketing.write/marketing.approve), dan audit-logged --
mengikuti pola persis bn_platform/finance.py."""
from datetime import datetime, timedelta, timezone
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import marketing_agent as ma
from .security import _check_rate_limit, write_audit_log

GetPool = Callable[..., Awaitable[asyncpg.Pool]]
GetCurrentUser = Callable[..., Awaitable[dict]]


def _parse_period(period_days: int) -> tuple[datetime, datetime]:
    period_days = max(1, min(period_days, 365))
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=period_days)
    return start, end


class CampaignCreateRequest(BaseModel):
    name: str
    goal: str | None = None
    target_audience: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    bot_id: str | None = None


class CampaignStatusRequest(BaseModel):
    status: str


class ContentCreateRequest(BaseModel):
    platform: str
    title: str | None = None
    body: str
    hashtags: list[str] = Field(default_factory=list)
    campaign_id: str | None = None
    bot_id: str | None = None


class ContentGenerateRequest(BaseModel):
    platform: str
    brief: str
    campaign_id: str | None = None
    bot_id: str | None = None


class ContentScheduleRequest(BaseModel):
    scheduled_at: datetime


class RunTaskRequest(BaseModel):
    goal: str
    bot_id: str | None = None


class EngagementCreateRequest(BaseModel):
    metric_type: str
    value: int = Field(ge=0)
    recorded_at: datetime | None = None


def build_marketing_router(*, get_pool: GetPool, get_current_user: GetCurrentUser,
                            require_permission, get_agent_config: Callable[[], dict]) -> APIRouter:
    router = APIRouter(prefix="/marketing", tags=["marketing"])
    cfg = get_agent_config()
    agent = ma.MarketingAgent(api_key=cfg.get("api_key"), model=cfg.get("model"),
                               base_url=cfg.get("base_url"), deepseek_api_key=cfg.get("deepseek_api_key", ""), openrouter_api_key=cfg.get("openrouter_api_key", ""), app_url=cfg.get("app_url", "https://botnesia.id"))

    # ── Dashboard ───────────────────────────────────────────────

    @router.get("/dashboard")
    async def dashboard(
        user: Annotated[dict, Depends(require_permission("marketing.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        return await ma.dashboard_summary(pool, user["org_id"])

    @router.get("/calendar")
    async def calendar(
        user: Annotated[dict, Depends(require_permission("marketing.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        period_days: int = 30,
    ):
        start, end = _parse_period(period_days)
        items = await ma.list_content_calendar(pool, user["org_id"], start, end)
        return {"calendar": items}

    @router.get("/due")
    async def due_content(
        user: Annotated[dict, Depends(require_permission("marketing.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        items = await ma.list_due_content(pool, user["org_id"])
        return {"due": items}

    # ── Campaigns ────────────────────────────────────────────────

    @router.get("/campaigns")
    async def list_campaigns(
        user: Annotated[dict, Depends(require_permission("marketing.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        limit: int = 50,
    ):
        limit = max(1, min(limit, 200))
        rows = await pool.fetch(
            "SELECT * FROM marketing_campaigns WHERE org_id=$1 ORDER BY created_at DESC LIMIT $2",
            user["org_id"], limit,
        )
        return {"campaigns": [dict(r) for r in rows]}

    @router.post("/campaigns", status_code=201)
    async def create_campaign_route(
        body: CampaignCreateRequest,
        user: Annotated[dict, Depends(require_permission("marketing.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        campaign = await ma.create_campaign(
            pool, org_id=org_id, bot_id=body.bot_id, name=body.name, goal=body.goal,
            target_audience=body.target_audience, start_date=body.start_date,
            end_date=body.end_date, created_by=user["id"],
        )
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="create", resource_type="marketing_campaign", resource_id=campaign["id"],
            metadata={"name": body.name},
        )
        return campaign

    @router.get("/campaigns/{campaign_id}")
    async def get_campaign(
        campaign_id: str,
        user: Annotated[dict, Depends(require_permission("marketing.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        row = await pool.fetchrow(
            "SELECT * FROM marketing_campaigns WHERE id=$1 AND org_id=$2", campaign_id, user["org_id"],
        )
        if not row:
            raise HTTPException(404, "Campaign tidak ditemukan")
        return dict(row)

    @router.patch("/campaigns/{campaign_id}/status")
    async def update_campaign_status_route(
        campaign_id: str,
        body: CampaignStatusRequest,
        user: Annotated[dict, Depends(require_permission("marketing.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        try:
            row = await ma.update_campaign_status(pool, org_id=org_id, campaign_id=campaign_id, status=body.status)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if not row:
            raise HTTPException(404, "Campaign tidak ditemukan")
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="marketing_campaign", resource_id=campaign_id,
            metadata={"status": body.status},
        )
        return row

    @router.get("/campaigns/{campaign_id}/analytics")
    async def campaign_analytics_route(
        campaign_id: str,
        user: Annotated[dict, Depends(require_permission("marketing.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        return await ma.campaign_analytics(pool, user["org_id"], campaign_id)

    @router.delete("/campaigns/{campaign_id}")
    async def delete_campaign(
        campaign_id: str,
        user: Annotated[dict, Depends(require_permission("marketing.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        row = await pool.fetchrow(
            "SELECT id FROM marketing_campaigns WHERE id=$1 AND org_id=$2", campaign_id, org_id,
        )
        if not row:
            raise HTTPException(404, "Campaign tidak ditemukan")
        await pool.execute("DELETE FROM marketing_campaigns WHERE id=$1 AND org_id=$2", campaign_id, org_id)
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="delete", resource_type="marketing_campaign", resource_id=campaign_id, metadata={},
        )
        return {"deleted": True}

    # ── Content ──────────────────────────────────────────────────

    @router.get("/content")
    async def list_content(
        user: Annotated[dict, Depends(require_permission("marketing.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        platform: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ):
        org_id = user["org_id"]
        limit = max(1, min(limit, 200))
        conditions = ["org_id=$1"]
        params: list = [org_id]
        if platform:
            params.append(platform)
            conditions.append(f"platform=${len(params)}")
        if status:
            params.append(status)
            conditions.append(f"status=${len(params)}")
        params.append(limit)
        rows = await pool.fetch(
            f"SELECT * FROM marketing_content WHERE {' AND '.join(conditions)} "
            f"ORDER BY created_at DESC LIMIT ${len(params)}",
            *params,
        )
        return {"content": [ma._content_out(dict(r)) for r in rows]}

    @router.post("/content", status_code=201)
    async def create_content_route(
        body: ContentCreateRequest,
        user: Annotated[dict, Depends(require_permission("marketing.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        try:
            content = await ma.create_content(
                pool, org_id=org_id, bot_id=body.bot_id, campaign_id=body.campaign_id,
                platform=body.platform, title=body.title, body=body.body,
                hashtags=body.hashtags, created_by=user["id"],
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="create", resource_type="marketing_content", resource_id=content["id"],
            metadata={"platform": body.platform},
        )
        return content

    @router.post("/content/generate", status_code=201)
    async def generate_content_route(
        body: ContentGenerateRequest,
        user: Annotated[dict, Depends(require_permission("marketing.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        result = await agent.safe_run({
            "user_message": body.brief, "platform": body.platform, "org_id": user["org_id"],
            "bot_id": body.bot_id, "campaign_id": body.campaign_id, "pool": pool,
            "actor_user_id": user["id"],
        })
        if not result.success:
            raise HTTPException(422, result.error or "Gagal generate konten")
        await write_audit_log(
            pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
            action="create", resource_type="marketing_content",
            resource_id=result.output["content"]["id"], metadata={"platform": body.platform, "ai_generated": True},
        )
        return result.output["content"]

    @router.get("/content/{content_id}")
    async def get_content(
        content_id: str,
        user: Annotated[dict, Depends(require_permission("marketing.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        row = await pool.fetchrow(
            "SELECT * FROM marketing_content WHERE id=$1 AND org_id=$2", content_id, user["org_id"],
        )
        if not row:
            raise HTTPException(404, "Konten tidak ditemukan")
        return ma._content_out(dict(row))

    @router.patch("/content/{content_id}/schedule")
    async def schedule_content_route(
        content_id: str,
        body: ContentScheduleRequest,
        user: Annotated[dict, Depends(require_permission("marketing.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        row = await ma.schedule_content(pool, org_id=org_id, content_id=content_id, scheduled_at=body.scheduled_at)
        if not row:
            raise HTTPException(404, "Konten tidak ditemukan")
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="marketing_content", resource_id=content_id,
            metadata={"scheduled_at": body.scheduled_at.isoformat()},
        )
        return row

    @router.patch("/content/{content_id}/approve")
    async def approve_content_route(
        content_id: str,
        user: Annotated[dict, Depends(require_permission("marketing.approve"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        row = await ma.approve_content(pool, org_id=org_id, content_id=content_id, approver_id=user["id"])
        if not row:
            raise HTTPException(404, "Konten tidak ditemukan")
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="marketing_content", resource_id=content_id,
            metadata={"approved": True},
        )
        return row

    @router.patch("/content/{content_id}/publish")
    async def publish_content_route(
        content_id: str,
        user: Annotated[dict, Depends(require_permission("marketing.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        row = await ma.mark_content_published(pool, org_id=org_id, content_id=content_id)
        if not row:
            raise HTTPException(404, "Konten tidak ditemukan")
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="marketing_content", resource_id=content_id,
            metadata={"status": "published"},
        )
        return row

    @router.delete("/content/{content_id}")
    async def cancel_content_route(
        content_id: str,
        user: Annotated[dict, Depends(require_permission("marketing.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        row = await ma.cancel_content(pool, org_id=org_id, content_id=content_id)
        if not row:
            raise HTTPException(404, "Konten tidak ditemukan")
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="marketing_content", resource_id=content_id,
            metadata={"status": "cancelled"},
        )
        return row

    # ── Engagement ───────────────────────────────────────────────

    @router.get("/content/{content_id}/engagement")
    async def list_engagement(
        content_id: str,
        user: Annotated[dict, Depends(require_permission("marketing.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        rows = await pool.fetch(
            "SELECT * FROM marketing_engagement WHERE content_id=$1 AND org_id=$2 ORDER BY recorded_at DESC",
            content_id, user["org_id"],
        )
        return {"engagement": [dict(r) for r in rows]}

    @router.post("/content/{content_id}/engagement", status_code=201)
    async def create_engagement_route(
        content_id: str,
        body: EngagementCreateRequest,
        user: Annotated[dict, Depends(require_permission("marketing.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        content = await pool.fetchrow(
            "SELECT id FROM marketing_content WHERE id=$1 AND org_id=$2", content_id, org_id,
        )
        if not content:
            raise HTTPException(404, "Konten tidak ditemukan")
        try:
            engagement = await ma.record_engagement(
                pool, org_id=org_id, content_id=content_id, metric_type=body.metric_type,
                value=body.value, recorded_at=body.recorded_at, created_by=user["id"],
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="create", resource_type="marketing_engagement", resource_id=engagement["id"],
            metadata={"content_id": content_id, "metric_type": body.metric_type, "value": body.value},
        )
        return engagement

    # ── Task Engine: goal bebas multi-step lewat Marketing Agent's tools ──
    @router.post("/run-task")
    async def run_task(
        body: RunTaskRequest,
        user: Annotated[dict, Depends(require_permission("marketing.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        _check_rate_limit(f"marketing-run-task:{user['org_id']}", 5)
        result = await agent.run_task(body.goal, pool=pool, org_id=user["org_id"], bot_id=body.bot_id)
        await write_audit_log(
            pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
            action="create", resource_type="agent_task_execution",
            metadata={"goal": body.goal, "status": result.get("status")},
        )
        return result

    return router
