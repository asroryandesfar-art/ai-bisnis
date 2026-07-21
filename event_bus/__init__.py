"""event_bus — event bus in-process untuk BotNesia (P0-C).

Decouple produser/konsumen:

    from event_bus import subscribe, publish, TASK_FINISHED

    subscribe(TASK_FINISHED, on_task_finished)          # konsumen (mis. evaluasi)
    await publish(TASK_FINISHED, {"job_id": jid}, org_id=org)   # produser (P0-D)

Backend default in-process (error tiap handler diisolasi). Redis Streams durable =
follow-up (ADR-0003). Modul mandiri, zero wiring — konsumen mengadopsi bertahap.
"""
from event_bus.bus import (
    Event, EventBus, WILDCARD, get_event_bus, set_event_bus,
)
from event_bus.events import (
    TASK_STARTED, TASK_FINISHED, TASK_FAILED,
    MEMORY_UPDATED, KNOWLEDGE_UPDATED,
    BROWSER_FINISHED, SCRAPER_FINISHED, WORKFLOW_COMPLETED,
    ALL_EVENT_TYPES,
)


def subscribe(event_type, handler):
    """Daftarkan handler; return fungsi unsubscribe."""
    return get_event_bus().subscribe(event_type, handler)


def unsubscribe(event_type, handler):
    get_event_bus().unsubscribe(event_type, handler)


async def publish(event_type, payload=None, *, org_id=None, trace_id=None):
    """Terbitkan event ke bus proses. Return jumlah handler dipanggil."""
    return await get_event_bus().publish(
        event_type, payload, org_id=org_id, trace_id=trace_id)


__all__ = [
    "Event", "EventBus", "WILDCARD", "get_event_bus", "set_event_bus",
    "subscribe", "unsubscribe", "publish",
    "TASK_STARTED", "TASK_FINISHED", "TASK_FAILED",
    "MEMORY_UPDATED", "KNOWLEDGE_UPDATED",
    "BROWSER_FINISHED", "SCRAPER_FINISHED", "WORKFLOW_COMPLETED",
    "ALL_EVENT_TYPES",
]
