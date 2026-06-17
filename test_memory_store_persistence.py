"""
Long-term memory (UserProfile facts + conversation summaries) moved from a
local JSON file (data/memory.json) to Postgres (user_memory_profiles,
conversation_memory_summaries) -- shared by every BotNesia process/worker
instead of being per-process and out of sync.

MemoryStore never caches profiles/summaries in-process once a pool is
given -- every read goes straight to Postgres -- so two independent
MemoryStore instances (simulating two separate worker processes) sharing
one pool can never silently clobber each other's writes the way the old
file-based "dump my whole in-memory state" approach could.
"""
import asyncio
import uuid

import asyncpg

import main
from memory_agent import MemoryStore


def _run(coro_fn):
    async def _wrapped():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await coro_fn(pool)
        finally:
            await pool.close()
    asyncio.run(_wrapped())


def test_two_independent_stores_writing_different_users_dont_clobber_each_other():
    """Simulates two separate worker processes, each with their own
    MemoryStore instance, both backed by the same Postgres pool."""
    async def body(pool):
        org_id, bot_id = f"org-{uuid.uuid4().hex[:8]}", "bot-1"
        store_a = MemoryStore()
        store_b = MemoryStore()

        await store_a.apply_fact_updates(
            "user-a", org_id, bot_id,
            facts_to_store=[{"key": "name", "value": "Asrori"}], forget_keys=[], pool=pool,
        )
        await store_b.apply_fact_updates(
            "user-b", org_id, bot_id,
            facts_to_store=[{"key": "business_type", "value": "toko baju"}], forget_keys=[], pool=pool,
        )

        profile_a = await store_a.get_profile("user-a", org_id, bot_id, pool=pool)
        profile_b = await store_b.get_profile("user-b", org_id, bot_id, pool=pool)
        assert profile_a.facts["name"].value == "Asrori"
        assert profile_b.facts["business_type"].value == "toko baju"

    _run(body)


def test_get_profile_always_reads_fresh_even_if_other_store_wrote_after():
    """store_a never reloads internally -- but since MemoryStore doesn't
    cache when a pool is given, store_a's NEXT get_profile() call must see
    whatever store_b wrote in between, not a stale snapshot."""
    async def body(pool):
        org_id, bot_id = f"org-{uuid.uuid4().hex[:8]}", "bot-1"
        store_a = MemoryStore()
        store_b = MemoryStore()

        await store_a.apply_fact_updates(
            "user-a", org_id, bot_id,
            facts_to_store=[{"key": "name", "value": "Asrori"}], forget_keys=[], pool=pool,
        )
        await store_b.apply_fact_updates(
            "user-a", org_id, bot_id,
            facts_to_store=[{"key": "city", "value": "Gresik"}], forget_keys=[], pool=pool,
        )

        # store_a re-reads -- must see BOTH facts, since apply_fact_updates
        # always does a fresh read-modify-write, never trusts a cached copy.
        profile = await store_a.get_profile("user-a", org_id, bot_id, pool=pool)
        assert profile.facts["name"].value == "Asrori"
        assert profile.facts["city"].value == "Gresik"

    _run(body)


def test_conversation_summaries_persist_and_are_visible_across_store_instances():
    async def body(pool):
        conv_id = f"conv-{uuid.uuid4()}"
        store_a = MemoryStore()
        store_b = MemoryStore()

        await store_a.set_conversation_summary(conv_id, "Diskusi soal harga paket.", pool=pool)
        summary = await store_b.get_conversation_summary(conv_id, pool=pool)
        assert summary == "Diskusi soal harga paket."

    _run(body)


def test_forget_keys_removes_fact_in_db():
    async def body(pool):
        org_id, bot_id = f"org-{uuid.uuid4().hex[:8]}", "bot-1"
        store = MemoryStore()
        await store.apply_fact_updates(
            "user-a", org_id, bot_id,
            facts_to_store=[{"key": "name", "value": "Asrori"}, {"key": "city", "value": "Gresik"}],
            forget_keys=[], pool=pool,
        )
        await store.apply_fact_updates(
            "user-a", org_id, bot_id,
            facts_to_store=[], forget_keys=["city"], pool=pool,
        )
        profile = await store.get_profile("user-a", org_id, bot_id, pool=pool)
        assert "name" in profile.facts
        assert "city" not in profile.facts

    _run(body)


def test_touch_profile_conv_count_increments_and_persists():
    async def body(pool):
        org_id, bot_id = f"org-{uuid.uuid4().hex[:8]}", "bot-1"
        store = MemoryStore()
        await store.touch_profile_conv_count("user-a", org_id, bot_id, pool=pool)
        await store.touch_profile_conv_count("user-a", org_id, bot_id, pool=pool)
        profile = await store.get_profile("user-a", org_id, bot_id, pool=pool)
        assert profile.total_convs == 2

    _run(body)


def test_without_pool_falls_back_to_in_process_dict_not_persistent():
    """No pool supplied (e.g. a lightweight unit test) -- still usable
    within one MemoryStore instance, but a second instance shares nothing.
    No real DB needed for this one -- exercises the pool=None fallback only."""
    async def body():
        store_a = MemoryStore()
        await store_a.apply_fact_updates(
            "user-a", "org-1", "bot-1",
            facts_to_store=[{"key": "name", "value": "Asrori"}], forget_keys=[], pool=None,
        )
        profile = await store_a.get_profile("user-a", "org-1", "bot-1", pool=None)
        assert profile.facts["name"].value == "Asrori"

        store_b = MemoryStore()
        profile_b = await store_b.get_profile("user-a", "org-1", "bot-1", pool=None)
        assert "name" not in profile_b.facts

    asyncio.run(body())
