"""test_digital_employees_tools.py — Phase 3: 5 Digital Employees (Finance/
HR/Marketing/Sales/Operations) harus punya tools NYATA (bukan list kosong/
label tanpa binding) dan bisa menjalankan run_task() lewat Task Engine
tanpa mengubah perilaku run()/parse_intent() lama sama sekali."""
import asyncio

import tool_executor
from base import BaseAgent
from finance_agent import FinanceAgent
from hr_agent import HRAgent
from marketing_agent import MarketingAgent
from operations_agent import OperationsAgent
from intelligence.sales_agent import SalesAgent

AGENT_CLASSES = [FinanceAgent, HRAgent, MarketingAgent, OperationsAgent, SalesAgent]


def test_no_digital_employee_has_empty_placeholder_tools():
    for cls in AGENT_CLASSES:
        assert cls.tools, f"{cls.__name__}.tools masih kosong -- placeholder agent"


def test_every_declared_tool_either_has_real_executor_or_is_documented_label():
    """Setiap nama di agent.tools harus: (a) ada di TOOL_SCHEMAS (executable
    nyata), ATAU (b) label lama yang sudah dikenal (channel_messaging,
    didokumentasikan tool_registry.py, tidak diubah Phase 1-3)."""
    known_labels = {"channel_messaging"}
    for cls in AGENT_CLASSES:
        for tool_name in cls.tools:
            assert tool_name in tool_executor.TOOL_SCHEMAS or tool_name in known_labels, (
                f"{cls.__name__} punya tool '{tool_name}' yang tidak executable dan tidak dikenal"
            )


def test_every_digital_employee_has_at_least_one_executable_tool():
    for cls in AGENT_CLASSES:
        executable = [t for t in cls.tools if t in tool_executor.TOOL_SCHEMAS]
        assert executable, f"{cls.__name__} tidak punya satu pun tool yang benar-benar executable"


def test_run_task_is_inherited_and_delegates_to_task_engine(monkeypatch):
    """run_task() ada di semua 5 agent (lewat BaseAgent), dan benar-benar
    memanggil task_engine.run_agent_task -- bukan no-op."""
    called = {}

    async def fake_run_agent_task(agent, goal, *, pool, org_id, bot_id=None, ctx=None):
        called["agent_name"] = agent.name
        called["goal"] = goal
        called["org_id"] = org_id
        return {"status": "completed", "report": "ok"}

    import task_engine
    monkeypatch.setattr(task_engine, "run_agent_task", fake_run_agent_task)

    for cls in AGENT_CLASSES:
        agent = cls(api_key="fake-key", model="test-model")
        result = asyncio.run(agent.run_task("goal uji", pool=None, org_id="org-1"))
        assert result["status"] == "completed"
        assert called["agent_name"] == agent.name
        assert called["org_id"] == "org-1"


def test_finance_agent_run_and_parse_intent_unchanged_by_phase3(monkeypatch):
    """Jalur lama (intent-classify -> dispatch aksi tetap) HARUS tetap
    berfungsi persis seperti sebelumnya -- Phase 3 cuma menambah, tidak
    mengganti."""
    async def fake_json(self, messages, **kwargs):
        return {"action": "unknown"}
    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_json)

    agent = FinanceAgent(api_key="fake-key", model="test-model")
    result = asyncio.run(agent.run({"user_message": "halo", "org_id": "org-1", "pool": object()}))
    # action="unknown" -> niat tidak dikenali, sama seperti perilaku asli sebelum Phase 3 (unchanged).
    assert result.success is False
    assert result.output["intent"]["action"] == "unknown"
