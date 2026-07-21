"""P0-A C3 — rate limiter (`bn_platform.security._check_rate_limit`) di atas StateStore.

Membuktikan perilaku 429 tak berubah (behavior-preserving) untuk backend in-process
DAN Redis (fakeredis). `_check_rate_limit` kini async; semua call-site di-await.
"""
import asyncio

import pytest
from fastapi import HTTPException

import bn_platform.security as sec
from platform_state import InProcessStateStore, set_state_store


def _run(coro):
    return asyncio.run(coro)


def teardown_function():
    set_state_store(None)                       # jangan bocorkan store ke test lain


def test_allows_until_limit_then_429_inprocess():
    set_state_store(InProcessStateStore())

    async def scenario():
        await sec._check_rate_limit("k", 2)                     # 1 ok
        await sec._check_rate_limit("k", 2)                     # 2 ok
        with pytest.raises(HTTPException) as ei:
            await sec._check_rate_limit("k", 2)                 # 3 → 429
        assert ei.value.status_code == 429
        assert ei.value.headers.get("Retry-After") == "60"
        # slot tak dikonsumsi saat ditolak → tetap 429
        with pytest.raises(HTTPException):
            await sec._check_rate_limit("k", 2)

    _run(scenario())


def test_keys_isolated():
    set_state_store(InProcessStateStore())

    async def scenario():
        await sec._check_rate_limit("a", 1)
        with pytest.raises(HTTPException):
            await sec._check_rate_limit("a", 1)
        await sec._check_rate_limit("b", 1)                     # key lain tak terpengaruh

    _run(scenario())


def test_parity_via_redis_backend():
    pytest.importorskip("fakeredis")
    import fakeredis.aioredis as fr
    from platform_state.redis_store import RedisStateStore

    set_state_store(RedisStateStore(fr.FakeRedis(decode_responses=True)))

    async def scenario():
        await sec._check_rate_limit("rk", 2)
        await sec._check_rate_limit("rk", 2)
        with pytest.raises(HTTPException) as ei:
            await sec._check_rate_limit("rk", 2)
        assert ei.value.status_code == 429

    _run(scenario())
