"""Knowledge-base source + seeding routes (/api/knowledge/*), from main.py.

Cohesive, contiguous block with no direct-caller tests. Business logic lives in
the knowledge_seeder module (imported directly); the two main helpers
_require_owned_bot and _schedule_knowledge_crawl stay in main (shared with the
documents routes) and are injected. Request models are injected too.
"""
import asyncio
from typing import Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException

import knowledge_seeder


def build_knowledge_router(
    *,
    get_current_user: Callable[..., Awaitable[dict]],
    get_pool: Callable[..., Awaitable],
    require_owned_bot: Callable[..., Awaitable],
    schedule_knowledge_crawl: Callable[..., None],
    KnowledgeBulkUrlReq,
    KnowledgeSeedReq,
    MarketplaceKnowledgeSeedReq,
    KnowledgeRetryFailedReq,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/knowledge/urls/bulk")
    async def knowledge_bulk_urls(
        body: KnowledgeBulkUrlReq,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        """Bulk import URL ke queue knowledge_sources, lalu crawl background terbatas."""
        await require_owned_bot(pool, body.bot_id, user["org_id"])
        result = await knowledge_seeder.bulk_import_urls(
            pool,
            org_id=str(user["org_id"]),
            bot_id=str(body.bot_id),
            urls_data=[entry.model_dump() for entry in body.urls],
        )
        result["stats"] = await knowledge_seeder.get_source_stats(
            pool, org_id=str(user["org_id"]), bot_id=str(body.bot_id)
        )
        if body.crawl and result.get("imported", 0) > 0:
            schedule_knowledge_crawl(pool, org_id=user["org_id"], bot_id=body.bot_id)
            result["crawler"] = "scheduled"
        return result

    @router.get("/api/knowledge/sources")
    async def knowledge_sources(
        bot_id: str | None = None,
        status: str | None = None,
        category: str | None = None,
        agent_id: str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        if bot_id:
            await require_owned_bot(pool, bot_id, user["org_id"])
        rows, stats = await asyncio.gather(
            knowledge_seeder.get_sources(
                pool,
                org_id=str(user["org_id"]),
                bot_id=bot_id,
                status=status,
                category=category,
                agent_id=agent_id,
                search=search,
                limit=max(1, min(200, int(limit or 50))),
                offset=max(0, int(offset or 0)),
            ),
            knowledge_seeder.get_source_stats(pool, org_id=str(user["org_id"]), bot_id=bot_id),
        )
        return {"sources": rows, "stats": stats}

    @router.get("/api/knowledge/sources/{source_id}")
    async def knowledge_source_detail(
        source_id: str,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        row = await pool.fetchrow(
            """SELECT id, org_id, bot_id, url, title, category, agent_type, priority, language,
                      trusted, status, error_message, retry_count, document_id, last_crawled_at, created_at
                 FROM knowledge_sources WHERE id=$1 AND org_id=$2""",
            source_id,
            user["org_id"],
        )
        if not row:
            raise HTTPException(404, "Knowledge source tidak ditemukan")
        return dict(row)

    @router.post("/api/knowledge/sources/{source_id}/retry")
    async def knowledge_source_retry(
        source_id: str,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        row = await pool.fetchrow(
            "SELECT id, bot_id FROM knowledge_sources WHERE id=$1 AND org_id=$2",
            source_id,
            user["org_id"],
        )
        if not row:
            raise HTTPException(404, "Knowledge source tidak ditemukan")
        ok = await knowledge_seeder.retry_source(pool, source_id=source_id, org_id=str(user["org_id"]))
        if not ok:
            raise HTTPException(400, "Source tidak bisa diretry atau sudah mencapai batas retry")
        schedule_knowledge_crawl(pool, org_id=user["org_id"], bot_id=str(row["bot_id"]), batch_size=5)
        return {"message": "Retry dijadwalkan", "source_id": source_id}

    @router.delete("/api/knowledge/sources/{source_id}")
    async def knowledge_source_delete(
        source_id: str,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        ok = await knowledge_seeder.delete_source(pool, source_id=source_id, org_id=str(user["org_id"]))
        if not ok:
            raise HTTPException(404, "Knowledge source tidak ditemukan")
        return {"message": "Knowledge source dihapus"}

    @router.post("/api/knowledge/seed/general")
    async def knowledge_seed_general(
        body: KnowledgeSeedReq,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        await require_owned_bot(pool, body.bot_id, user["org_id"])
        result = await knowledge_seeder.seed_agent_urls(
            pool, org_id=str(user["org_id"]), bot_id=body.bot_id, agent_type="general_ai"
        )
        result["stats"] = await knowledge_seeder.get_source_stats(pool, org_id=str(user["org_id"]), bot_id=body.bot_id)
        if body.crawl and result.get("imported", 0) > 0:
            schedule_knowledge_crawl(pool, org_id=user["org_id"], bot_id=body.bot_id)
            result["crawler"] = "scheduled"
        return result

    @router.post("/api/knowledge/seed/agents")
    async def knowledge_seed_all_agents(
        body: KnowledgeSeedReq,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        await require_owned_bot(pool, body.bot_id, user["org_id"])
        agent_types = [
            "travel_agent", "ecommerce_agent", "clinic_agent", "school_agent", "sales_agent",
            "property_agent", "faq_agent", "customer_service_agent", "botnesia_business",
        ]
        results = {}
        for agent_type in agent_types:
            results[agent_type] = await knowledge_seeder.seed_agent_urls(
                pool, org_id=str(user["org_id"]), bot_id=body.bot_id, agent_type=agent_type
            )
        if body.crawl:
            schedule_knowledge_crawl(pool, org_id=user["org_id"], bot_id=body.bot_id)
        return {"results": results, "stats": await knowledge_seeder.get_source_stats(pool, org_id=str(user["org_id"]), bot_id=body.bot_id)}

    @router.post("/api/knowledge/seed/marketplace-1000")
    async def knowledge_seed_marketplace_1000(
        body: MarketplaceKnowledgeSeedReq,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        """Queue 1000+ marketplace URL seeds. Does not crawl by default."""
        if body.bot_id:
            await require_owned_bot(pool, body.bot_id, user["org_id"])
        result = await knowledge_seeder.bulk_import_marketplace_seed(
            pool,
            org_id=str(user["org_id"]),
            fallback_bot_id=body.bot_id,
            installed_only=body.installed_only,
        )
        result["status"] = await knowledge_seeder.get_marketplace_seed_status(
            pool, org_id=str(user["org_id"]), bot_id=body.bot_id,
        )
        if body.crawl and result.get("imported", 0) > 0:
            for touched_bot in result.get("touched_bots", [])[:3]:
                schedule_knowledge_crawl(pool, org_id=user["org_id"], bot_id=touched_bot, batch_size=5)
            result["crawler"] = "scheduled_limited_batch"
        else:
            result["crawler"] = "not_scheduled"
        return result

    @router.get("/api/knowledge/seed/status")
    async def knowledge_seed_status(
        bot_id: str | None = None,
        agent_id: str | None = None,
        category: str | None = None,
        search: str | None = None,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        if bot_id:
            await require_owned_bot(pool, bot_id, user["org_id"])
        return await knowledge_seeder.get_marketplace_seed_status(
            pool,
            org_id=str(user["org_id"]),
            bot_id=bot_id,
            agent_id=agent_id,
            category=category,
            search=search,
        )

    @router.post("/api/knowledge/sources/retry-failed")
    async def knowledge_sources_retry_failed(
        body: KnowledgeRetryFailedReq,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        if body.bot_id:
            await require_owned_bot(pool, body.bot_id, user["org_id"])
        retried = await knowledge_seeder.retry_failed_sources(
            pool,
            org_id=str(user["org_id"]),
            bot_id=body.bot_id,
            agent_id=body.agent_id,
            category=body.category,
        )
        if body.crawl and body.bot_id and retried:
            schedule_knowledge_crawl(pool, org_id=user["org_id"], bot_id=body.bot_id, batch_size=5)
        return {"retried": retried, "crawler": "scheduled_limited_batch" if body.crawl and body.bot_id and retried else "not_scheduled"}

    @router.post("/api/knowledge/seed/{agent_id}")
    async def knowledge_seed_agent(
        agent_id: str,
        body: KnowledgeSeedReq,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        await require_owned_bot(pool, body.bot_id, user["org_id"])
        agent_type = agent_id.strip().lower().replace("-", "_")
        result = await knowledge_seeder.seed_agent_urls(
            pool, org_id=str(user["org_id"]), bot_id=body.bot_id, agent_type=agent_type
        )
        result["stats"] = await knowledge_seeder.get_source_stats(pool, org_id=str(user["org_id"]), bot_id=body.bot_id)
        if body.crawl and result.get("imported", 0) > 0:
            schedule_knowledge_crawl(pool, org_id=user["org_id"], bot_id=body.bot_id)
            result["crawler"] = "scheduled"
        return result

    return router
