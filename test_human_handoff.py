import asyncio
from pathlib import Path

import pytest

from bn_platform.handoff import (
    enqueue_handoff,
    evaluate_handoff_trigger,
    reply_to_item,
    resolve_item,
)


@pytest.mark.parametrize(
    ("overrides", "reason", "priority"),
    [
        ({"confidence": 0.2}, "low_confidence", "high"),
        ({"final_answer": "Maaf, saya tidak tahu jawabannya."}, "ai_does_not_know", "medium"),
        ({"user_message": "Saya sangat marah dan kecewa."}, "angry_user", "high"),
        ({"user_message": "Tolong hubungkan ke manusia."}, "user_requested_human", "medium"),
        ({"errors": ["provider timeout"]}, "ai_error", "high"),
    ],
)
def test_handoff_trigger_covers_required_conditions(overrides, reason, priority):
    values = {
        "confidence": 0.9,
        "sentiment": {"label": "neutral", "score": 0},
        "should_escalate": False,
        "escalation_urgency": None,
        "escalation_reason": None,
        "friction_points": [],
        "user_message": "",
        "final_answer": "Jawaban tersedia.",
        "errors": [],
    }
    values.update(overrides)

    assert evaluate_handoff_trigger(**values) == (True, reason, priority)


class FakePool:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.calls = []

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self.rows.pop(0) if self.rows else None

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return "OK"


def test_enqueue_reopens_resolved_handoff_and_sets_conversation_flag():
    row = {"id": "handoff-1", "conversation_id": "conversation-1", "status": "waiting"}
    pool = FakePool([row])

    result = asyncio.run(enqueue_handoff(
        pool, org_id="tenant-1", conversation_id="conversation-1",
        reason="ai_error", priority="high",
    ))

    insert_sql = next(sql for kind, sql, _ in pool.calls if kind == "fetchrow")
    assert "status IN ('resolved','cancelled')" in insert_sql
    assert "assigned_agent_id" in insert_sql
    assert result["status"] == "waiting"
    assert any("handoff_needed=TRUE" in sql for kind, sql, _ in pool.calls if kind == "execute")


def test_human_reply_requires_assignment_and_is_attributed_to_agent():
    pool = FakePool([
        {"id": "handoff-1", "conversation_id": "conversation-1", "status": "assigned", "assigned_agent_id": "agent-1"},
        {"id": "message-1", "conversation_id": "conversation-1", "role": "assistant", "content": "Kami bantu.", "model": "human:agent-1"},
    ])

    result = asyncio.run(reply_to_item(
        pool, org_id="tenant-1", queue_id="handoff-1",
        agent_id="agent-1", message="Kami bantu.",
    ))

    message_call = pool.calls[1]
    assert "INSERT INTO messages" in message_call[1]
    assert message_call[2][2] == "human:agent-1"
    assert result["model"] == "human:agent-1"


def test_resolve_returns_conversation_control_to_ai():
    pool = FakePool([{"id": "handoff-1", "conversation_id": "conversation-1"}])

    asyncio.run(resolve_item(
        pool, org_id="tenant-1", queue_id="handoff-1", note="Selesai",
    ))

    conversation_sql = next(
        sql for kind, sql, _ in pool.calls
        if kind == "execute" and "UPDATE conversations" in sql
    )
    assert "handoff_needed=FALSE" in conversation_sql
    assert "assigned_agent_id=NULL" in conversation_sql
    assert "resolved=FALSE" in conversation_sql


def test_handoff_routes_and_schema_contract_are_present():
    import main

    paths = {getattr(route, "path", "") for route in main.app.routes}
    assert "/api/handoff/queue" in paths
    assert "/api/handoff/stats" in paths
    assert "/api/handoff/{queue_id}/claim" in paths
    assert "/api/handoff/{queue_id}/reply" in paths
    assert "/api/handoff/{queue_id}/resolve" in paths

    schema = (Path(__file__).resolve().parent / "schema.sql").read_text()
    assert "CREATE OR REPLACE VIEW handoffs AS" in schema
    for field in ("tenant_id", "conversation_id", "reason", "status", "assigned_to", "created_at"):
        assert field in schema
