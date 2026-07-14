"""Characterization tests for the /chat/{bot_id} guard clauses.

/chat is the ~1130-line core endpoint with only live-LLM e2e coverage (which
fails without API keys). These pin its cheap, deterministic guard behaviors
(bot lookup, rate limit, monthly quota) without exercising the full pipeline —
a safety net for any future decomposition. Only the DB + rate-limiter
boundaries are mocked.
"""
import types

import pytest
from fastapi.testclient import TestClient

import main

_BOT = {
    "id": "bot-1", "org_id": "org-1", "system_prompt": "", "language": "id",
    "temperature": 0.5, "reasoning_mode": "standard", "computer_agent_enabled": False,
    "plan": "starter", "billing_status": "active", "conv_limit": 1000,
}


class FakePool:
    def __init__(self, bot=None, conv_count=0):
        self._bot = bot
        self._conv_count = conv_count

    async def fetchrow(self, sql, *a):
        if "FROM bots b" in sql:
            return self._bot
        return None

    async def fetchval(self, sql, *a):
        if "COUNT(*) FROM conversations" in sql:
            return self._conv_count
        return 0


def _fake_rate_limiter(status):
    async def check(**_kw):
        return types.SimpleNamespace(status=status, message="limit", retry_after_s=5)
    return types.SimpleNamespace(check=check)


@pytest.fixture
def client(monkeypatch):
    # Quota fallback path (no Phase 2 check_limit); rate limiter allows by default.
    monkeypatch.setattr(main, "_platform_check_limit", None)
    monkeypatch.setattr(main, "_platform_consume_conversation", None)
    monkeypatch.setattr(main, "_rate_limiter", _fake_rate_limiter(main.LimitStatus.ALLOWED))
    c = TestClient(main.app)
    try:
        yield c
    finally:
        main.app.dependency_overrides.pop(main.get_pool, None)


def _use_pool(pool):
    main.app.dependency_overrides[main.get_pool] = lambda: pool


def test_chat_unknown_or_inactive_bot_returns_404(client):
    _use_pool(FakePool(bot=None))
    r = client.post("/chat/nope", json={"message": "halo"})
    assert r.status_code == 404
    assert "Bot tidak aktif" in r.json()["detail"]


def test_chat_rate_limit_blocked_returns_429(client, monkeypatch):
    monkeypatch.setattr(main, "_rate_limiter", _fake_rate_limiter(main.LimitStatus.BLOCKED))
    _use_pool(FakePool(bot=_BOT))
    r = client.post("/chat/bot-1", json={"message": "halo"})
    assert r.status_code == 429
    assert r.headers.get("Retry-After") == "5"


def test_chat_monthly_quota_exceeded_returns_429(client):
    # Rate limiter ALLOWED, but conversations this month (5) >= conv_limit (0).
    bot = dict(_BOT, conv_limit=0)
    _use_pool(FakePool(bot=bot, conv_count=5))
    r = client.post("/chat/bot-1", json={"message": "halo"})
    assert r.status_code == 429
    assert "percakapan" in r.json()["detail"].lower()
