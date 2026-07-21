"""Parity tests untuk RedisStateStore (P0-A C2).

Membuktikan RedisStateStore memenuhi kontrak yang SAMA dengan InProcessStateStore
(lihat test_platform_state.py). Memakai `fakeredis` (+`lupa` untuk Lua/EVAL).
Di-skip otomatis bila fakeredis tak terpasang → suite utama tetap hijau di mana pun
(dev-deps: `pip install fakeredis lupa`, lihat requirements-dev.txt).

Determinisme: operasi sensitif-waktu (rate_incr) memakai `store._now` yang di-mock;
TTL native (PEXPIRE) diverifikasi lewat `pttl` tanpa `sleep`.
"""
import asyncio

import pytest

fakeredis = pytest.importorskip("fakeredis")
import fakeredis.aioredis as fr  # noqa: E402

from platform_state.redis_store import RedisStateStore  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _store():
    return RedisStateStore(fr.FakeRedis(decode_responses=True))


def _clocked():
    store = _store()
    t = {"v": 1000.0}
    store._now = lambda: t["v"]                       # type: ignore[method-assign]
    return store, (lambda d: t.__setitem__("v", t["v"] + d))


# ── kv / incr (parity dengan InProcess) ─────────────────────────────────────
def test_get_set_delete():
    store = _store()
    assert _run(store.get("k")) is None
    _run(store.set("k", "v1"))
    assert _run(store.get("k")) == "v1"
    _run(store.delete("k"))
    assert _run(store.get("k")) is None


def test_set_ttl_applies_pexpire():
    store = _store()
    _run(store.set("k", "v", ttl_s=100))
    ttl_ms = _run(store._r.pttl("k"))
    assert 0 < ttl_ms <= 100_000                       # TTL benar-benar dipasang


def test_incr_atomic_and_ttl_on_create_only():
    store = _store()
    assert _run(store.incr("c", ttl_s=100)) == 1
    assert _run(store.incr("c", amount=4)) == 5
    ttl_ms = _run(store._r.pttl("c"))
    assert ttl_ms > 0                                   # TTL awal tetap ada


# ── hash (circuit-breaker shape) ────────────────────────────────────────────
def test_hash_ops():
    store = _store()
    _run(store.hset("h", "fails", "2", ttl_s=300))
    _run(store.hset("h", "open_until", "1234"))
    assert _run(store.hget("h", "fails")) == "2"
    assert _run(store.hgetall("h")) == {"fails": "2", "open_until": "1234"}
    assert _run(store._r.pttl("h")) > 0


# ── list (STM buffer) ───────────────────────────────────────────────────────
def test_list_lpush_trim_and_range():
    store = _store()
    for i in range(5):
        _run(store.lpush_trim("stm", f"m{i}", maxlen=3))
    assert _run(store.lrange("stm", 0, -1)) == ["m4", "m3", "m2"]
    assert _run(store.lrange("stm", 0, 0)) == ["m4"]


# ── rate limit — WAJIB identik dengan InProcess & _check_rate_limit ─────────
def test_rate_incr_allows_until_limit_then_blocks_without_consuming():
    store, _ = _clocked()
    assert _run(store.rate_incr("rl:x", window_s=60, limit=3)) == (True, 1)
    assert _run(store.rate_incr("rl:x", window_s=60, limit=3)) == (True, 2)
    assert _run(store.rate_incr("rl:x", window_s=60, limit=3)) == (True, 3)
    assert _run(store.rate_incr("rl:x", window_s=60, limit=3)) == (False, 3)
    assert _run(store.rate_incr("rl:x", window_s=60, limit=3)) == (False, 3)


def test_rate_incr_window_slides():
    store, advance = _clocked()
    _run(store.rate_incr("rl:y", window_s=60, limit=1))
    assert _run(store.rate_incr("rl:y", window_s=60, limit=1)) == (False, 1)
    advance(61)
    assert _run(store.rate_incr("rl:y", window_s=60, limit=1)) == (True, 1)


def test_rate_incr_isolated_per_key():
    store, _ = _clocked()
    assert _run(store.rate_incr("a", window_s=60, limit=1)) == (True, 1)
    assert _run(store.rate_incr("b", window_s=60, limit=1)) == (True, 1)


# ── distributed lock ────────────────────────────────────────────────────────
def test_lock_nx_and_token_release():
    store = _store()
    assert _run(store.acquire_lock("job:1", ttl_s=30, token="A")) is True
    assert _run(store.acquire_lock("job:1", ttl_s=30, token="B")) is False
    assert _run(store.release_lock("job:1", token="B")) is False    # token salah
    assert _run(store.release_lock("job:1", token="A")) is True
    assert _run(store.acquire_lock("job:1", ttl_s=30, token="B")) is True


def test_healthcheck():
    store = _store()
    assert _run(store.healthcheck()) is True
