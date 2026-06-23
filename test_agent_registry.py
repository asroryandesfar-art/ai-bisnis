"""
test_agent_registry.py — Agent Directory + Admin Agent (AI Agent Platform
Phase 5): list_agents() membaca skills/tools/goals tiap class dengan benar,
import gagal di-skip aman, AdminAgent.platform_overview() agregasi paralel
dengan graceful fallback (mirror pola test_executive_agent.py kalau ada).
"""
import asyncio

import agent_registry


def test_list_agents_returns_entry_for_every_directory_item():
    agents = agent_registry.list_agents()
    names = {a["name"] for a in agents}
    assert len(agents) == len(agent_registry.AGENT_DIRECTORY)
    assert "cs_agent" in names
    assert "computer_agent" in names
    assert "admin_agent" not in names  # AdminAgent sendiri tidak masuk direktori


def test_list_agents_every_entry_has_nonempty_skills_and_goals():
    for agent in agent_registry.list_agents():
        assert len(agent["skills"]) > 0, f"{agent['name']} missing skills"
        assert len(agent["goals"]) > 0, f"{agent['name']} missing goals"
        assert agent["channel"] in (agent_registry.CHAT_PIPELINE, agent_registry.AUTHENTICATED_API)


def test_list_agents_skips_unimportable_entry_gracefully(monkeypatch):
    bogus_directory = list(agent_registry.AGENT_DIRECTORY) + [("nonexistent_module_xyz", "Nope", "x", "y")]
    monkeypatch.setattr(agent_registry, "AGENT_DIRECTORY", bogus_directory)
    agents = agent_registry.list_agents()
    assert len(agents) == len(agent_registry.AGENT_DIRECTORY) - 1


def test_get_agent_returns_none_for_unknown_name():
    assert agent_registry.get_agent("does_not_exist") is None


def test_get_agent_returns_matching_entry():
    agent = agent_registry.get_agent("cs_agent")
    assert agent is not None
    assert agent["category"] == "customer_service"


class FakePool:
    pass


def test_platform_overview_combines_all_sources(monkeypatch):
    import execution_log
    import workforce_orchestrator
    import computer_agent

    async def fake_summary(pool, org_id):
        return {"by_source_type": {"chat_agent": 5}, "by_status": {"success": 5}}

    async def fake_dashboard(pool, org_id):
        return {"by_status": {"pending": 2}}

    async def fake_list_tasks(pool, *, org_id, status=None, limit=50):
        return [{"id": "t1"}, {"id": "t2"}]

    monkeypatch.setattr(execution_log, "execution_log_summary", fake_summary)
    monkeypatch.setattr(workforce_orchestrator, "dashboard_summary", fake_dashboard)
    monkeypatch.setattr(computer_agent, "list_tasks", fake_list_tasks)

    agent = agent_registry.AdminAgent(api_key=None)
    result = asyncio.run(agent.platform_overview(FakePool(), "org-1"))

    assert result["execution_log"]["by_source_type"]["chat_agent"] == 5
    assert result["workforce"]["by_status"]["pending"] == 2
    assert result["computer_agent_pending_approval_count"] == 2
    assert result["agents"]["total"] == len(agent_registry.AGENT_DIRECTORY)


def test_platform_overview_degrades_gracefully_on_partial_failure(monkeypatch):
    import execution_log
    import workforce_orchestrator
    import computer_agent

    async def fake_summary(pool, org_id):
        raise RuntimeError("db down")

    async def fake_dashboard(pool, org_id):
        return {"by_status": {}}

    async def fake_list_tasks(pool, *, org_id, status=None, limit=50):
        return []

    monkeypatch.setattr(execution_log, "execution_log_summary", fake_summary)
    monkeypatch.setattr(workforce_orchestrator, "dashboard_summary", fake_dashboard)
    monkeypatch.setattr(computer_agent, "list_tasks", fake_list_tasks)

    agent = agent_registry.AdminAgent(api_key=None)
    result = asyncio.run(agent.platform_overview(FakePool(), "org-1"))

    assert result["execution_log"] == {"by_source_type": {}, "by_status": {}}
    assert result["computer_agent_pending_approval_count"] == 0
