"""P0-A C5 — working-memory STM (memory_agent.MemoryStore) di atas StateStore.

STM kini disimpan di platform_state.StateStore (`mem:stm:{conv}`, trim + TTL),
bukan dict in-process `_short` yang tumbuh selamanya. Perilaku observable tak
berubah (STM masih write-only untuk reasoning); test ini memverifikasi
penyimpanan/retrieval/trim/clear + paritas backend Redis.
"""
import asyncio

import pytest

from memory_agent import MemoryStore
from platform_state import InProcessStateStore, set_state_store


def _run(coro):
    return asyncio.run(coro)


def teardown_function():
    set_state_store(None)


def test_add_and_get_recent_chronological():
    set_state_store(InProcessStateStore())
    store = MemoryStore()

    async def s():
        await store.add_to_stm("c1", "user", "halo")
        await store.add_to_stm("c1", "assistant", "hai, ada yang bisa dibantu?")
        recent = await store.get_recent("c1")
        assert [m["role"] for m in recent] == ["user", "assistant"]      # lama→baru
        assert recent[0]["content"] == "halo"

    _run(s())


def test_trim_to_maxlen():
    set_state_store(InProcessStateStore())
    store = MemoryStore()

    async def s():
        for i in range(70):
            await store.add_to_stm("c2", "user", f"m{i}")
        recent = await store.get_recent("c2", n=200)
        assert len(recent) == 60                                          # _STM_MAXLEN
        assert recent[-1]["content"] == "m69"                             # terbaru dipertahankan

    _run(s())


def test_clear_and_isolation():
    set_state_store(InProcessStateStore())
    store = MemoryStore()

    async def s():
        await store.add_to_stm("a", "user", "x")
        await store.add_to_stm("b", "user", "y")
        await store.clear_stm("a")
        assert await store.get_recent("a") == []
        assert len(await store.get_recent("b")) == 1                      # conv lain aman

    _run(s())


def test_empty_conv_id_noop():
    set_state_store(InProcessStateStore())
    store = MemoryStore()

    async def s():
        await store.add_to_stm("", "user", "x")                          # tak crash
        assert await store.get_recent("") == []

    _run(s())


def test_stats_has_no_stm_leak_counter():
    set_state_store(InProcessStateStore())
    store = MemoryStore()
    st = store.stats()
    assert "active_conversations" not in st                              # STM tak lagi in-process
    assert "user_profiles_cached" in st


def test_parity_via_redis_backend():
    pytest.importorskip("fakeredis")
    import fakeredis.aioredis as fr
    from platform_state.redis_store import RedisStateStore

    set_state_store(RedisStateStore(fr.FakeRedis(decode_responses=True)))
    store = MemoryStore()

    async def s():
        await store.add_to_stm("rc", "user", "satu")
        await store.add_to_stm("rc", "assistant", "dua")
        recent = await store.get_recent("rc")
        assert [m["content"] for m in recent] == ["satu", "dua"]

    _run(s())
