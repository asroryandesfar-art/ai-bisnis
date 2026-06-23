"""
test_agent_skills.py — Tool Framework (Agent OS Phase 2): setiap agent AI
Workforce mendeklarasikan skills/tools/goals secara eksplisit (foundation
untuk "dynamically selectable per agent"), mirip GeneralAIAgent/ResearchAgent
dari Phase 1.
"""
from finance_agent import FinanceAgent
from marketing_agent import MarketingAgent
from hr_agent import HRAgent
from operations_agent import OperationsAgent
from security_agent import SecurityAgent
from executive_agent import ExecutiveAgent


def _assert_has_skills_tools_goals(cls):
    agent = cls(api_key=None)
    assert isinstance(agent.skills, list) and len(agent.skills) > 0
    assert isinstance(agent.tools, list)
    assert isinstance(agent.goals, list) and len(agent.goals) > 0


def test_finance_agent_has_skills_tools_goals():
    _assert_has_skills_tools_goals(FinanceAgent)


def test_marketing_agent_has_skills_tools_goals():
    _assert_has_skills_tools_goals(MarketingAgent)
    assert "channel_messaging" in MarketingAgent.tools


def test_hr_agent_has_skills_tools_goals():
    _assert_has_skills_tools_goals(HRAgent)


def test_operations_agent_has_skills_tools_goals():
    _assert_has_skills_tools_goals(OperationsAgent)


def test_security_agent_has_skills_tools_goals():
    _assert_has_skills_tools_goals(SecurityAgent)


def test_executive_agent_has_skills_tools_goals():
    _assert_has_skills_tools_goals(ExecutiveAgent)
