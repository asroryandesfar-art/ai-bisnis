"""
test_computer_agent.py — Computer Agent (AI Agent Platform Phase 3): SSRF
rejection, defense-in-depth write-plan rejection, read-only execution (mocked
Playwright, TIDAK ada browser/network nyata), dan persistensi
computer_agent_tasks (FakePool, mirror test_workforce_orchestrator.py).
"""
import asyncio
import json

import pytest

import computer_agent as ca


# ─── Fake Playwright harness (tidak ada browser/network nyata) ──────────

class FakePage:
    def __init__(self, *, title="Contoh Halaman", body_text="Halo dunia", raise_on_goto=None):
        self._title = title
        self._body_text = body_text
        self._raise_on_goto = raise_on_goto
        self.url = "https://example.com"
        self.goto_calls: list[str] = []
        self.click_calls: list[str] = []
        self.fill_calls: list[tuple] = []

    async def goto(self, url, timeout=None, wait_until=None):
        self.goto_calls.append(url)
        if self._raise_on_goto:
            raise self._raise_on_goto
        self.url = url

    async def title(self):
        return self._title

    async def inner_text(self, selector):
        return self._body_text

    async def screenshot(self):
        return b"\x89PNG-fake-bytes"

    class _Mouse:
        async def wheel(self, x, y):
            return None

    @property
    def mouse(self):
        return FakePage._Mouse()

    async def click(self, selector, timeout=None):
        self.click_calls.append(selector)

    async def fill(self, selector, value, timeout=None):
        self.fill_calls.append((selector, value))


class FakeContext:
    def __init__(self, page: FakePage):
        self._page = page
        self.closed = False

    async def new_page(self):
        return self._page

    async def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, page: FakePage):
        self._page = page
        self.contexts: list[FakeContext] = []

    async def new_context(self):
        ctx = FakeContext(self._page)
        self.contexts.append(ctx)
        return ctx


def _patch_browser(monkeypatch, page: FakePage):
    fake_browser = FakeBrowser(page)

    async def fake_get_browser():
        return fake_browser

    monkeypatch.setattr(ca, "_get_browser", fake_get_browser)
    return fake_browser


# ─── SSRF protection ──────────────────────────────────────────────────

def test_execute_read_only_rejects_private_ip_before_goto(monkeypatch):
    page = FakePage()
    _patch_browser(monkeypatch, page)
    agent = ca.ComputerAgent(api_key=None)
    steps = [{"action": "navigate", "target": "http://127.0.0.1/admin", "value": None}]
    result = asyncio.run(agent.execute_read_only(steps))
    assert result["success"] is False
    assert "ditolak" in result["error"]
    assert page.goto_calls == []  # tidak pernah dipanggil


def test_execute_read_only_rejects_cloud_metadata_ip(monkeypatch):
    page = FakePage()
    _patch_browser(monkeypatch, page)
    agent = ca.ComputerAgent(api_key=None)
    steps = [{"action": "navigate", "target": "http://169.254.169.254/latest/meta-data/", "value": None}]
    result = asyncio.run(agent.execute_read_only(steps))
    assert result["success"] is False
    assert page.goto_calls == []


def test_execute_read_only_allows_public_url(monkeypatch):
    page = FakePage(body_text="Konten publik")
    _patch_browser(monkeypatch, page)
    agent = ca.ComputerAgent(api_key=None)
    steps = [
        {"action": "navigate", "target": "https://example.com", "value": None},
        {"action": "read_text", "target": "", "value": None},
    ]
    result = asyncio.run(agent.execute_read_only(steps))
    assert result["success"] is True
    assert "Konten publik" in result["text"]
    assert page.goto_calls == ["https://example.com"]


# ─── Defense-in-depth: write plan tidak boleh auto-execute ───────────────

def test_execute_read_only_hard_rejects_write_plan(monkeypatch):
    def fail_if_called():
        raise AssertionError("_get_browser should not be called for a write plan")

    monkeypatch.setattr(ca, "_get_browser", fail_if_called)
    agent = ca.ComputerAgent(api_key=None)
    steps = [
        {"action": "navigate", "target": "https://example.com", "value": None},
        {"action": "click", "target": "#submit-btn", "value": None},
    ]
    result = asyncio.run(agent.execute_read_only(steps))
    assert result["success"] is False
    assert "approval" in result["error"]


def test_is_write_plan_detects_click_fill_submit():
    assert ca.is_write_plan([{"action": "click", "target": "#x"}])
    assert ca.is_write_plan([{"action": "fill", "target": "#x"}])
    assert ca.is_write_plan([{"action": "submit", "target": "#x"}])
    assert not ca.is_write_plan([{"action": "navigate", "target": "https://example.com"}])
    assert not ca.is_write_plan([{"action": "read_text", "target": ""}])
    assert not ca.is_write_plan([])


def test_execute_approved_plan_runs_write_step(monkeypatch):
    page = FakePage()
    _patch_browser(monkeypatch, page)
    agent = ca.ComputerAgent(api_key=None)
    steps = [
        {"action": "navigate", "target": "https://example.com/contact", "value": None},
        {"action": "fill", "target": "#name", "value": "Budi"},
        {"action": "click", "target": "#submit-btn", "value": None},
    ]
    result = asyncio.run(agent.execute_approved_plan(steps))
    assert result["success"] is True
    assert page.fill_calls == [("#name", "Budi")]
    assert page.click_calls == ["#submit-btn"]


# ─── plan_actions: graceful degradation ──────────────────────────────────

def test_plan_actions_returns_empty_list_when_llm_unavailable(monkeypatch):
    agent = ca.ComputerAgent(api_key=None)

    async def fake_call_llm_json(messages, **kwargs):
        return kwargs.get("default", {})

    monkeypatch.setattr(agent, "_call_llm_json", fake_call_llm_json)
    steps = asyncio.run(agent.plan_actions("buka halaman example.com"))
    assert steps == []


def test_plan_actions_caps_at_max_steps(monkeypatch):
    agent = ca.ComputerAgent(api_key=None)
    many_steps = [{"action": "navigate", "target": f"https://example.com/{i}"} for i in range(20)]

    async def fake_call_llm_json(messages, **kwargs):
        return {"steps": many_steps}

    monkeypatch.setattr(agent, "_call_llm_json", fake_call_llm_json)
    steps = asyncio.run(agent.plan_actions("goal"))
    assert len(steps) == ca.MAX_STEPS


def test_plan_actions_drops_unknown_actions(monkeypatch):
    agent = ca.ComputerAgent(api_key=None)

    async def fake_call_llm_json(messages, **kwargs):
        return {"steps": [{"action": "delete_everything", "target": "x"}, {"action": "navigate", "target": "https://example.com"}]}

    monkeypatch.setattr(agent, "_call_llm_json", fake_call_llm_json)
    steps = asyncio.run(agent.plan_actions("goal"))
    assert len(steps) == 1
    assert steps[0]["action"] == "navigate"


# ─── Persistensi (FakePool, mirror test_workforce_orchestrator.py) ───────

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


def test_create_task_inserts_with_correct_action_type():
    pool = FakePool(fetchrow_results=[{"id": "task-1", "status": "completed"}])
    steps = [{"action": "navigate", "target": "https://example.com"}]
    task = asyncio.run(ca.create_task(
        pool, org_id="org-1", bot_id="bot-1", conversation_id="conv-1",
        goal="baca halaman", steps=steps, status="completed",
    ))
    assert task["id"] == "task-1"
    insert_call = next(c for c in pool.calls if "INSERT INTO computer_agent_tasks" in c[1])
    assert insert_call[2][4] == "read"  # action_type


def test_create_task_marks_write_action_type_for_click_step():
    pool = FakePool(fetchrow_results=[{"id": "task-2"}])
    steps = [{"action": "click", "target": "#btn"}]
    asyncio.run(ca.create_task(
        pool, org_id="org-1", bot_id="bot-1", conversation_id=None,
        goal="klik tombol", steps=steps, status="pending_approval",
    ))
    insert_call = next(c for c in pool.calls if "INSERT INTO computer_agent_tasks" in c[1])
    assert insert_call[2][4] == "write"
    assert insert_call[2][9] is True  # requires_approval


def test_approve_task_returns_none_when_not_pending_approval():
    pool = FakePool(fetchrow_results=[{"id": "task-3", "status": "completed", "plan": "[]"}])
    result = asyncio.run(ca.approve_task(pool, org_id="org-1", task_id="task-3", approver_id="user-1"))
    assert result is None


def test_reject_task_updates_status(monkeypatch):
    pool = FakePool(fetchrow_results=[
        {"id": "task-4", "status": "pending_approval", "plan": "[]"},
        {"id": "task-4", "status": "rejected", "rejected_reason": "tidak relevan"},
    ])
    result = asyncio.run(ca.reject_task(pool, org_id="org-1", task_id="task-4", approver_id="user-1", reason="tidak relevan"))
    assert result["status"] == "rejected"
