"""
test_research_agent.py — Research Agent: graceful degradation saat web
search belum dikonfigurasi (kondisi default project ini saat ini), dan
sanity check decompose_goal()/run() tanpa memanggil LLM/network sungguhan.
"""
import asyncio

from research_agent import ResearchAgent


def test_run_research_skips_gracefully_without_any_search_provider():
    agent = ResearchAgent(api_key=None)
    result = asyncio.run(agent.run_research("Cari pelanggan kuliner Jakarta"))
    assert result["success"] is False
    assert result["skipped"] is True
    assert "sub_queries" in result and len(result["sub_queries"]) >= 1


def test_run_research_returns_error_for_empty_goal():
    agent = ResearchAgent(api_key=None)
    result = asyncio.run(agent.run_research("   "))
    assert result["success"] is False
    assert "error" in result


def test_decompose_goal_falls_back_to_goal_itself_without_llm():
    agent = ResearchAgent(api_key=None)
    sub_queries = asyncio.run(agent.decompose_goal("Cari pelanggan kuliner Jakarta"))
    assert sub_queries == ["Cari pelanggan kuliner Jakarta"]


def test_run_returns_agent_result_with_skipped_output():
    agent = ResearchAgent(api_key=None)
    result = asyncio.run(agent.run({"goal": "Cari pelanggan kuliner Jakarta"}))
    assert result.agent == "research_agent"
    assert result.success is True
    assert result.output["skipped"] is True
