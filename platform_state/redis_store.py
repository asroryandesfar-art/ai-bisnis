"""platform_state.redis_store — backend `RedisStateStore` (lintas-worker).

Backend produksi opt-in (`STATE_BACKEND=redis`). Kontrak identik dengan
`InProcessStateStore`; operasi kritis atomik lewat Lua:
  - `rate_incr` : sliding-window LOG via ZSET (meniru persis `_check_rate_limit`;
                  slot tak dikonsumsi saat ditolak) — 1 round-trip, atomik.
  - `release_lock` : GET+DEL by-token atomik (cegah lepas milik worker lain).
`acquire_lock` = `SET NX PX` native. TTL kv/hash/list = `PEXPIRE` native.

Jam (`_now`) dipakai untuk skor ZSET rate-limit & bersifat wall-clock supaya
KONSISTEN antar-worker (asumsi host/NTP tersinkron; lihat ADR-0001). Bisa di-mock
di test untuk determinisme. Modul mandiri — hanya bergantung `redis.asyncio`.
"""
from __future__ import annotations

import time
import uuid

from platform_state.base import StateStore

# Sliding-window log rate limiter (atomik). KEYS[1]=key; ARGV=now,window_s,limit,member.
_RATE_LUA = """
local now=tonumber(ARGV[1]); local win=tonumber(ARGV[2]); local lim=tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now-win)
local c=redis.call('ZCARD', KEYS[1])
if c>=lim then return {0, c} end
redis.call('ZADD', KEYS[1], now, ARGV[4])
redis.call('PEXPIRE', KEYS[1], math.ceil(win*1000))
return {1, c+1}
"""

# Lepas lock HANYA bila token cocok (GET+DEL atomik).
_UNLOCK_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) else return 0 end
"""


class RedisStateStore(StateStore):
    def __init__(self, client) -> None:
        # client: redis.asyncio.Redis(decode_responses=True)
        self._r = client

    def _now(self) -> float:
        return time.time()          # wall-clock (shared antar-worker); mockable di test

    # ── key / value ──────────────────────────────────────────────────────
    async def get(self, key: str) -> str | None:
        return await self._r.get(key)

    async def set(self, key: str, value: str, *, ttl_s: int | None = None) -> None:
        if ttl_s:
            await self._r.set(key, str(value), px=int(ttl_s * 1000))
        else:
            await self._r.set(key, str(value))

    async def delete(self, key: str) -> None:
        await self._r.delete(key)

    async def incr(self, key: str, *, amount: int = 1, ttl_s: int | None = None) -> int:
        val = int(await self._r.incrby(key, amount))
        if ttl_s and val == amount:          # baru dibuat → set TTL sekali
            await self._r.pexpire(key, int(ttl_s * 1000))
        return val

    # ── hash ──────────────────────────────────────────────────────────────
    async def hset(self, key: str, field: str, value: str, *, ttl_s: int | None = None) -> None:
        await self._r.hset(key, field, str(value))
        if ttl_s:
            await self._r.pexpire(key, int(ttl_s * 1000))

    async def hget(self, key: str, field: str) -> str | None:
        return await self._r.hget(key, field)

    async def hgetall(self, key: str) -> dict[str, str]:
        return await self._r.hgetall(key)

    # ── list ────────────────────────────────────────────────────────────
    async def lpush_trim(self, key: str, value: str, *, maxlen: int, ttl_s: int | None = None) -> None:
        pipe = self._r.pipeline(transaction=True)
        pipe.lpush(key, str(value))
        pipe.ltrim(key, 0, maxlen - 1)
        if ttl_s:
            pipe.pexpire(key, int(ttl_s * 1000))
        await pipe.execute()

    async def lrange(self, key: str, start: int = 0, stop: int = -1) -> list[str]:
        return await self._r.lrange(key, start, stop)

    # ── rate limit (Lua atomik, sliding-window log) ───────────────────────
    async def rate_incr(self, key: str, *, window_s: int, limit: int) -> tuple[bool, int]:
        now = self._now()
        member = f"{now}:{uuid.uuid4().hex}"          # unik per request
        res = await self._r.eval(_RATE_LUA, 1, key, str(now), str(window_s), str(limit), member)
        return (int(res[0]) == 1, int(res[1]))

    # ── distributed lock ──────────────────────────────────────────────────
    async def acquire_lock(self, key: str, *, ttl_s: int, token: str) -> bool:
        return bool(await self._r.set(key, token, nx=True, px=int(ttl_s * 1000)))

    async def release_lock(self, key: str, *, token: str) -> bool:
        return int(await self._r.eval(_UNLOCK_LUA, 1, key, token)) == 1

    async def healthcheck(self) -> bool:
        try:
            return bool(await self._r.ping())
        except Exception:
            return False

    async def aclose(self) -> None:
        try:
            await self._r.aclose()
        except Exception:
            pass


def build_redis_store(url: str, *, max_connections: int = 50,
                      socket_timeout: float = 2.0) -> RedisStateStore:
    """Bangun RedisStateStore dari URL (dipakai wiring startup). Lazy import redis."""
    import redis.asyncio as redis_async
    client = redis_async.from_url(
        url, decode_responses=True, max_connections=max_connections,
        socket_timeout=socket_timeout, socket_connect_timeout=socket_timeout,
    )
    return RedisStateStore(client)
