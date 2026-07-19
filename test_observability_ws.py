"""Realtime observability — hub pub/sub + event emission dari observe_agent."""
import asyncio

import agent_observability as ao
from agent_observability import observe_agent, trace_request
from bn_platform.observability_ws import ObservabilityHub


class FakePool:
    def __init__(self):
        self.calls = []

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        return "OK"


class FakeWS:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    async def send_json(self, event):
        if self.fail:
            raise RuntimeError("socket dead")
        self.sent.append(event)


def test_hub_broadcasts_to_org_and_prunes_dead():
    hub = ObservabilityHub()
    live, dead = FakeWS(), FakeWS(fail=True)
    hub.connect("org-1", live)
    hub.connect("org-1", dead)
    hub.connect("org-2", FakeWS())          # org lain tak ikut kebagian
    asyncio.run(hub.publish("org-1", {"type": "agent", "status": "running"}))
    assert live.sent == [{"type": "agent", "status": "running"}]
    assert dead not in hub._conns.get("org-1", set())   # koneksi mati dibersihkan
    assert hub.has("org-1")                              # yang hidup tetap ada


def test_disconnect_removes_and_cleans_empty_org():
    hub = ObservabilityHub()
    ws = FakeWS()
    hub.connect("org-x", ws)
    hub.disconnect("org-x", ws)
    assert not hub.has("org-x")
    assert "org-x" not in hub._conns


def test_observe_agent_emits_running_and_final_events():
    events = []

    def publisher(org_id, event):    # sinkron → _emit menangkap langsung (deterministik)
        events.append((org_id, event))

    ao.set_event_publisher(publisher)
    try:
        pool = FakePool()
        ctx = {
            "org_id": "00000000-0000-0000-0000-000000000001",
            "conversation_id": "00000000-0000-0000-0000-000000000002",
            "user_message": "x",
            "_observability_pool": pool,
        }

        async def child():
            return {"confidence_score": 90}

        async def operation():
            await observe_agent("finance_agent", ctx, child)
            return "ok"

        asyncio.run(trace_request(ctx, operation))
    finally:
        ao.set_event_publisher(None)

    statuses = [(e["agent_name"], e["status"]) for _, e in events]
    assert ("finance_agent", "running") in statuses
    assert ("finance_agent", "success") in statuses


def test_observability_ws_route_present():
    import main
    paths = {getattr(r, "path", "") for r in main.app.routes}
    assert "/api/observability/ws" in paths


def test_ws_endpoint_handshake_with_valid_token():
    """WS asli (TestClient) — token valid → 'connected' + koneksi terdaftar di hub."""
    import main
    from fastapi.testclient import TestClient
    from bn_platform.observability_ws import get_hub

    token = main.create_token("11111111-1111-1111-1111-111111111111",
                              "22222222-2222-2222-2222-222222222222")
    client = TestClient(main.app)
    with client.websocket_connect(f"/api/observability/ws?token={token}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "connected"
        assert get_hub().has("22222222-2222-2222-2222-222222222222")


def test_ws_endpoint_rejects_invalid_token():
    import main
    from fastapi.testclient import TestClient
    client = TestClient(main.app)
    with client.websocket_connect("/api/observability/ws?token=not-a-jwt") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
