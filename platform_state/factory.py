"""platform_state.factory — pemilih backend + singleton `StateStore`.

C1 (sekarang): hanya `InProcessStateStore` (default, zero-behavior-change).
C2 (berikutnya): `get_state_store()` memilih Redis bila `STATE_BACKEND=redis`,
tanpa mengubah pemanggil. `set_state_store()` dipakai wiring startup & test.
"""
from __future__ import annotations

from platform_state.base import StateStore
from platform_state.inprocess import InProcessStateStore

_store: StateStore | None = None


def get_state_store() -> StateStore:
    """Kembalikan singleton StateStore proses. Default: in-process (perilaku lama)."""
    global _store
    if _store is None:
        _store = InProcessStateStore()
    return _store


def set_state_store(store: StateStore | None) -> None:
    """Override backend aktif (dipakai wiring startup C2 & isolasi test)."""
    global _store
    _store = store
