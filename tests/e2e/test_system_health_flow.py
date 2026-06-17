"""
E2E observability flow: hit the real /api/system-health endpoint through the
full FastAPI stack (auth -> RBAC -> system_health_report composition) and
confirm a chat call actually produces structured routing/KB-retrieval log
output (Section 10's "ensure routing decisions and KB retrieval timing are
actually logged" requirement), not just in-memory dataclasses.
"""
import logging


def test_system_health_endpoint_requires_auth(client):
    resp = client.get("/api/system-health")
    assert resp.status_code in (401, 403)


def test_system_health_endpoint_returns_composed_report(client, registered_org):
    resp = client.get("/api/system-health", headers=registered_org["headers"])
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["org_id"] == registered_org["org_id"]
    for key in ("http_metrics", "security", "top_issues_7d", "knowledge_health",
                "marketplace_health", "cost_health"):
        assert key in data, data


def test_chat_emits_structured_routing_and_kb_retrieval_logs(client, bot, chat_user_meta, caplog):
    with caplog.at_level(logging.INFO, logger="botnesia"):
        resp = client.post(f"/chat/{bot}", json={"message": "Apa itu Bitcoin?", "user_meta": chat_user_meta})
    assert resp.status_code == 200, resp.text
    messages = [r.message for r in caplog.records]
    assert any(m.startswith("kb_retrieval ") for m in messages), messages
    assert any(m.startswith("chat_routing ") for m in messages), messages
