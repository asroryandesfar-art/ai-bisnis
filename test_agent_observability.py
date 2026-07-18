import asyncio

import httpx

import agent_observability
from agent_observability import add_token_usage, observe_agent, trace_request
from bn_platform.ai_observability import build_ai_observability_router


def _ctx(pool):
    return {
        "org_id": "00000000-0000-0000-0000-000000000001",
        "conversation_id": "00000000-0000-0000-0000-000000000002",
        "user_message": "x",
        "_observability_pool": pool,
    }


def _final_update(pool):
    """Args UPDATE terakhir (yg set execution_end + retry_count)."""
    for sql, args in pool.calls:
        if "UPDATE agent_executions" in sql and "execution_end=$2" in sql:
            return args
    return None


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


def test_failure_records_nonblank_error_even_for_empty_exception():
    """Regresi: exception dgn str() KOSONG (mis. CancelledError / exception tanpa
    pesan) dulu tersimpan error_message blank → dashboard FAILED tanpa alasan.
    Sekarang tipe exception selalu tercatat (root cause terbaca)."""
    pool = FakePool()
    context = {
        "org_id": "00000000-0000-0000-0000-000000000001",
        "conversation_id": "00000000-0000-0000-0000-000000000002",
        "user_message": "x",
        "_observability_pool": pool,
    }

    class Boom(Exception):
        pass  # str(Boom()) == ""

    async def child():
        raise Boom()

    async def operation():
        await observe_agent("marketing_agent", context, child)
        return "unreachable"

    try:
        asyncio.run(trace_request(context, operation))
    except Exception:
        pass  # propagasi/tidak — yang penting UPDATE tercatat di finally

    updates = [args for sql, args in pool.calls if "UPDATE agent_executions" in sql]
    assert updates, "harus ada UPDATE agent_executions"
    status, error_message = updates[0][3], updates[0][4]
    assert status == "error"
    assert error_message and error_message.strip(), "error_message TIDAK boleh blank"
    assert "Boom" in error_message, "tipe exception harus tercatat sebagai root cause"


# ── Auto-retry transient + exponential backoff ──────────────────────────────
def test_is_transient_classification():
    assert agent_observability._is_transient(httpx.ConnectError("boom")) is True
    assert agent_observability._is_transient(asyncio.TimeoutError()) is True
    assert agent_observability._is_transient(RuntimeError("503 service unavailable")) is True
    assert agent_observability._is_transient(ValueError("bad prompt")) is False
    assert agent_observability._is_transient(KeyError("x")) is False


def test_transient_error_is_retried_then_succeeds(monkeypatch):
    monkeypatch.setattr(agent_observability, "_RETRY_BASE_DELAY", 0)  # tanpa delay di test
    pool = FakePool()
    ctx = _ctx(pool)
    attempts = {"n": 0}

    async def child():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise httpx.ConnectError("connection reset")   # transient
        return {"confidence_score": 90}

    async def operation():
        await observe_agent("finance_agent", ctx, child)
        return "ok"

    asyncio.run(trace_request(ctx, operation))
    assert attempts["n"] == 3                    # 1 awal + 2 retry
    args = _final_update(pool)
    assert args and args[3] == "success"         # akhirnya sukses
    assert args[10] == 2                          # retry_count tercatat


def test_non_transient_error_is_not_retried(monkeypatch):
    monkeypatch.setattr(agent_observability, "_RETRY_BASE_DELAY", 0)
    pool = FakePool()
    ctx = _ctx(pool)
    attempts = {"n": 0}

    async def child():
        attempts["n"] += 1
        raise ValueError("prompt invalid")         # non-transient → fail fast

    async def operation():
        await observe_agent("finance_agent", ctx, child)
        return "ok"

    try:
        asyncio.run(trace_request(ctx, operation))
    except Exception:
        pass
    assert attempts["n"] == 1                     # TIDAK di-retry
    args = _final_update(pool)
    assert args and args[3] == "error" and args[10] == 0


def test_transient_exhausted_records_retry_count(monkeypatch):
    monkeypatch.setattr(agent_observability, "_RETRY_BASE_DELAY", 0)
    monkeypatch.setattr(agent_observability, "_RETRY_MAX", 3)
    pool = FakePool()
    ctx = _ctx(pool)
    attempts = {"n": 0}

    async def child():
        attempts["n"] += 1
        raise httpx.ReadTimeout("timed out")        # selalu transient

    async def operation():
        await observe_agent("finance_agent", ctx, child)
        return "ok"

    try:
        asyncio.run(trace_request(ctx, operation))
    except Exception:
        pass
    assert attempts["n"] == 4                      # 1 + 3 retry
    args = _final_update(pool)
    assert args and args[3] == "error"
    assert args[10] == 3                            # retry_count = maks
    assert "retry" in (args[4] or "").lower()      # error mencatat jumlah retry


class SummaryPool:
    def __init__(self):
        self.queries = []

    async def fetchrow(self, sql, *args):
        self.queries.append(sql)
        return {"active_agents": 0, "failed_agents": 0}

    async def fetch(self, sql, *args):
        self.queries.append(sql)
        return []


def test_observability_health_uses_latest_execution_status():
    pool = SummaryPool()
    router = build_ai_observability_router(
        get_pool=lambda: pool,
        get_current_user=lambda: {"org_id": "org-1"},
    )
    endpoint = next(route.endpoint for route in router.routes if route.path.endswith("/summary"))

    result = asyncio.run(endpoint(days=7, user={"org_id": "org-1"}, pool=pool))

    assert result["metrics"]["failed_agents"] == 0
    assert "SELECT DISTINCT ON (agent_name)" in pool.queries[0]
    assert "status AS last_status" in pool.queries[1]
    assert "COUNT(*) FILTER (WHERE w.status='error')" in pool.queries[1]
