"""platform_state.inprocess — backend default `InProcessStateStore`.

Menyimpan state di memori proses (persis perilaku BotNesia sekarang). Aman untuk
dev/test dan single-worker; TIDAK persisten lintas proses/restart. Dipakai selama
`STATE_BACKEND=inprocess` (default) → migrasi ke Redis bersifat opt-in & reversible.

Semua pembacaan waktu lewat `self._now()` supaya bisa di-mock deterministik di test
(kontrol TTL/rate-window tanpa `sleep`). Aman untuk asyncio single-thread: tak ada
`await` di tengah operasi baca-ubah-tulis → efektif atomik per event loop.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from platform_state.base import StateStore


class InProcessStateStore(StateStore):
    def __init__(self) -> None:
        self._kv: dict[str, tuple[str, float | None]] = {}      # key -> (value, expiry|None)
        self._hash: dict[str, dict[str, str]] = defaultdict(dict)
        self._hash_exp: dict[str, float] = {}
        self._list: dict[str, deque] = defaultdict(deque)
        self._list_exp: dict[str, float] = {}
        self._rate: dict[str, deque] = defaultdict(deque)       # key -> deque[timestamp]
        self._lock: dict[str, tuple[str, float]] = {}           # key -> (token, expiry)

    # ── clock (di-mock di test) ───────────────────────────────────────────
    def _now(self) -> float:
        return time.monotonic()

    @staticmethod
    def _is_expired(exp: float | None, now: float) -> bool:
        return exp is not None and now >= exp

    def _evict_kv(self, key: str) -> None:
        item = self._kv.get(key)
        if item and self._is_expired(item[1], self._now()):
            self._kv.pop(key, None)

    def _evict_hash(self, key: str) -> None:
        exp = self._hash_exp.get(key)
        if exp is not None and self._now() >= exp:
            self._hash.pop(key, None)
            self._hash_exp.pop(key, None)

    def _evict_list(self, key: str) -> None:
        exp = self._list_exp.get(key)
        if exp is not None and self._now() >= exp:
            self._list.pop(key, None)
            self._list_exp.pop(key, None)

    # ── key / value ──────────────────────────────────────────────────────
    async def get(self, key: str) -> str | None:
        self._evict_kv(key)
        item = self._kv.get(key)
        return item[0] if item else None

    async def set(self, key: str, value: str, *, ttl_s: int | None = None) -> None:
        exp = self._now() + ttl_s if ttl_s else None
        self._kv[key] = (str(value), exp)

    async def delete(self, key: str) -> None:
        self._kv.pop(key, None)
        self._hash.pop(key, None); self._hash_exp.pop(key, None)
        self._list.pop(key, None); self._list_exp.pop(key, None)

    async def incr(self, key: str, *, amount: int = 1, ttl_s: int | None = None) -> int:
        self._evict_kv(key)
        cur = self._kv.get(key)
        if cur:
            val = int(cur[0]) + amount
            exp = cur[1]                       # pertahankan TTL awal (seperti Redis INCR)
        else:
            val = amount
            exp = self._now() + ttl_s if ttl_s else None
        self._kv[key] = (str(val), exp)
        return val

    # ── hash ──────────────────────────────────────────────────────────────
    async def hset(self, key: str, field: str, value: str, *, ttl_s: int | None = None) -> None:
        self._evict_hash(key)
        self._hash[key][field] = str(value)
        if ttl_s:
            self._hash_exp[key] = self._now() + ttl_s

    async def hget(self, key: str, field: str) -> str | None:
        self._evict_hash(key)
        return self._hash.get(key, {}).get(field)

    async def hgetall(self, key: str) -> dict[str, str]:
        self._evict_hash(key)
        return dict(self._hash.get(key, {}))

    # ── list ────────────────────────────────────────────────────────────
    async def lpush_trim(self, key: str, value: str, *, maxlen: int, ttl_s: int | None = None) -> None:
        self._evict_list(key)
        dq = self._list[key]
        dq.appendleft(str(value))
        while len(dq) > maxlen:
            dq.pop()
        if ttl_s:
            self._list_exp[key] = self._now() + ttl_s

    async def lrange(self, key: str, start: int = 0, stop: int = -1) -> list[str]:
        self._evict_list(key)
        items = list(self._list.get(key, []))
        end = len(items) if stop == -1 else stop + 1
        return items[start:end]

    # ── rate limit (sliding-window log; meniru _check_rate_limit lama) ────
    async def rate_incr(self, key: str, *, window_s: int, limit: int) -> tuple[bool, int]:
        now = self._now()
        dq = self._rate[key]
        cutoff = now - window_s
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= limit:
            return (False, len(dq))            # ditolak → slot TIDAK dikonsumsi
        dq.append(now)
        return (True, len(dq))

    # ── distributed lock ──────────────────────────────────────────────────
    async def acquire_lock(self, key: str, *, ttl_s: int, token: str) -> bool:
        cur = self._lock.get(key)
        if cur and self._now() < cur[1]:
            return False
        self._lock[key] = (token, self._now() + ttl_s)
        return True

    async def release_lock(self, key: str, *, token: str) -> bool:
        cur = self._lock.get(key)
        if cur and cur[0] == token:
            self._lock.pop(key, None)
            return True
        return False

    async def healthcheck(self) -> bool:
        return True
