"""
Security audit (org_id defense-in-depth): GET /bots/{bot_id}/analytics
validates the bot belongs to the caller's org once, then used to run its
summary/daily/top-questions queries filtered ONLY by bot_id -- relying
entirely on bot_id always being correctly paired with the right org_id
everywhere else in the system. If a conversations/messages row ever ended
up with a bot_id/org_id mismatch (e.g. a future bug elsewhere, or a data
migration issue), analytics would silently count it in.

This test simulates exactly that inconsistent state directly in the DB and
confirms the analytics query now excludes it -- the org_id filter added to
the summary/daily/top_questions queries is a real, independently-enforced
second check, not just decoration.
"""
import asyncio
import uuid
from datetime import datetime, timezone

import asyncpg

import main


def _run(coro_fn):
    async def _wrapped():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await coro_fn(pool)
        finally:
            await pool.close()
    asyncio.run(_wrapped())


async def _setup_org(pool, name: str) -> str:
    org_id = str(uuid.uuid4())
    slug = f"e2e-analytics-{uuid.uuid4().hex[:8]}"
    await pool.execute(
        """INSERT INTO organizations (id, name, slug, plan, billing_status)
           VALUES ($1,$2,$3,'starter','trialing')""",
        org_id, name, slug,
    )
    return org_id


async def _setup_bot(pool, org_id: str) -> str:
    bot_id = str(uuid.uuid4())
    await pool.execute(
        """INSERT INTO bots (id, org_id, name, status, primary_color, greeting, language, system_prompt)
           VALUES ($1,$2,'Analytics Test Bot','active','#0066FF','Halo','id','Kamu adalah asisten.')""",
        bot_id, org_id,
    )
    return bot_id


async def _insert_conversation(pool, *, org_id: str, bot_id: str) -> str:
    conv_id = str(uuid.uuid4())
    await pool.execute(
        """INSERT INTO conversations (id, bot_id, org_id, channel, started_at)
           VALUES ($1,$2,$3,'widget',$4)""",
        conv_id, bot_id, org_id, datetime.now(timezone.utc),
    )
    return conv_id


def test_analytics_excludes_conversation_with_mismatched_org_id():
    async def body(pool):
        owner_org = await _setup_org(pool, "Analytics Owner Org")
        other_org = await _setup_org(pool, "Analytics Other Org")
        bot_id = await _setup_bot(pool, owner_org)

        # Legitimate conversation: bot_id and org_id correctly paired.
        await _insert_conversation(pool, org_id=owner_org, bot_id=bot_id)

        # Simulated data inconsistency: same bot_id, but tagged with a
        # DIFFERENT org_id. This should never happen via the normal app
        # flow, but the analytics query must not trust bot_id alone.
        await _insert_conversation(pool, org_id=other_org, bot_id=bot_id)

        result = await main.get_analytics(
            bot_id=bot_id, days=30, user={"org_id": owner_org}, pool=pool,
        )
        assert result["summary"]["total_convs"] == 1, result

    _run(body)


def test_analytics_rejects_bot_not_owned_by_caller_org():
    async def body(pool):
        owner_org = await _setup_org(pool, "Analytics Owner Org 2")
        intruder_org = await _setup_org(pool, "Analytics Intruder Org")
        bot_id = await _setup_bot(pool, owner_org)

        from fastapi import HTTPException
        try:
            await main.get_analytics(
                bot_id=bot_id, days=30, user={"org_id": intruder_org}, pool=pool,
            )
            raise AssertionError("expected HTTPException 404")
        except HTTPException as exc:
            assert exc.status_code == 404

    _run(body)
