"""P0-A validasi LINTAS-WORKER via satu server Redis (fakeredis) yang di-share
dua RedisStateStore — menembus jalur kode Redis + Lua yang sama (bukan InProcess).

Membuktikan rate-limit, distributed-lock, circuit-breaker, & working-memory STM
benar-benar konsisten antar "worker" (dua instance store atas satu Redis).
Ini bukti terkuat yang bisa dilakukan tanpa server Redis nyata (lihat
docs/RUNBOOK-staging-validation.md untuk validasi Redis/Celery asli).
"""
import asyncio

import pytest

fakeredis = pytest.importorskip("fakeredis")
import fakeredis  # noqa: E402
import fakeredis.aioredis as fr  # noqa: E402

from platform_state.redis_store import RedisStateStore  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _two_workers():
    server = fakeredis.FakeServer()
    a = RedisStateStore(fr.FakeRedis(server=server, decode_responses=True))
    b = RedisStateStore(fr.FakeRedis(server=server, decode_responses=True))
    return a, b


def test_rate_limit_shared_across_workers():
    a, b = _two_workers()

    async def s():
        assert (await a.rate_incr("rl:org", window_s=60, limit=2))[0] is True
        assert (await a.rate_incr("rl:org", window_s=60, limit=2))[0] is True
        # worker B melihat count yang sama → ditolak (limit global, bukan ×worker)
        assert await b.rate_incr("rl:org", window_s=60, limit=2) == (False, 2)
    _run(s())


def test_distributed_lock_across_workers():
    a, b = _two_workers()

    async def s():
        assert await a.acquire_lock("lock:job", ttl_s=30, token="A") is True
        assert await b.acquire_lock("lock:job", ttl_s=30, token="B") is False
        assert await b.release_lock("lock:job", token="B") is False    # token salah
        assert await a.release_lock("lock:job", token="A") is True
        assert await b.acquire_lock("lock:job", ttl_s=30, token="B") is True
    _run(s())


def test_kv_hash_list_shared_across_workers():
    a, b = _two_workers()

    async def s():
        await a.set("k", "v1")
        assert await b.get("k") == "v1"
        await a.hset("h", "f", "1")
        assert await b.hgetall("h") == {"f": "1"}
        await a.lpush_trim("stm", "m1", maxlen=5)
        assert await b.lrange("stm", 0, -1) == ["m1"]
    _run(s())


def test_circuit_breaker_shared_across_workers():
    """Dua worker: A membuka breaker (fail 3×) → B melihatnya open via Redis."""
    import ai_providers.router as router
    from platform_state import set_state_store

    a_store, b_store = _two_workers()
    breaker_a = router._CircuitBreaker()      # state lokal worker A
    breaker_b = router._CircuitBreaker()      # state lokal worker B (terpisah)

    async def s():
        set_state_store(a_store)              # "worker A"
        for _ in range(3):
            await breaker_a.fail("gemini")
        assert await breaker_a.is_open("gemini") is True
        set_state_store(b_store)              # "worker B" (state lokal kosong)
        assert await breaker_b.is_open("gemini") is True   # adopsi open dari Redis shared
    try:
        _run(s())
    finally:
        set_state_store(None)


def test_working_memory_stm_shared_across_workers():
    from memory_agent import MemoryStore
    from platform_state import set_state_store

    a_store, b_store = _two_workers()
    store_a, store_b = MemoryStore(), MemoryStore()

    async def s():
        set_state_store(a_store)
        await store_a.add_to_stm("conv1", "user", "halo")
        set_state_store(b_store)
        recent = await store_b.get_recent("conv1")          # worker B baca STM worker A
        assert [m["content"] for m in recent] == ["halo"]
    try:
        _run(s())
    finally:
        set_state_store(None)
