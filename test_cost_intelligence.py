import asyncio
from decimal import Decimal

from agent_observability import add_token_usage, observe_agent, trace_request
from cost_intelligence import budget_status, choose_model, estimate_cost_usd


class FakePool:
    def __init__(self):
        self.calls = []

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        return "OK"


def test_official_groq_token_pricing_estimate():
    assert estimate_cost_usd("llama-3.1-8b-instant", 1_000_000, 1_000_000) == Decimal("0.13000000")
    assert estimate_cost_usd("llama-3.3-70b-versatile", 1_000_000, 1_000_000) == Decimal("1.38000000")
    assert estimate_cost_usd("unknown-model", 1_000_000, 1_000_000) == Decimal("1.38000000")


def test_budget_thresholds():
    assert budget_status(79, 100)["level"] == "healthy"
    assert budget_status(80, 100)["level"] == "warning"
    assert budget_status(90, 100)["level"] == "critical"
    assert budget_status(100, 100)["level"] == "exceeded"


def test_model_routing_uses_economy_for_simple_and_quality_for_complex():
    simple = choose_model("berapa harga paket?", "standard", "cheap-model", "strong-model")
    complex_route = choose_model(
        "Analisis kenapa penjualan turun dan rekomendasikan strategi.",
        "pro",
        "cheap-model",
        "strong-model",
    )

    assert (simple.complexity, simple.model, simple.tier) == ("simple", "cheap-model", "economy")
    assert (complex_route.complexity, complex_route.model, complex_route.tier) == (
        "complex", "strong-model", "quality",
    )


def test_cost_record_tracks_tenant_conversation_agent_model_and_channel():
    pool = FakePool()
    context = {
        "org_id": "00000000-0000-0000-0000-000000000001",
        "conversation_id": "00000000-0000-0000-0000-000000000002",
        "user_message": "berapa harga paket?",
        "reasoning_mode": "standard",
        "metadata": {"channel": "whatsapp"},
        "_cheap_model": "llama-3.1-8b-instant",
        "_strong_model": "llama-3.3-70b-versatile",
        "_observability_pool": pool,
    }

    class Result:
        final_answer = "Jawaban"
        errors = []

    async def agent_call():
        add_token_usage(
            model="llama-3.1-8b-instant",
            prompt_tokens=1_000,
            completion_tokens=500,
        )
        return {"confidence": 0.9}

    async def operation():
        await observe_agent("cs_agent", context, agent_call)
        return Result()

    result = asyncio.run(trace_request(context, operation))
    cost_args = next(args for sql, args in pool.calls if "INSERT INTO cost_records" in sql)

    assert result.routed_model == "llama-3.1-8b-instant"
    assert cost_args[1] == context["org_id"]
    assert cost_args[2] == context["conversation_id"]
    assert cost_args[5] == "llama-3.1-8b-instant"
    assert cost_args[6] == "cs_agent"
    assert cost_args[9] == 1500
    assert cost_args[11] == "whatsapp"
    assert cost_args[10] > 0


def test_cost_intelligence_routes_are_mounted():
    import main

    paths = {getattr(route, "path", "") for route in main.app.routes}
    assert "/api/cost-intelligence/summary" in paths
    assert "/api/cost-intelligence/budget" in paths
