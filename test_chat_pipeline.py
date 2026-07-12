"""Happy-path characterization test for the /chat/{bot_id} pipeline.

Complements test_chat_guards.py by exercising the full pipeline once end to end
with the supervisor mocked at get_supervisor(): new conversation -> user message
persist -> KB retrieval (empty) -> supervisor.process -> response assembly. Pins
the response contract (answer + routing metadata) so the chat handler can be
safely extracted/decomposed later. Only the DB, rate limiter, and supervisor
boundaries are mocked; the real handler logic runs.
"""
import types

import pytest
from fastapi.testclient import TestClient

import main

_BOT = {
    "id": "11111111-1111-1111-1111-111111111111",
    "org_id": "22222222-2222-2222-2222-222222222222",
    "system_prompt": "Kamu asisten.", "language": "id",
    "temperature": 0.5, "reasoning_mode": "standard", "computer_agent_enabled": False,
    "plan": "starter", "billing_status": "active", "conv_limit": 1000,
}


def _make_result(answer="Halo, ada yang bisa saya bantu?"):
    from supervisor import SupervisorResult
    return SupervisorResult(
        final_answer=answer, confidence=0.9, topics=[], suggested_followup=None,
        should_escalate=False, escalation_urgency="none", escalation_reason=None,
        escalation_message=None, recommended_team=None, sentiment={}, intent="general",
        bot_quality_score=0.0, friction_points=[], product_insights=[],
        conversation_summary="", trainer_score=0.0, improved_response=None,
        training_examples=[], prompt_suggestions=[], faq_match=None, sales_signals=[],
        sales_has_objection=False, sales_recommended_angle=None, kg_product_mentions=[],
        agent_results={}, total_latency_ms=10, errors=[],
        intent_routing={"intent": "general", "selected_agent": "CS", "confidence": 0.9},
    )


class FakePool:
    """Permissive asyncpg-pool stand-in for the chat happy path."""

    def __init__(self, bot=_BOT):
        self._bot = bot

    async def fetchrow(self, sql, *a):
        if "FROM bots b" in sql:
            return self._bot
        return None  # conversation lookup, human_queue -> none

    async def fetch(self, sql, *a):
        return []  # history, KB candidate chunks

    async def fetchval(self, sql, *a):
        return 0

    async def execute(self, sql, *a):
        return "OK"

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return pool

            async def __aexit__(self, *a):
                return False

        return _Ctx()

    def transaction(self):
        class _T:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *a):
                return False

        return _T()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "_platform_check_limit", None)
    # Force the supervisor pipeline path (not the opt-in DeepSeek-brain shortcut,
    # which would call a real API in envs where DEEPSEEK_BRAIN_ENABLED is set).
    monkeypatch.setattr(main.cfg, "deepseek_brain_enabled", False)

    # Neutralize fire-and-forget workflow triggers so the test never touches the
    # real DB via a background task (get_pool inside the create_task).
    async def _noop_trigger(*a, **k):
        return None

    monkeypatch.setattr(main, "_dispatch_workflow_trigger", _noop_trigger)

    async def _allowed(**_kw):
        return types.SimpleNamespace(status=main.LimitStatus.ALLOWED, message="", retry_after_s=0)

    monkeypatch.setattr(main, "_rate_limiter", types.SimpleNamespace(check=_allowed))

    fake_supervisor = types.SimpleNamespace(process=_proc)
    monkeypatch.setattr(main, "get_supervisor", lambda use_cloud: fake_supervisor)

    main.app.dependency_overrides[main.get_pool] = lambda: FakePool()
    c = TestClient(main.app)
    try:
        yield c
    finally:
        main.app.dependency_overrides.pop(main.get_pool, None)


async def _proc(_ctx):
    return _make_result()


def test_chat_happy_path_returns_answer_and_session(client):
    r = client.post("/chat/bot-1", json={"message": "halo"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"] == "Halo, ada yang bisa saya bantu?"
    assert body["session_id"]
    # routing metadata present in the response contract
    assert "intent" in body
    assert "sources" in body
