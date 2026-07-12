"""Unit test for _maybe_generate_chat_image (chat handler decomposition step 9)."""
import asyncio

import main
from fastapi import HTTPException

_BOT = {"org_id": "22222222-2222-2222-2222-222222222222"}


def _call(**over):
    kw = dict(
        message="buatkan gambar kucing", bot=_BOT, bot_id="bot-1", conv_id="conv-1",
        user_meta={}, effective_lang="id", system="SYS", pool=object(),
    )
    kw.update(over)
    return asyncio.run(main._maybe_generate_chat_image(**kw))


def test_noop_for_non_image_request(monkeypatch):
    monkeypatch.setattr(main.image_providers, "looks_like_image_request", lambda m: False)
    system, url, provider = _call()
    assert system == "SYS" and url is None and provider is None


def test_cooldown_skips(monkeypatch):
    monkeypatch.setattr(main.image_providers, "looks_like_image_request", lambda m: True)
    monkeypatch.setattr(main, "_check_media_cooldown", lambda *a: 20)
    system, url, provider = _call()
    assert system == "SYS" and url is None and provider is None


def test_success_augments_system_and_returns_url(monkeypatch):
    monkeypatch.setattr(main.image_providers, "looks_like_image_request", lambda m: True)
    monkeypatch.setattr(main, "_check_media_cooldown", lambda *a: 0)

    async def _gen(**k):
        return {"image_url": "/media/cat.png", "provider": "replicate"}

    monkeypatch.setattr(main, "_run_image_generation", _gen)
    system, url, provider = _call()
    assert url == "/media/cat.png"
    assert provider == "replicate"
    assert "Gambar berhasil dibuat" in system


def test_generation_failure_notes_error_without_crashing(monkeypatch):
    monkeypatch.setattr(main.image_providers, "looks_like_image_request", lambda m: True)
    monkeypatch.setattr(main, "_check_media_cooldown", lambda *a: 0)

    async def _gen(**k):
        raise HTTPException(429, "cooling")

    monkeypatch.setattr(main, "_run_image_generation", _gen)
    system, url, provider = _call()
    assert url is None
    assert "Gambar gagal dibuat" in system
