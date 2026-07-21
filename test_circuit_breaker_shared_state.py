"""P0-A C4 — circuit breaker hybrid (ai_providers/router._CircuitBreaker).

Membuktikan: perilaku lokal identik versi lama (open setelah 3 gagal, reset saat
ok / setelah cooldown) DAN sharing lintas-worker via StateStore (open di satu
instance terlihat instance lain). `state()` tetap sync (tanpa I/O).
"""
import asyncio

import ai_providers.router as router
from ai_providers.router import _CircuitBreaker
from platform_state import InProcessStateStore, set_state_store


def _run(coro):
    return asyncio.run(coro)


def teardown_function():
    set_state_store(None)


def test_opens_after_threshold():
    set_state_store(InProcessStateStore())
    cb = _CircuitBreaker()

    async def s():
        assert await cb.is_open("p") is False
        await cb.fail("p"); await cb.fail("p")
        assert await cb.is_open("p") is False           # belum mencapai 3
        await cb.fail("p")                               # gagal ke-3 → open
        assert await cb.is_open("p") is True

    _run(s())


def test_ok_resets():
    set_state_store(InProcessStateStore())
    cb = _CircuitBreaker()

    async def s():
        for _ in range(3):
            await cb.fail("p")
        assert await cb.is_open("p") is True
        await cb.ok("p")
        assert await cb.is_open("p") is False
        assert cb.state("p")["fails"] == 0

    _run(s())


def test_cooldown_expiry(monkeypatch):
    set_state_store(InProcessStateStore())
    monkeypatch.setattr(router, "_RESET_SECS", 0.05)
    cb = _CircuitBreaker()

    async def s():
        for _ in range(3):
            await cb.fail("p")
        assert await cb.is_open("p") is True
        await asyncio.sleep(0.07)                         # lewati cooldown
        assert await cb.is_open("p") is False

    _run(s())


def test_cross_worker_sharing_via_shared_store():
    shared = InProcessStateStore()
    set_state_store(shared)                               # dua "worker" berbagi store
    a = _CircuitBreaker()
    b = _CircuitBreaker()

    async def s():
        for _ in range(3):
            await a.fail("gemini")                        # worker A membuka
        assert await a.is_open("gemini") is True
        # worker B (state lokal kosong) mengadopsi open dari shared store
        assert await b.is_open("gemini") is True

    _run(s())


def test_state_is_sync_no_io():
    set_state_store(InProcessStateStore())
    cb = _CircuitBreaker()
    _run(cb.fail("p"))
    st = cb.state("p")                                    # sync, tanpa await/I/O
    assert st["fails"] == 1 and st["open"] is False
