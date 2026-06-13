import asyncio

from fastapi import HTTPException

from bn_platform.founder_os import (
    build_founder_insights,
    build_founder_router,
    calculate_health_score,
    percentage_change,
)


def _route(router, path, method):
    for route in router.routes:
        if route.path.endswith(path) and method in route.methods:
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


def test_percentage_change_handles_zero_baseline():
    assert percentage_change(100, 0) == 0.0
    assert percentage_change(0, 0) == 0.0
    assert percentage_change(120, 100) == 20.0


def test_health_score_is_bounded_and_exposes_components():
    result = calculate_health_score(growth=15, revenue=20, churn=2, usage=12, retention=92)
    assert 0 <= result["score"] <= 100
    assert result["label"] == "healthy"
    assert set(result["components"]) == {"growth", "revenue", "churn", "usage", "retention"}


def test_founder_insights_flag_revenue_churn_cost_and_failures():
    metrics = {
        "revenue_growth_rate": 15, "churn_rate": 8, "usage_growth_rate": 20,
        "profit_idr": -10, "ai_cost_usd": 100,
    }
    insights = build_founder_insights(
        metrics,
        high_cost_tenants=[{"name": "Acme", "ai_cost_usd": 40}],
        failing_agents=[{"agent_name": "cs_agent", "failure_rate": 25}],
    )
    titles = " ".join(item["title"] for item in insights)
    assert "Revenue naik" in titles
    assert "Churn" in titles
    assert "Operating profit negatif" in titles
    assert "Acme" in titles
    assert "cs_agent" in titles


def test_founder_router_enforces_platform_admin(monkeypatch):
    import bn_platform.founder_os as founder

    async def get_user():
        return {}

    async def get_pool():
        return None

    router = build_founder_router(get_pool=get_pool, get_current_user=get_user)
    access = _route(router, "/access", "GET")
    monkeypatch.setattr(founder, "_require_platform_admin", lambda user: (_ for _ in ()).throw(HTTPException(403)))
    try:
        asyncio.run(access(user={"email": "tenant@example.com"}))
        assert False, "access should be rejected"
    except HTTPException as exc:
        assert exc.status_code == 403


def test_founder_routes_are_mounted():
    import main

    paths = {getattr(route, "path", "") for route in main.app.routes}
    assert "/api/founder/access" in paths
    assert "/api/founder/overview" in paths
