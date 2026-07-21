"""platform_state — shared-state lintas-worker untuk BotNesia (P0-A).

Satu kontrak `StateStore`, dua backend (InProcess default, Redis opt-in di C2).
Dipakai untuk: rate-limit, circuit-breaker, working-memory, distributed-lock.
"""
from platform_state.base import StateStore
from platform_state.inprocess import InProcessStateStore
from platform_state.factory import get_state_store, set_state_store

__all__ = ["StateStore", "InProcessStateStore", "get_state_store", "set_state_store"]
