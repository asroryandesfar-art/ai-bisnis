"""perf_cache — TTL cache kecil untuk hot-path read-heavy & toleran-basi (P2-D).

Dipakai menekan beban DB duplikat pada endpoint poll (mis. SSE observability yang
mem-poll snapshot tiap interval dari BANYAK koneksi → tanpa cache = N× query
identik). Sengaja MINIMAL: dict + expiry monotonic, tanpa lock (single-flight tak
dijamin — dua miss bersamaan boleh sama-sama compute; TTL tetap mengumpulkan poll
sekuensial lintas koneksi). `ttl<=0` → BYPASS total (perilaku tanpa-cache identik).

Modul MANDIRI (tak impor app) → aman diuji & dipakai di mana saja.
"""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Hashable


class TTLCache:
    def __init__(self, *, maxsize: int = 1024, clock: Callable[[], float] = time.monotonic):
        self._d: dict[Hashable, tuple[float, Any]] = {}
        self._maxsize = max(1, int(maxsize))
        self._clock = clock
        self.hits = 0
        self.misses = 0

    def get(self, key: Hashable) -> Any:
        item = self._d.get(key)
        if item is None:
            self.misses += 1
            return None
        expires_at, value = item
        if self._clock() >= expires_at:
            self._d.pop(key, None)
            self.misses += 1
            return None
        self.hits += 1
        return value

    def set(self, key: Hashable, value: Any, ttl: float) -> None:
        if ttl <= 0:
            return
        if len(self._d) >= self._maxsize and key not in self._d:
            self._evict()
        self._d[key] = (self._clock() + ttl, value)

    def _evict(self) -> None:
        now = self._clock()
        for k in [k for k, (exp, _) in self._d.items() if exp <= now]:
            self._d.pop(k, None)
        if len(self._d) >= self._maxsize:               # masih penuh → buang tertua (FIFO-ish)
            try:
                self._d.pop(next(iter(self._d)))
            except StopIteration:
                pass

    def clear(self) -> None:
        self._d.clear()
        self.hits = self.misses = 0

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {"size": len(self._d), "hits": self.hits, "misses": self.misses,
                "hit_rate": round(self.hits / total, 4) if total else 0.0}


async def get_or_compute(cache: TTLCache, key: Hashable, ttl: float,
                         factory: Callable[[], Awaitable[Any]]) -> Any:
    """Kembalikan nilai cache bila segar; jika tidak, `await factory()` lalu simpan.
    `ttl<=0` → selalu compute (tak menyentuh cache) = identik tanpa-cache."""
    if ttl <= 0:
        return await factory()
    hit = cache.get(key)
    if hit is not None:
        return hit
    value = await factory()
    cache.set(key, value, ttl)
    return value
