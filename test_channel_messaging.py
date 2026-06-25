"""test_channel_messaging.py — channel_messaging.py (Tool Framework Phase 7):
persistence + approve/reject safety gate. Mirror pola test_computer_agent.py
(FakePool, no network/DB sungguhan)."""
import asyncio
import json

import channel_messaging as cm


class FakePool:
    def __init__(self, fetchrow_results=None, fetch_results=None):
        self.calls = []
        self._fetchrow_results = list(fetchrow_results or [])
        self._fetch_results = list(fetch_results or [])

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self._fetchrow_results.pop(0) if self._fetchrow_results else None

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return self._fetch_results.pop(0) if self._fetch_results else []


def test_create_task_always_starts_pending_approval():
    pool = FakePool(fetchrow_results=[{"id": "t1", "status": "pending_approval", "channel": "whatsapp"}])
    result = asyncio.run(cm.create_task(
        pool, org_id="org-1", bot_id=None, agent_name="marketing_agent",
        channel="whatsapp", recipient="6281234", message="Halo",
    ))
    assert result["status"] == "pending_approval"
    insert_sql = pool.calls[0][1]
    assert "pending_approval" in insert_sql


def test_approve_task_returns_none_when_not_pending_approval():
    pool = FakePool(fetchrow_results=[{"id": "t1", "status": "sent"}])
    result = asyncio.run(cm.approve_task(pool, org_id="org-1", task_id="t1", approver_id="user-1"))
    assert result is None


def test_approve_task_fails_honestly_when_channel_not_connected():
    pool = FakePool(fetchrow_results=[
        {"id": "t1", "status": "pending_approval", "channel": "whatsapp", "recipient": "628", "message": "hi", "agent_name": "marketing_agent"},
        None,  # _find_connection_id query -> no connected channel
        {"id": "t1", "status": "failed", "result": json.dumps({"success": False})},
    ])
    result = asyncio.run(cm.approve_task(pool, org_id="org-1", task_id="t1", approver_id="user-1"))
    assert result["status"] == "failed"
    update_sql, update_args = pool.calls[-1][1], pool.calls[-1][2]
    assert "UPDATE channel_message_tasks" in update_sql
    assert update_args[0] == "failed"


def test_reject_task_returns_none_when_not_pending_approval():
    pool = FakePool(fetchrow_results=[{"id": "t1", "status": "sent"}])
    result = asyncio.run(cm.reject_task(pool, org_id="org-1", task_id="t1", approver_id="user-1", reason="tidak relevan"))
    assert result is None


def test_reject_task_sets_rejected_status_and_reason():
    pool = FakePool(fetchrow_results=[
        {"id": "t1", "status": "pending_approval"},
        {"id": "t1", "status": "rejected", "rejected_reason": "tidak relevan"},
    ])
    result = asyncio.run(cm.reject_task(pool, org_id="org-1", task_id="t1", approver_id="user-1", reason="tidak relevan"))
    assert result["status"] == "rejected"
    assert result["rejected_reason"] == "tidak relevan"


def test_list_tasks_filters_by_status_when_given():
    pool = FakePool(fetch_results=[[{"id": "t1"}]])
    result = asyncio.run(cm.list_tasks(pool, org_id="org-1", status="pending_approval"))
    assert len(result) == 1
    assert "AND status=$2" in pool.calls[0][1]
