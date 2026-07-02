"""
agent_registry.py — Agent Directory + Admin Agent (AI Agent Platform Phase 5).

Katalog deklaratif setiap "digital employee" agent di platform ini (BUKAN
agent mesin-internal reasoning pipeline seperti Devil's Advocate/Verification/
Planner/Intent Classifier -- itu komponen reasoning, bukan "karyawan").
`list_agents()` membaca atribut `skills`/`tools`/`goals` yang SUDAH ADA di
tiap class lewat import dinamis -- tidak hardcode duplikat supaya tidak
drift kalau atribut itu berubah. `AdminAgent` murni agregasi fakta (gaya
`executive_agent.gather_synthesis_data()`), tanpa LLM -- saran lintas-domain
sudah jadi tugas Executive Agent, tidak diduplikasi di sini.
"""
from __future__ import annotations

import asyncio
import importlib

import asyncpg

from base import BaseAgent

CHAT_PIPELINE = "chat_pipeline"
AUTHENTICATED_API = "authenticated_api"

# (module_path, class_name, category, channel)
AGENT_DIRECTORY: list[tuple[str, str, str, str]] = [
    ("cs_agent", "CSAgent", "customer_service", CHAT_PIPELINE),
    ("intelligence.sales_agent", "SalesAgent", "sales", CHAT_PIPELINE),
    ("intelligence.faq_agent", "FAQAgent", "knowledge", CHAT_PIPELINE),
    ("intelligence.knowledge_agent", "KnowledgeAgent", "knowledge", CHAT_PIPELINE),
    ("finance_agent", "FinanceAgent", "finance", AUTHENTICATED_API),
    ("marketing_agent", "MarketingAgent", "marketing", AUTHENTICATED_API),
    ("hr_agent", "HRAgent", "hr", AUTHENTICATED_API),
    ("operations_agent", "OperationsAgent", "operations", AUTHENTICATED_API),
    ("security_agent", "SecurityAgent", "security", AUTHENTICATED_API),
    ("executive_agent", "ExecutiveAgent", "executive", AUTHENTICATED_API),
    ("workforce_orchestrator", "WorkforceOrchestratorAgent", "workforce", AUTHENTICATED_API),
    ("self_learning_engine", "SelfLearningAgent", "self_learning", AUTHENTICATED_API),
    ("general_ai_agent", "GeneralAIAgent", "general_ai", CHAT_PIPELINE),
    ("research_agent", "ResearchAgent", "research", AUTHENTICATED_API),
    ("computer_agent", "ComputerAgent", "computer_use", CHAT_PIPELINE),
]


def list_agents() -> list[dict]:
    agents: list[dict] = []
    for module_path, class_name, category, channel in AGENT_DIRECTORY:
        try:
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
        except Exception:
            continue
        agents.append({
            "name": getattr(cls, "name", class_name),
            "class_name": class_name,
            "category": category,
            "channel": channel,
            "skills": list(getattr(cls, "skills", [])),
            "tools": list(getattr(cls, "tools", [])),
            "goals": list(getattr(cls, "goals", [])),
        })
    return agents


def get_agent(name: str) -> dict | None:
    for agent in list_agents():
        if agent["name"] == name:
            return agent
    return None


class AdminAgent(BaseAgent):
    name = "admin_agent"
    skills = ["agent_directory", "platform_health_overview"]
    tools: list[str] = []
    goals = [
        "Menyediakan daftar lengkap agent yang ada di platform beserta skills/tools/goals-nya.",
        "Menyediakan ringkasan aktivitas lintas-sistem (execution log, workforce, computer agent) untuk Agent Center Dashboard.",
    ]

    async def platform_overview(self, pool: asyncpg.Pool, org_id: str) -> dict:
        import execution_log
        import workforce_orchestrator
        import computer_agent

        async def _pending_local_agent_commands() -> list:
            rows = await pool.fetch(
                "SELECT id FROM local_agent_commands WHERE org_id=$1 AND status='pending_approval'",
                org_id,
            )
            return [dict(r) for r in rows]

        results = await asyncio.gather(
            execution_log.execution_log_summary(pool, org_id),
            workforce_orchestrator.dashboard_summary(pool, org_id),
            computer_agent.list_tasks(pool, org_id=org_id, status="pending_approval"),
            _pending_local_agent_commands(),
            return_exceptions=True,
        )

        def _safe(value: object, fallback):
            return fallback if isinstance(value, Exception) else value

        execution_summary, workforce_summary, pending_ca_tasks, pending_la_commands = results
        agents = list_agents()
        return {
            "agents": {
                "total": len(agents),
                "by_category": {agent["category"]: sum(1 for a in agents if a["category"] == agent["category"]) for agent in agents},
                "items": agents,
            },
            "execution_log": _safe(execution_summary, {"by_source_type": {}, "by_status": {}}),
            "workforce": _safe(workforce_summary, {}),
            "computer_agent_pending_approval_count": len(_safe(pending_ca_tasks, [])),
            "local_agent_pending_approval_count": len(_safe(pending_la_commands, [])),
        }
