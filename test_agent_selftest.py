"""Agent readiness self-test — konstruksi + verifikasi tiap agent, laporan jujur."""
import agent_registry
from bn_platform.agent_selftest import run_agent_self_test

CONFIG = {
    "api_key": "", "model": "", "base_url": None, "app_url": "http://x",
    "gemini_api_key": "", "gemini_model": "", "gemini_pro_model": "",
    "gemini_timeout": 30, "gemini_max_retry": 3,
    "openrouter_api_key": "", "deepseek_api_key": "",
}


def test_self_test_runs_all_registry_agents():
    r = run_agent_self_test(CONFIG)
    assert r["total"] >= 15
    assert r["ok"] + r["failed"] == r["total"]
    names = {a["agent"] for a in r["agents"]}
    for expected in ("MarketingAgent", "MemoryAgent", "AnalyticsAgent",
                     "FinanceAgent", "ComputerAgent", "SalesAgent"):
        assert expected in names, expected


def test_ok_agents_expose_entrypoint():
    r = run_agent_self_test(CONFIG)
    ok = [a for a in r["agents"] if a["status"] == "ok"]
    assert ok
    assert all(a.get("entrypoint") for a in ok)


def test_failed_agent_is_reported_with_root_cause(monkeypatch):
    """Kegagalan konstruksi HARUS dilaporkan (bukan disembunyikan) + root cause."""
    orig = agent_registry.build_agent

    def boom(module_path, class_name, **kw):
        if class_name == "FinanceAgent":
            raise ImportError("No module named 'foo'")
        return orig(module_path, class_name, **kw)

    monkeypatch.setattr(agent_registry, "build_agent", boom)
    r = run_agent_self_test(CONFIG)
    fin = next(a for a in r["agents"] if a["agent"] == "FinanceAgent")
    assert fin["status"] == "failed"
    assert "ImportError" in fin["error"]
    assert "dependency" in fin["root_cause"].lower()
    assert fin["suggested_fix"]
    assert r["failed"] >= 1
    # failed diurutkan di atas
    assert r["agents"][0]["status"] == "failed"


def test_self_test_route_present():
    import main
    assert "/api/observability/self-test" in {getattr(r, "path", "") for r in main.app.routes}
