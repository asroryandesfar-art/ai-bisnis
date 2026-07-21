"""Wiring test P0-A C2 — main._init_shared_state() (startup shared-state).

Membuktikan: (a) default inprocess = tanpa efek, (b) backend=redis + URL tak
terjangkau → FAIL-OPEN ke inprocess (tak crash boot), (c) sukses → RedisStateStore
terpasang. Semua state global direset agar tak bocor ke test lain.
"""
import asyncio

import pytest

import main
from platform_state import InProcessStateStore, get_state_store, set_state_store


def _run(coro):
    return asyncio.run(coro)


def _reset():
    set_state_store(None)
    main._state_store_active = None
    main.cfg.state_backend = "inprocess"
    main.cfg.redis_url = ""


def test_default_inprocess_no_effect():
    _reset()
    _run(main._init_shared_state())
    assert main._state_store_active is None
    assert isinstance(get_state_store(), InProcessStateStore)
    _reset()


def test_redis_backend_failopen_on_unreachable():
    _reset()
    main.cfg.state_backend = "redis"
    main.cfg.redis_url = "redis://127.0.0.1:6390/0"      # port tak terpakai
    main.cfg.redis_socket_timeout_seconds = 0.15
    _run(main._init_shared_state())                       # tak boleh raise
    assert main._state_store_active is None               # fallback
    assert isinstance(get_state_store(), InProcessStateStore)
    _reset()


def test_redis_backend_success():
    pytest.importorskip("fakeredis")
    import fakeredis.aioredis as fr
    import platform_state
    from platform_state.redis_store import RedisStateStore

    _reset()
    fake = RedisStateStore(fr.FakeRedis(decode_responses=True))
    orig = platform_state.build_redis_store
    platform_state.build_redis_store = lambda url, **k: fake   # _init impor lazily dari sini
    try:
        main.cfg.state_backend = "redis"
        main.cfg.redis_url = "redis://fake/0"
        _run(main._init_shared_state())
        assert get_state_store() is fake
        assert main._state_store_active is fake
    finally:
        platform_state.build_redis_store = orig
        _reset()
