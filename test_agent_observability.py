import asyncio

from agent_observability import add_token_usage, observe_agent, trace_request


class FakePool:
    def __init__(self):
        self.calls = []

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        return "OK"


def test_trace_records_agent_lifecycle_and_token_usage():
    pool = FakePool()
    context = {
        "org_id": "00000000-0000-0000-0000-000000000001",
        "conversation_id": "00000000-0000-0000-0000-000000000002",
        "user_message": "Analisis bisnis saya",
        "_observability_pool": pool,
    }

    class Result:
        final_answer = "Jawaban akhir"
        errors = []

    async def child():
        add_token_usage(model="test-model", prompt_tokens=12, completion_tokens=8)
        return {"confidence_score": 91, "reasoning_summary": "Data lalu kesimpulan"}

    async def operation():
        await observe_agent("planner_agent", context, child)
        return Result()

    result = asyncio.run(trace_request(context, operation))

    assert result.total_tokens == 20
    assert any("INSERT INTO ai_traces" in sql for sql, _ in pool.calls)
    assert any("INSERT INTO agent_executions" in sql for sql, _ in pool.calls)
    execution_updates = [
        args for sql, args in pool.calls if "UPDATE agent_executions" in sql
    ]
    assert any(args[8] == 20 for args in execution_updates)
    trace_update = next(args for sql, args in pool.calls if "UPDATE ai_traces" in sql)
    assert trace_update[6] == 20


def test_trace_is_fail_open_without_pool():
    context = {
        "org_id": "org-1",
        "conversation_id": "conv-1",
        "user_message": "Halo",
    }

    async def operation():
        return "ok"

    assert asyncio.run(trace_request(context, operation)) == "ok"


def test_observability_routes_are_mounted():
    import main

    paths = {getattr(route, "path", "") for route in main.app.routes}
    assert "/api/observability/summary" in paths
    assert "/api/observability/traces/{trace_id}" in paths
