"""Tests untuk Executive Agent (AI Workforce Phase 6): executive_agent.py
(sintesis lintas-agent, company health score, executive brief) dan
endpoint baru di bn_platform/executive.py.

Mengikuti pola FakePool queue-based dari test_operations_agent.py.
gather_synthesis_data() dimock lewat monkeypatch import-time (modul
finance_agent/marketing_agent/hr_agent/operations_agent/security_agent/
lead_engine diimpor LOKAL di dalam fungsi -- jadi kita patch atribut
`dashboard_summary`/`lead_funnel_summary` di modul aslinya)."""
import asyncio

import pytest
from fastapi import HTTPException

import executive_agent as exe
from bn_platform.executive import build_executive_router, ReportGenerateRequest


def _route(router, path, method):
    for r in router.routes:
        if r.path.endswith(path) and method in r.methods:
            return r.endpoint
    raise AssertionError(f"route not found: {method} {path}")


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

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return "OK"


def _patch_synthesis(monkeypatch, *, finance=None, marketing=None, hr=None, operations=None, security=None, sales=None):
    import finance_agent, marketing_agent, hr_agent, operations_agent, security_agent
    from bn_platform import lead_engine

    async def fake(pool, org_id):
        return finance or {}
    async def fake_marketing(pool, org_id):
        return marketing or {}
    async def fake_hr(pool, org_id):
        return hr or {}
    async def fake_ops(pool, org_id):
        return operations or {}
    async def fake_sec(pool, org_id):
        return security or {}
    async def fake_leads(pool, *, org_id):
        return sales or {"cold": 0, "warm": 0, "hot": 0}

    monkeypatch.setattr(finance_agent, "dashboard_summary", fake)
    monkeypatch.setattr(marketing_agent, "dashboard_summary", fake_marketing)
    monkeypatch.setattr(hr_agent, "dashboard_summary", fake_hr)
    monkeypatch.setattr(operations_agent, "dashboard_summary", fake_ops)
    monkeypatch.setattr(security_agent, "dashboard_summary", fake_sec)
    monkeypatch.setattr(lead_engine, "lead_funnel_summary", fake_leads)


# ─── Synthesis / health score ────────────────────────────────────

def test_gather_synthesis_data_combines_all_domains(monkeypatch):
    _patch_synthesis(
        monkeypatch,
        finance={"profit_30d_idr": 100}, marketing={"active_campaigns": 1},
        hr={"avg_evaluation_score_90d": 80}, operations={"health": {"score": 90}},
        security={"score": 95}, sales={"cold": 1, "warm": 2, "hot": 3},
    )
    pool = FakePool()
    result = asyncio.run(exe.gather_synthesis_data(pool, "org-1"))
    assert result["finance"]["profit_30d_idr"] == 100
    assert result["sales"]["hot"] == 3
    assert result["operations"]["health"]["score"] == 90


def test_gather_synthesis_data_degrades_gracefully_on_exception(monkeypatch):
    import finance_agent, marketing_agent, hr_agent, operations_agent, security_agent
    from bn_platform import lead_engine

    async def boom(pool, org_id):
        raise RuntimeError("db down")
    async def ok(pool, org_id):
        return {"x": 1}
    async def ok_leads(pool, *, org_id):
        return {"cold": 0, "warm": 0, "hot": 0}

    monkeypatch.setattr(finance_agent, "dashboard_summary", boom)
    monkeypatch.setattr(marketing_agent, "dashboard_summary", ok)
    monkeypatch.setattr(hr_agent, "dashboard_summary", ok)
    monkeypatch.setattr(operations_agent, "dashboard_summary", ok)
    monkeypatch.setattr(security_agent, "dashboard_summary", ok)
    monkeypatch.setattr(lead_engine, "lead_funnel_summary", ok_leads)

    pool = FakePool()
    result = asyncio.run(exe.gather_synthesis_data(pool, "org-1"))
    assert result["finance"] == {}
    assert result["marketing"] == {"x": 1}


def test_compute_company_health_score_all_healthy():
    data = {
        "finance": {"profit_30d_idr": 5000, "churn_pct": 0, "overdue_invoices_count": 0},
        "marketing": {"active_campaigns": 2, "content_due_now": 0},
        "hr": {"avg_evaluation_score_90d": 85, "pending_training_recommendations": 0},
        "operations": {"health": {"score": 95}},
        "security": {"score": 98},
        "sales": {"cold": 1, "warm": 2, "hot": 3},
    }
    result = exe.compute_company_health_score(data)
    assert result["label"] == "healthy"
    assert result["overall"] >= 90
    assert result["by_domain"]["operations"] == 95
    assert result["by_domain"]["security"] == 98


def test_compute_company_health_score_penalizes_problems():
    data = {
        "finance": {"profit_30d_idr": -100, "churn_pct": 20, "overdue_invoices_count": 5},
        "marketing": {"active_campaigns": 0, "content_due_now": 10},
        "hr": {"avg_evaluation_score_90d": 40, "pending_training_recommendations": 20},
        "operations": {"health": {"score": 5}},
        "security": {"score": 5},
        "sales": {"cold": 5, "warm": 3, "hot": 0},
    }
    result = exe.compute_company_health_score(data)
    assert result["label"] == "critical"
    assert result["by_domain"]["finance"] < 100
    assert result["by_domain"]["sales"] < 100


def test_compute_company_health_score_handles_missing_data():
    result = exe.compute_company_health_score({})
    assert result["overall"] >= 90
    assert result["label"] == "healthy"


# ─── Report generation ──────────────────────────────────────────

def test_generate_executive_report_rejects_invalid_type():
    pool = FakePool()
    with pytest.raises(ValueError):
        asyncio.run(exe.generate_executive_report(pool, "org-1", "bogus"))


def test_generate_executive_report_persists_with_brief(monkeypatch):
    _patch_synthesis(monkeypatch)
    pool = FakePool(fetchrow_results=[{"id": "report-1", "report_type": "weekly", "source": "executive"}])

    class FakeAgent:
        async def generate_executive_brief(self, synthesis, health):
            return {"executive_summary": "Bisnis sehat.", "growth_recommendations": ["Tambah campaign"],
                    "cost_optimization": [], "revenue_opportunities": [], "strategic_insights": []}

    report = asyncio.run(exe.generate_executive_report(pool, "org-1", "weekly", agent=FakeAgent()))
    assert report["id"] == "report-1"
    assert any("INSERT INTO ops_reports" in c[1] and "'executive'" in c[1] for c in pool.calls)


def test_dashboard_summary_returns_health_and_synthesis(monkeypatch):
    _patch_synthesis(monkeypatch, operations={"health": {"score": 70}}, security={"score": 80})
    pool = FakePool()
    result = asyncio.run(exe.dashboard_summary(pool, "org-1"))
    assert "health" in result and "synthesis" in result
    assert result["health"]["by_domain"]["operations"] == 70


# ─── ExecutiveAgent (LLM brief) ──────────────────────────────────

def test_generate_executive_brief_returns_none_when_llm_unavailable(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.4, max_tokens=1024, default=None):
        out = dict(default or {})
        out["_llm_unavailable"] = True
        return out

    monkeypatch.setattr(exe.ExecutiveAgent, "_call_llm_json", fake_call_llm_json)
    agent = exe.ExecutiveAgent(api_key="test-key")
    result = asyncio.run(agent.generate_executive_brief({}, {"overall": 80}))
    assert result is None


def test_generate_executive_brief_returns_structured_data(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.4, max_tokens=1024, default=None):
        return {"executive_summary": "Ringkasan.", "growth_recommendations": ["A"],
                "cost_optimization": ["B"], "revenue_opportunities": ["C"], "strategic_insights": ["D"]}

    monkeypatch.setattr(exe.ExecutiveAgent, "_call_llm_json", fake_call_llm_json)
    agent = exe.ExecutiveAgent(api_key="test-key")
    result = asyncio.run(agent.generate_executive_brief({}, {"overall": 80}))
    assert result["executive_summary"] == "Ringkasan."
    assert result["growth_recommendations"] == ["A"]


# ─── Executive Analytics Charts (Phase Next 13) ──────────────────

def test_gather_trend_series_returns_all_six_series_in_order():
    import datetime as dt
    day = dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc)
    pool = FakePool(fetch_results=[
        [{"day": day, "value": 1_000_000}],   # revenue_trend
        [{"day": day, "value": 3}],            # customer_growth
        [{"day": day, "value": 2}],            # sales_growth
        [{"day": day, "value": 66.7}],         # lead_conversion
        [{"day": day, "value": 4.5}],          # customer_satisfaction
        [{"day": day, "value": 8.2}],          # ai_performance
    ])
    result = asyncio.run(exe.gather_trend_series(pool, "org-1", days=30))
    assert result["revenue_trend"] == [{"date": "2026-06-01", "value": 1_000_000.0}]
    assert result["customer_growth"][0]["value"] == 3.0
    assert result["sales_growth"][0]["value"] == 2.0
    assert result["lead_conversion"][0]["value"] == 66.7
    assert result["customer_satisfaction"][0]["value"] == 4.5
    assert result["ai_performance"][0]["value"] == 8.2


def test_gather_trend_series_handles_empty_series():
    pool = FakePool(fetch_results=[[], [], [], [], [], []])
    result = asyncio.run(exe.gather_trend_series(pool, "org-1", days=7))
    assert all(result[key] == [] for key in ("revenue_trend", "customer_growth", "sales_growth", "lead_conversion", "customer_satisfaction", "ai_performance"))


def test_gather_trend_series_clamps_days_window():
    pool = FakePool(fetch_results=[[], [], [], [], [], []])
    asyncio.run(exe.gather_trend_series(pool, "org-1", days=9999))
    revenue_call = next(c for c in pool.calls if c[0] == "fetch" and "finance_transactions" in c[1])
    assert revenue_call[2][1] == 365


def test_trends_route_returns_series(monkeypatch):
    pool = FakePool(fetch_results=[[], [], [], [], [], []])
    router = _build_router(pool)
    handler = _route(router, "/trends", "GET")
    result = asyncio.run(handler(user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool, days=30))
    assert set(result.keys()) == {"revenue_trend", "customer_growth", "sales_growth", "lead_conversion", "customer_satisfaction", "ai_performance"}


# ─── AI Business Analyst (Phase Next 12) ─────────────────────────

def test_business_health_label_four_tiers():
    assert exe.business_health_label(95) == "Excellent"
    assert exe.business_health_label(80) == "Good"
    assert exe.business_health_label(60) == "Warning"
    assert exe.business_health_label(30) == "Critical"


def test_get_latest_synthesis_snapshot_none_when_no_report():
    pool = FakePool(fetchrow_results=[None])
    result = asyncio.run(exe.get_latest_synthesis_snapshot(pool, "org-1"))
    assert result is None


def test_get_latest_synthesis_snapshot_parses_json_string_data():
    import json
    pool = FakePool(fetchrow_results=[{"data": json.dumps({"synthesis": {"finance": {"revenue_30d_idr": 100}}, "health": {"overall": 70}})}])
    result = asyncio.run(exe.get_latest_synthesis_snapshot(pool, "org-1"))
    assert result["synthesis"]["finance"]["revenue_30d_idr"] == 100
    assert result["health"]["overall"] == 70


def test_compute_score_deltas_no_historical_data():
    deltas = exe.compute_score_deltas({}, {"overall": 80, "by_domain": {}}, None)
    assert deltas == {"has_historical_data": False}


def test_compute_score_deltas_computes_real_changes():
    current_synthesis = {"finance": {"revenue_30d_idr": 8_000_000, "churn_pct": 5}, "sales": {"cold": 2, "warm": 1, "hot": 1}}
    current_health = {"overall": 70, "by_domain": {"finance": 60, "sales": 80}}
    previous = {
        "synthesis": {"finance": {"revenue_30d_idr": 10_000_000, "churn_pct": 2}, "sales": {"cold": 1, "warm": 1, "hot": 3}},
        "health": {"overall": 85, "by_domain": {"finance": 90, "sales": 95}},
    }
    deltas = exe.compute_score_deltas(current_synthesis, current_health, previous)
    assert deltas["has_historical_data"] is True
    assert deltas["overall_score_delta"] == -15
    assert deltas["revenue_30d_idr_delta"] == -2_000_000
    assert deltas["hot_leads_delta"] == -2
    assert deltas["by_domain_delta"]["finance"] == -30


def test_analyze_business_returns_none_when_llm_unavailable(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.4, max_tokens=1536, default=None):
        out = dict(default or {})
        out["_llm_unavailable"] = True
        return out

    monkeypatch.setattr(exe.ExecutiveAgent, "_call_llm_json", fake_call_llm_json)
    agent = exe.ExecutiveAgent(api_key="test-key")
    result = asyncio.run(agent.analyze_business({}, {"overall": 80}, {"has_historical_data": False}))
    assert result is None


def test_analyze_business_returns_structured_data(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.4, max_tokens=1536, default=None):
        return {
            "executive_summary": "Ringkasan.",
            "root_cause_analysis": [{"question": "Mengapa skor turun?", "explanation": "Revenue turun 20%."}],
            "recommendations": {"high": ["Tagih invoice overdue"], "medium": [], "low": []},
            "action_plan": {"7_days": ["Hubungi pelanggan overdue"], "30_days": [], "90_days": []},
        }

    monkeypatch.setattr(exe.ExecutiveAgent, "_call_llm_json", fake_call_llm_json)
    agent = exe.ExecutiveAgent(api_key="test-key")
    result = asyncio.run(agent.analyze_business({}, {"overall": 70}, {"has_historical_data": False}))
    assert result["root_cause_analysis"][0]["question"] == "Mengapa skor turun?"
    assert result["recommendations"]["high"] == ["Tagih invoice overdue"]


def test_analyze_business_normalizes_array_executive_summary(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.4, max_tokens=2048, default=None):
        return {
            "executive_summary": ["Kalimat satu.", "Kalimat dua."],
            "root_cause_analysis": [], "recommendations": {"high": [], "medium": [], "low": []},
            "action_plan": {"7_days": [], "30_days": [], "90_days": []},
        }

    monkeypatch.setattr(exe.ExecutiveAgent, "_call_llm_json", fake_call_llm_json)
    agent = exe.ExecutiveAgent(api_key="test-key")
    result = asyncio.run(agent.analyze_business({}, {"overall": 70}, {"has_historical_data": False}))
    assert result["executive_summary"] == "Kalimat satu. Kalimat dua."


def test_run_business_analysis_combines_health_label_and_deltas(monkeypatch):
    _patch_synthesis(monkeypatch, operations={"health": {"score": 90}}, security={"score": 90})
    pool = FakePool(fetchrow_results=[None])

    class FakeAgent:
        async def analyze_business(self, synthesis, health, deltas):
            return {"executive_summary": "OK", "root_cause_analysis": [], "recommendations": {"high": [], "medium": [], "low": []}, "action_plan": {"7_days": [], "30_days": [], "90_days": []}}

    result = asyncio.run(exe.run_business_analysis(pool, "org-1", agent=FakeAgent()))
    assert result["business_health_label"] in ("Excellent", "Good", "Warning", "Critical")
    assert result["deltas"]["has_historical_data"] is False
    assert result["analysis"]["executive_summary"] == "OK"


def test_analyze_business_route_writes_audit_log(monkeypatch):
    _patch_synthesis(monkeypatch, operations={"health": {"score": 90}}, security={"score": 90})
    pool = FakePool(fetchrow_results=[None])
    router = _build_router(pool)
    handler = _route(router, "/analyze", "POST")
    result = asyncio.run(handler(user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool))
    assert "business_health_label" in result
    assert any("INSERT INTO audit_logs" in c[1] for c in pool.calls)


# ─── Router: RBAC gating ────────────────────────────────────────

def test_router_gates_every_route_with_executive_permission():
    requested_keys = []

    def recording_require_permission(key):
        requested_keys.append(key)
        async def _checker(user=None, pool=None):
            return user
        return _checker

    async def get_pool():
        return FakePool()

    async def get_current_user():
        return {"org_id": "org-1", "id": "user-1"}

    build_executive_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=recording_require_permission,
        get_agent_config=lambda: {"api_key": ""},
    )

    assert requested_keys.count("executive.read") == 4
    assert requested_keys.count("executive.write") == 2
    assert set(requested_keys) == {"executive.read", "executive.write"}


def _build_router(pool):
    async def get_pool():
        return pool

    async def get_current_user():
        return {"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}

    def require_permission(_key):
        return get_current_user

    return build_executive_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=require_permission, get_agent_config=lambda: {"api_key": ""},
    )


def test_generate_report_route_rejects_invalid_type():
    pool = FakePool()
    router = _build_router(pool)
    handler = _route(router, "/reports/generate", "POST")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(
            body=ReportGenerateRequest(report_type="bogus"),
            user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
        ))
    assert exc.value.status_code == 422


def test_get_report_route_404_when_not_found():
    pool = FakePool(fetchrow_results=[None])
    router = _build_router(pool)
    handler = _route(router, "/reports/{report_id}", "GET")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(
            report_id="r1", user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
        ))
    assert exc.value.status_code == 404
