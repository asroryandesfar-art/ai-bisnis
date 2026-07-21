"""Tests untuk event_bus (P0-C)."""
import asyncio

import event_bus as eb
from event_bus import EventBus, set_event_bus


def _run(coro):
    return asyncio.run(coro)


def teardown_function():
    set_event_bus(None)                         # bus segar untuk test berikutnya


def test_subscribe_and_publish_sync_handler():
    set_event_bus(EventBus())
    seen = []
    eb.subscribe(eb.TASK_FINISHED, lambda e: seen.append(e.payload["job_id"]))

    async def s():
        n = await eb.publish(eb.TASK_FINISHED, {"job_id": "j1"}, org_id="org1")
        assert n == 1
    _run(s())
    assert seen == ["j1"]


def test_async_handler_awaited():
    set_event_bus(EventBus())
    seen = []

    async def handler(e):
        await asyncio.sleep(0)
        seen.append(e.type)

    eb.subscribe(eb.MEMORY_UPDATED, handler)
    _run(eb.publish(eb.MEMORY_UPDATED, {}))
    assert seen == [eb.MEMORY_UPDATED]


def test_wildcard_receives_all():
    set_event_bus(EventBus())
    got = []
    eb.subscribe(eb.WILDCARD, lambda e: got.append(e.type))

    async def s():
        await eb.publish(eb.TASK_STARTED, {})
        await eb.publish(eb.SCRAPER_FINISHED, {})
    _run(s())
    assert got == [eb.TASK_STARTED, eb.SCRAPER_FINISHED]


def test_handler_error_isolated():
    set_event_bus(EventBus())
    ok = []

    def bad(e):
        raise RuntimeError("boom")

    eb.subscribe(eb.TASK_FAILED, bad)
    eb.subscribe(eb.TASK_FAILED, lambda e: ok.append(True))
    # publisher tak ikut gagal; handler kedua tetap jalan
    n = _run(eb.publish(eb.TASK_FAILED, {}))
    assert n == 2 and ok == [True]


def test_unsubscribe():
    set_event_bus(EventBus())
    seen = []
    unsub = eb.subscribe(eb.KNOWLEDGE_UPDATED, lambda e: seen.append(1))
    _run(eb.publish(eb.KNOWLEDGE_UPDATED, {}))
    unsub()
    _run(eb.publish(eb.KNOWLEDGE_UPDATED, {}))
    assert seen == [1]                          # hanya sekali (setelah unsub tak dipanggil)


def test_no_handlers_returns_zero():
    set_event_bus(EventBus())
    assert _run(eb.publish(eb.WORKFLOW_COMPLETED, {})) == 0


def test_event_envelope_fields():
    set_event_bus(EventBus())
    captured = {}
    eb.subscribe(eb.TASK_STARTED, lambda e: captured.update(e.to_dict()))
    _run(eb.publish(eb.TASK_STARTED, {"x": 1}, org_id="o9", trace_id="t1"))
    assert captured["type"] == eb.TASK_STARTED
    assert captured["org_id"] == "o9" and captured["trace_id"] == "t1"
    assert captured["payload"] == {"x": 1}
    assert captured["id"] and captured["ts"] > 0


def test_subscriptions_introspection():
    set_event_bus(EventBus())
    eb.subscribe(eb.TASK_STARTED, lambda e: None)
    eb.subscribe(eb.TASK_STARTED, lambda e: None)
    eb.subscribe(eb.WILDCARD, lambda e: None)
    subs = eb.get_event_bus().subscriptions()
    assert subs[eb.TASK_STARTED] == 2 and subs[eb.WILDCARD] == 1
