"""Contract tests untuk platform_state.StateStore (P0-A C1).

Satu suite yang WAJIB lolos untuk SETIAP backend — di C2 dijalankan ulang untuk
RedisStateStore (parity). Sekarang: InProcessStateStore. Deterministik: waktu
di-mock lewat `store._now` (tanpa sleep). Fokus utama: `rate_incr` meniru persis
semantik `bn_platform.security._check_rate_limit` (behavior-preserving migration).
"""
import asyncio

from platform_state import InProcessStateStore, get_state_store, set_state_store


def _run(coro):
    return asyncio.run(coro)


def _clocked_store():
    """InProcessStateStore dengan clock yang bisa dimajukan manual."""
    store = InProcessStateStore()
    t = {"v": 1000.0}
    store._now = lambda: t["v"]                      # type: ignore[method-assign]
    return store, (lambda d: t.__setitem__("v", t["v"] + d))


# ── key/value ──────────────────────────────────────────────────────────────
def test_get_set_delete():
    store, _ = _clocked_store()
    assert _run(store.get("k")) is None
    _run(store.set("k", "v1"))
    assert _run(store.get("k")) == "v1"
    _run(store.delete("k"))
    assert _run(store.get("k")) is None


def test_ttl_expiry():
    store, advance = _clocked_store()
    _run(store.set("k", "v", ttl_s=10))
    assert _run(store.get("k")) == "v"
    advance(9)
    assert _run(store.get("k")) == "v"               # belum kadaluarsa
    advance(2)                                        # total 11 > 10
    assert _run(store.get("k")) is None               # kadaluarsa


def test_incr_atomic_and_ttl_on_create_only():
    store, advance = _clocked_store()
    assert _run(store.incr("c", ttl_s=10)) == 1
    assert _run(store.incr("c", amount=4)) == 5
    advance(11)
    assert _run(store.get("c")) is None               # TTL awal tetap berlaku
    assert _run(store.incr("c")) == 1                 # key baru lagi


# ── hash ────────────────────────────────────────────────────────────────────
def test_hash_ops():
    store, advance = _clocked_store()
    _run(store.hset("h", "fails", "2", ttl_s=300))
    _run(store.hset("h", "open_until", "1234"))
    assert _run(store.hget("h", "fails")) == "2"
    assert _run(store.hgetall("h")) == {"fails": "2", "open_until": "1234"}
    advance(301)
    assert _run(store.hgetall("h")) == {}             # hash kadaluarsa


# ── list (STM buffer) ───────────────────────────────────────────────────────
def test_list_lpush_trim_and_range():
    store, _ = _clocked_store()
    for i in range(5):
        _run(store.lpush_trim("stm", f"m{i}", maxlen=3))
    # hanya 3 terbaru, terbaru di kepala (m4, m3, m2)
    assert _run(store.lrange("stm", 0, -1)) == ["m4", "m3", "m2"]
    assert _run(store.lrange("stm", 0, 0)) == ["m4"]  # inklusif seperti Redis


# ── rate limit — meniru _check_rate_limit lama ──────────────────────────────
def test_rate_incr_allows_until_limit_then_blocks_without_consuming():
    store, advance = _clocked_store()
    # limit 3 / window 60s
    assert _run(store.rate_incr("rl:x", window_s=60, limit=3)) == (True, 1)
    assert _run(store.rate_incr("rl:x", window_s=60, limit=3)) == (True, 2)
    assert _run(store.rate_incr("rl:x", window_s=60, limit=3)) == (True, 3)
    # request ke-4 ditolak; count tetap 3 (slot TIDAK dikonsumsi)
    assert _run(store.rate_incr("rl:x", window_s=60, limit=3)) == (False, 3)
    assert _run(store.rate_incr("rl:x", window_s=60, limit=3)) == (False, 3)


def test_rate_incr_window_slides():
    store, advance = _clocked_store()
    _run(store.rate_incr("rl:y", window_s=60, limit=1))          # (True,1)
    assert _run(store.rate_incr("rl:y", window_s=60, limit=1)) == (False, 1)
    advance(61)                                                   # jendela geser
    assert _run(store.rate_incr("rl:y", window_s=60, limit=1)) == (True, 1)


def test_rate_incr_isolated_per_key():
    store, _ = _clocked_store()
    assert _run(store.rate_incr("a", window_s=60, limit=1)) == (True, 1)
    assert _run(store.rate_incr("b", window_s=60, limit=1)) == (True, 1)   # kunci lain bebas


# ── distributed lock ────────────────────────────────────────────────────────
def test_lock_nx_and_token_release():
    store, advance = _clocked_store()
    assert _run(store.acquire_lock("job:1", ttl_s=30, token="A")) is True
    assert _run(store.acquire_lock("job:1", ttl_s=30, token="B")) is False   # sudah dikunci
    assert _run(store.release_lock("job:1", token="B")) is False             # token salah
    assert _run(store.release_lock("job:1", token="A")) is True              # token benar
    assert _run(store.acquire_lock("job:1", ttl_s=30, token="B")) is True    # kini bebas


def test_lock_expires():
    store, advance = _clocked_store()
    assert _run(store.acquire_lock("job:2", ttl_s=10, token="A")) is True
    advance(11)
    assert _run(store.acquire_lock("job:2", ttl_s=10, token="B")) is True    # lease kadaluarsa


def test_healthcheck():
    store, _ = _clocked_store()
    assert _run(store.healthcheck()) is True


# ── factory ─────────────────────────────────────────────────────────────────
def test_factory_singleton_and_override():
    set_state_store(None)
    s1 = get_state_store()
    s2 = get_state_store()
    assert s1 is s2 and isinstance(s1, InProcessStateStore)
    custom = InProcessStateStore()
    set_state_store(custom)
    assert get_state_store() is custom
    set_state_store(None)                              # reset agar tak bocor ke test lain
