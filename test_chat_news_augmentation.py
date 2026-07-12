"""Unit test for _build_news_augmentation (chat handler decomposition step 2)."""
import asyncio

import main


def test_noop_when_news_disabled(monkeypatch):
    monkeypatch.setattr(main.cfg, "news_enabled", False)
    monkeypatch.setattr(main, "_looks_like_news_query", lambda t: True)
    out = asyncio.run(main._build_news_augmentation("berita hari ini", "SYS", "id"))
    assert out == "SYS"


def test_noop_for_non_news_query(monkeypatch):
    monkeypatch.setattr(main.cfg, "news_enabled", True)
    monkeypatch.setattr(main, "_looks_like_news_query", lambda t: False)
    out = asyncio.run(main._build_news_augmentation("apa kabar", "SYS", "id"))
    assert out == "SYS"


def test_augments_system_with_news_context(monkeypatch):
    monkeypatch.setattr(main.cfg, "news_enabled", True)
    monkeypatch.setattr(main, "_looks_like_news_query", lambda t: True)
    monkeypatch.setattr(main, "_news_needs_full_bodies", lambda t: False)

    async def _ctx(*a, **k):
        return "NEWS_CONTEXT_BODY"

    monkeypatch.setattr(main, "build_news_context", _ctx)
    out = asyncio.run(main._build_news_augmentation("berita ekonomi", "SYS", "id"))
    assert "NEWS_CONTEXT_BODY" in out
    assert "Berita terkini" in out  # Indonesian title


def test_english_title(monkeypatch):
    monkeypatch.setattr(main.cfg, "news_enabled", True)
    monkeypatch.setattr(main, "_looks_like_news_query", lambda t: True)
    monkeypatch.setattr(main, "_news_needs_full_bodies", lambda t: False)

    async def _ctx(*a, **k):
        return "BODY"

    monkeypatch.setattr(main, "build_news_context", _ctx)
    out = asyncio.run(main._build_news_augmentation("today's news", "SYS", "en"))
    assert "Latest news" in out


def test_degrades_gracefully_on_failure(monkeypatch):
    monkeypatch.setattr(main.cfg, "news_enabled", True)
    monkeypatch.setattr(main, "_looks_like_news_query", lambda t: True)
    monkeypatch.setattr(main, "_news_needs_full_bodies", lambda t: False)

    async def _boom(*a, **k):
        raise RuntimeError("feed down")

    monkeypatch.setattr(main, "build_news_context", _boom)
    out = asyncio.run(main._build_news_augmentation("berita", "SYS", "id"))
    assert out == "SYS"
