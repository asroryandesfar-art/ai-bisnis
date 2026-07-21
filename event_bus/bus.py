"""event_bus.bus — event bus in-process (P0-C).

Kurangi pemanggilan langsung antar-modul: produser `publish(type, payload)`,
konsumen `subscribe(type, handler)`. Backend default IN-PROCESS (sinkron per-
publish, error tiap handler DIISOLASI supaya satu konsumen gagal tak merusak
publisher/konsumen lain). Handler boleh sync atau async.

Backend Redis Streams (durable, konsumen async lintas-proses) = follow-up di
atas antarmuka yang sama (lihat ADR-0003).

Modul MANDIRI (tak impor main/bn_platform) → aman diuji & dipakai di mana saja.
"""
from __future__ import annotations

import inspect
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("botnesia.event_bus")

WILDCARD = "*"


@dataclass
class Event:
    """Envelope event terstandardisasi."""
    type: str
    payload: dict = field(default_factory=dict)
    org_id: str | None = None
    trace_id: str | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "org_id": self.org_id,
                "trace_id": self.trace_id, "ts": self.ts, "payload": self.payload}


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Callable]] = {}

    def subscribe(self, event_type: str, handler: Callable[[Event], Any]) -> Callable[[], None]:
        """Daftarkan handler untuk `event_type` (atau WILDCARD '*' untuk semua).
        Return fungsi unsubscribe."""
        self._subs.setdefault(event_type, []).append(handler)

        def _unsub() -> None:
            self.unsubscribe(event_type, handler)
        return _unsub

    def unsubscribe(self, event_type: str, handler: Callable) -> None:
        lst = self._subs.get(event_type)
        if lst and handler in lst:
            lst.remove(handler)
            if not lst:
                self._subs.pop(event_type, None)

    def _handlers_for(self, event_type: str) -> list[Callable]:
        return list(self._subs.get(event_type, ())) + list(self._subs.get(WILDCARD, ()))

    async def publish(self, event_type: str, payload: dict | None = None, *,
                      org_id: str | None = None, trace_id: str | None = None) -> int:
        """Terbitkan event ke semua handler (spesifik + wildcard). Error tiap
        handler diisolasi & dicatat. Return jumlah handler yang dipanggil."""
        event = Event(type=event_type, payload=dict(payload or {}),
                      org_id=org_id, trace_id=trace_id)
        handlers = self._handlers_for(event_type)
        for h in handlers:
            try:
                res = h(event)
                if inspect.isawaitable(res):
                    await res
            except Exception:
                logger.exception("event handler gagal (type=%s handler=%s)",
                                 event_type, getattr(h, "__name__", h))
        return len(handlers)

    def subscriptions(self) -> dict[str, int]:
        """Introspeksi: jumlah handler per event type."""
        return {k: len(v) for k, v in self._subs.items()}


# Singleton proses (dipakai lintas modul lewat event_bus.publish/subscribe).
_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


def set_event_bus(bus: EventBus | None) -> None:
    """Override/reset bus (dipakai test & wiring startup)."""
    global _bus
    _bus = bus
