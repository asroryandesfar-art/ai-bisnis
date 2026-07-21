"""platform_state — shared-state lintas-worker untuk BotNesia (P0-A).

Satu kontrak `StateStore`, dua backend (InProcess default, Redis opt-in di C2).
Dipakai untuk: rate-limit, circuit-breaker, working-memory, distributed-lock.
"""
from platform_state.base import StateStore
from platform_state.inprocess import InProcessStateStore
from platform_state.factory import get_state_store, set_state_store

# RedisStateStore diimpor lazily lewat helper agar `import platform_state` tidak
# menyeret dependensi redis saat backend default (inprocess) dipakai.

__all__ = [
    "StateStore", "InProcessStateStore", "get_state_store", "set_state_store",
    "build_redis_store",
]


def build_redis_store(url: str, **kwargs):
    """Bangun RedisStateStore (lazy import). Lihat platform_state.redis_store."""
    from platform_state.redis_store import build_redis_store as _b
    return _b(url, **kwargs)
