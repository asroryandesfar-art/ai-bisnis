"""P2-D — perf_cache TTLCache + RuntimeMonitor caching (kurangi query DB poll SSE)."""
import asyncio

from perf_cache import TTLCache, get_or_compute
from task_runtime import RuntimeMonitor


class _Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t


def test_ttlcache_hit_miss_and_expiry():
    clk = _Clock()
    c = TTLCache(clock=clk)
    assert c.get("k") is None                    # miss
    c.set("k", 42, ttl=10)
    assert c.get("k") == 42                       # hit
    clk.t = 9.9
    assert c.get("k") == 42                       # masih segar
    clk.t = 10.0
    assert c.get("k") is None                     # kedaluwarsa
    assert c.stats()["hits"] == 2 and c.stats()["misses"] == 2


def test_ttlcache_zero_ttl_bypass():
    c = TTLCache()
    c.set("k", 1, ttl=0)                          # ttl<=0 → tak disimpan
    assert c.get("k") is None


def test_ttlcache_maxsize_eviction():
    clk = _Clock()
    c = TTLCache(maxsize=3, clock=clk)
    for i in range(3):
        c.set(f"k{i}", i, ttl=100)
    c.set("k3", 3, ttl=100)                        # picu evict (penuh, semua segar → FIFO)
    assert len(c._d) <= 3


def test_get_or_compute_caches_and_bypasses():
    async def run():
        c = TTLCache()
        calls = {"n": 0}

        async def factory():
            calls["n"] += 1
            return {"v": calls["n"]}

        # ttl>0 → compute sekali, lalu hit
        r1 = await get_or_compute(c, "k", 60, factory)
        r2 = await get_or_compute(c, "k", 60, factory)
        assert r1 == r2 == {"v": 1} and calls["n"] == 1
        # ttl<=0 → selalu compute (tak sentuh cache)
        r3 = await get_or_compute(c, "k2", 0, factory)
        r4 = await get_or_compute(c, "k2", 0, factory)
        assert calls["n"] == 3 and r3 != r4
    asyncio.run(run())


class _CountingPool:
    """Pool palsu penghitung — RuntimeMonitor cuma butuh fetch/fetchrow."""
    def __init__(self): self.calls = 0
    async def fetch(self, q, *a): self.calls += 1; return []
    async def fetchrow(self, q, *a): self.calls += 1; return {}


def test_runtime_monitor_cache_collapses_db_calls():
    async def run():
        pool = _CountingPool()
        mon = RuntimeMonitor(cache_ttl_s=60.0)
        s1 = await mon.health_snapshot(pool, "org1", window_hours=24)
        after_first = pool.calls
        assert after_first > 0                     # query pertama nyata
        s2 = await mon.health_snapshot(pool, "org1", window_hours=24)
        assert pool.calls == after_first           # kedua: dari cache, DB tak dipukul
        assert s1 == s2
        # window beda → key beda → miss → query lagi
        await mon.health_snapshot(pool, "org1", window_hours=48)
        assert pool.calls > after_first
    asyncio.run(run())


def test_runtime_monitor_no_cache_default_hits_db_each_time():
    async def run():
        pool = _CountingPool()
        mon = RuntimeMonitor()                      # default ttl=0 → tanpa cache (byte-identik)
        await mon.health_snapshot(pool, "org1")
        n1 = pool.calls
        await mon.health_snapshot(pool, "org1")
        assert pool.calls == 2 * n1                 # tiap panggilan query DB lagi
    asyncio.run(run())
