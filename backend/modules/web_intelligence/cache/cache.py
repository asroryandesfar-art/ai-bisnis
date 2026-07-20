"""Small dependency-free TTL cache for fetched pages (avoids re-hitting sites)."""
from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from typing import Any


class TTLCache:
    """Thread-unsafe (async single-loop) LRU+TTL cache. Bounded by `max_entries`."""

    def __init__(self, ttl_seconds: int = 900, max_entries: int = 512):
        self.ttl = max(1, int(ttl_seconds))
        self.max_entries = max(1, int(max_entries))
        self._store: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key_for(url: str, *, render: bool = False) -> str:
        return hashlib.sha256(f"{'render:' if render else ''}{url}".encode()).hexdigest()

    def get(self, key: str) -> Any | None:
        item = self._store.get(key)
        if item is None:
            self.misses += 1
            return None
        expires_at, value = item
        if time.time() > expires_at:
            self._store.pop(key, None)
            self.misses += 1
            return None
        self._store.move_to_end(key)
        self.hits += 1
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.time() + self.ttl, value)
        self._store.move_to_end(key)
        while len(self._store) > self.max_entries:
            self._store.popitem(last=False)  # evict oldest

    def clear(self) -> None:
        self._store.clear()

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "entries": len(self._store), "max_entries": self.max_entries,
            "ttl_seconds": self.ttl, "hits": self.hits, "misses": self.misses,
            "hit_rate": round(self.hits / total, 3) if total else 0.0,
        }


# Shared default cache instance for the module.
default_cache = TTLCache()
