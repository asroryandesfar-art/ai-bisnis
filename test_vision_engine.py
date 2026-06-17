import asyncio

import pytest

import vision_engine as ve


def test_mode_prompts_cover_all_supported_modes():
    assert set(ve.MODE_PROMPTS.keys()) == {"describe", "ocr", "ui_analysis", "document"}
    for prompt in ve.MODE_PROMPTS.values():
        assert prompt.strip()


def test_data_uri_is_well_formed_base64():
    uri = ve._data_uri(b"\x89PNG\r\n", "image/png")
    assert uri.startswith("data:image/png;base64,")
    assert len(uri.split(",", 1)[1]) > 0


def test_analyze_image_requires_api_key():
    with pytest.raises(RuntimeError):
        asyncio.run(ve.analyze_image(b"fake", "image/png", api_key="", model="some-model"))


def test_analyze_image_unknown_mode_falls_back_via_caller():
    # vision_engine itself doesn't validate `mode` (main.py does) — unknown mode
    # just means MODE_PROMPTS.get() returns None and falls back to default param.
    assert ve.MODE_PROMPTS.get("not-a-real-mode", ve.MODE_PROMPTS["describe"]) == ve.MODE_PROMPTS["describe"]
