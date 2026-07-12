"""Unit test for _maybe_run_computer_agent (chat handler decomposition step 3)."""
import asyncio
import types

import main

_BOT = {"org_id": "22222222-2222-2222-2222-222222222222", "computer_agent_enabled": True}


def _run(**over):
    kw = dict(
        bot=_BOT, message="buka contoh.com", bot_id="bot-1", conv_id="conv-1",
        user_meta={}, effective_lang="id", system="SYS", pool=object(),
    )
    kw.update(over)
    return asyncio.run(main._maybe_run_computer_agent(**kw))


def test_noop_when_disabled():
    system, shot = _run(bot={"org_id": "o", "computer_agent_enabled": False})
    assert system == "SYS" and shot is None


def test_noop_for_non_browsing_message(monkeypatch):
    monkeypatch.setattr(main.computer_agent, "looks_like_computer_agent_request", lambda m: False)
    system, shot = _run()
    assert system == "SYS" and shot is None


def test_read_only_success_augments_system_and_returns_screenshot(monkeypatch):
    monkeypatch.setattr(main.computer_agent, "looks_like_computer_agent_request", lambda m: True)
    monkeypatch.setattr(main, "_check_media_cooldown", lambda *a: 0)
    monkeypatch.setattr(main.computer_agent, "is_write_plan", lambda steps: False)
    monkeypatch.setattr(main.computer_agent, "COMPUTER_AGENT_DATA_BLOCK", "DATA_BLOCK")

    async def _create_task(*a, **k):
        return None

    monkeypatch.setattr(main.computer_agent, "create_task", _create_task)

    class _CA:
        def __init__(self, *a, **k):
            pass

        async def plan_actions(self, m):
            return [{"action": "read"}]

        async def execute_read_only(self, steps):
            return {"success": True, "text": "PAGE TEXT", "screenshot_url": "/media/x.png"}

    monkeypatch.setattr(main.computer_agent, "ComputerAgent", _CA)

    system, shot = _run()
    assert shot == "/media/x.png"
    assert "PAGE TEXT" in system
    assert "DATA_BLOCK" in system


def test_write_plan_is_queued_for_approval_not_executed(monkeypatch):
    monkeypatch.setattr(main.computer_agent, "looks_like_computer_agent_request", lambda m: True)
    monkeypatch.setattr(main, "_check_media_cooldown", lambda *a: 0)
    monkeypatch.setattr(main.computer_agent, "is_write_plan", lambda steps: True)
    created = {"status": None}

    async def _create_task(*a, **k):
        created["status"] = k.get("status")

    monkeypatch.setattr(main.computer_agent, "create_task", _create_task)

    class _CA:
        def __init__(self, *a, **k):
            pass

        async def plan_actions(self, m):
            return [{"action": "click"}]

        async def execute_read_only(self, steps):  # must NOT be called for write plans
            raise AssertionError("write plan must not auto-execute")

    monkeypatch.setattr(main.computer_agent, "ComputerAgent", _CA)

    system, shot = _run()
    assert created["status"] == "pending_approval"
    assert shot is None
    assert "approval" in system.lower()


def test_cooldown_skips_execution(monkeypatch):
    monkeypatch.setattr(main.computer_agent, "looks_like_computer_agent_request", lambda m: True)
    monkeypatch.setattr(main, "_check_media_cooldown", lambda *a: 30)  # cooling down
    system, shot = _run()
    assert system == "SYS" and shot is None
