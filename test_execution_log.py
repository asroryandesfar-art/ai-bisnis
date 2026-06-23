"""Tests untuk execution_log.py (AI Agent Platform Phase 4) -- modul data
murni yang query VIEW agent_execution_log. Mengikuti pola FakePool
queue-based dari test_workforce_orchestrator.py/test_computer_agent.py."""
import asyncio

import execution_log as el


class FakePool:
    def __init__(self, fetch_results=None):
        self.calls = []
        self._fetch_results = list(fetch_results or [])

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return self._fetch_results.pop(0) if self._fetch_results else []


def test_list_execution_log_filters_by_source_type_and_status():
    pool = FakePool(fetch_results=[[{"source_type": "workforce_task", "status": "pending"}]])
    result = asyncio.run(el.list_execution_log(
        pool, org_id="org-1", source_type="workforce_task", status="pending",
    ))
    assert len(result) == 1
    sql, args = pool.calls[0][1], pool.calls[0][2]
    assert "agent_execution_log" in sql
    assert "source_type=$2" in sql
    assert "status=$3" in sql
    assert args == ("org-1", "workforce_task", "pending", 50)


def test_list_execution_log_no_filters():
    pool = FakePool(fetch_results=[[]])
    asyncio.run(el.list_execution_log(pool, org_id="org-1"))
    sql, args = pool.calls[0][1], pool.calls[0][2]
    assert "source_type=" not in sql
    assert "status=" not in sql
    assert args == ("org-1", 50)


def test_list_execution_log_caps_limit():
    pool = FakePool(fetch_results=[[]])
    asyncio.run(el.list_execution_log(pool, org_id="org-1", limit=9999))
    args = pool.calls[0][2]
    assert args[-1] == 200


def test_execution_log_summary_aggregates_by_source_and_status():
    pool = FakePool(fetch_results=[[
        {"source_type": "chat_agent", "status": "success", "cnt": 5},
        {"source_type": "workforce_task", "status": "pending", "cnt": 2},
        {"source_type": "workforce_task", "status": "completed", "cnt": 1},
    ]])
    result = asyncio.run(el.execution_log_summary(pool, "org-1"))
    assert result["by_source_type"]["chat_agent"] == 5
    assert result["by_source_type"]["workforce_task"] == 3
    assert result["by_status"]["pending"] == 2
    assert result["by_status"]["completed"] == 1
