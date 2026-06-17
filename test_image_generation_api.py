import asyncio

import pytest
from fastapi import HTTPException

import main


def test_video_endpoint_is_fully_removed():
    paths = {getattr(route, "path", "") for route in main.app.routes}
    assert "/media/video" not in paths
    assert not hasattr(main, "MediaVideoReq")
    assert not hasattr(main, "_replicate_video_queue")
    assert not hasattr(main, "_replicate_video_overrides_for_model")


def test_new_multimodal_routes_are_registered():
    routes_by_path = {}
    for route in main.app.routes:
        path = getattr(route, "path", "")
        if path:
            routes_by_path.setdefault(path, set()).update(getattr(route, "methods", set()) or set())

    assert "POST" in routes_by_path.get("/api/images/generate", set())
    assert "POST" in routes_by_path.get("/api/images/analyze", set())
    assert "GET" in routes_by_path.get("/api/images/history", set())
    assert "POST" in routes_by_path.get("/api/documents/generate", set())
    assert "POST" in routes_by_path.get("/media/image", set())


def test_run_image_generation_rejects_unconfigured_provider(monkeypatch):
    # Skip quota check (would otherwise hit the DB pool) and moderation (would hit Groq).
    monkeypatch.setattr(main, "_platform_check_limit", None)
    monkeypatch.setattr(main.cfg, "image_moderation_enabled", False)
    monkeypatch.setattr(main.cfg, "openai_api_key", "")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(main._run_image_generation(
            org_id="org-1", pool=None, prompt="buat logo restoran modern", provider_name="openai",
        ))
    assert exc_info.value.status_code == 400


def test_run_image_generation_rejects_unsafe_prompt(monkeypatch):
    monkeypatch.setattr(main, "_platform_check_limit", None)
    monkeypatch.setattr(main.cfg, "image_moderation_enabled", True)

    async def fake_unsafe(_text):
        return False

    monkeypatch.setattr(main, "_moderate_prompt", fake_unsafe)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(main._run_image_generation(
            org_id="org-1", pool=None, prompt="something flagged", provider_name="replicate",
        ))
    assert exc_info.value.status_code == 422


def test_image_provider_kwargs_reads_from_settings(monkeypatch):
    monkeypatch.setattr(main.cfg, "openai_api_key", "test-key")
    kwargs = main._image_provider_kwargs()
    assert kwargs["openai_api_key"] == "test-key"
    assert "replicate_tokens" in kwargs
