"""Unit test for _build_self_knowledge (chat handler decomposition step 5)."""
import asyncio
import sys
import types

import main

_BOT = {"org_id": "22222222-2222-2222-2222-222222222222", "plan": "starter"}


def _install_fake_botnesia_knowledge(monkeypatch, self_ctx, biz_ctx, boom=False):
    mod = types.ModuleType("botnesia_knowledge")

    async def _self(*a, **k):
        if boom:
            raise RuntimeError("db down")
        return self_ctx

    async def _biz(*a, **k):
        return biz_ctx

    mod.build_self_knowledge_context = _self
    mod.build_business_context = _biz
    monkeypatch.setitem(sys.modules, "botnesia_knowledge", mod)


def test_appends_self_knowledge_and_returns_both(monkeypatch):
    _install_fake_botnesia_knowledge(monkeypatch, "SELF_CTX", "BIZ_CTX")
    system, self_ctx, biz_ctx = asyncio.run(main._build_self_knowledge(object(), _BOT, "bot-1", "SYS"))
    assert self_ctx == "SELF_CTX"
    assert biz_ctx == "BIZ_CTX"
    assert system == "SYS\n\nSELF_CTX"


def test_no_self_context_leaves_system_unchanged(monkeypatch):
    _install_fake_botnesia_knowledge(monkeypatch, "", "BIZ_CTX")
    system, self_ctx, biz_ctx = asyncio.run(main._build_self_knowledge(object(), _BOT, "bot-1", "SYS"))
    assert system == "SYS"
    assert self_ctx == ""
    assert biz_ctx == "BIZ_CTX"


def test_degrades_gracefully_on_error(monkeypatch):
    _install_fake_botnesia_knowledge(monkeypatch, "SELF", "BIZ", boom=True)
    system, self_ctx, biz_ctx = asyncio.run(main._build_self_knowledge(object(), _BOT, "bot-1", "SYS"))
    assert system == "SYS"
    assert self_ctx == ""
    assert biz_ctx == ""
