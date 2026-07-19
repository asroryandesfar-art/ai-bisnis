"""Discovery + capability ranking DeepSeek — pilih model paling cerdas dinamis."""
import asyncio

import deepseek_discovery as dd


def test_capability_score_prefers_higher_version_and_tier():
    assert dd.capability_score("deepseek-v5-pro") > dd.capability_score("deepseek-v4-pro")
    assert dd.capability_score("deepseek-v4-pro") > dd.capability_score("deepseek-v4-flash")


def test_rank_and_tiers_for_current_lineup():
    m = ["deepseek-v4-flash", "deepseek-v4-pro"]
    assert dd.rank_models(m) == ["deepseek-v4-pro", "deepseek-v4-flash"]
    t = dd.select_tiers(m)
    assert t["complex"] == "deepseek-v4-pro"
    assert t["simple"] == "deepseek-v4-flash"


def test_new_flagship_auto_preferred_without_code_change():
    m = ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-v5-pro"]
    assert dd.select_tiers(m)["complex"] == "deepseek-v5-pro"   # auto-update


def test_is_fast_model():
    assert dd.is_fast_model("deepseek-v4-flash")
    assert not dd.is_fast_model("deepseek-v4-pro")


def test_select_tiers_empty():
    assert dd.select_tiers([]) == {}


def test_discover_uses_injected_fetch_and_caches():
    dd.reset_cache()
    try:
        async def fake_fetch(_key):
            return ["deepseek-v4-flash", "deepseek-v4-pro"]
        got = asyncio.run(dd.discover_models("k", fetch=fake_fetch))
        assert got == ["deepseek-v4-flash", "deepseek-v4-pro"]
        assert dd.cached_models() == got
    finally:
        dd.reset_cache()


def test_discover_failure_is_safe():
    dd.reset_cache()
    try:
        async def boom(_key):
            raise RuntimeError("network down")
        assert asyncio.run(dd.discover_models("k", fetch=boom)) == []   # fallback aman
    finally:
        dd.reset_cache()


def test_deepseek_models_uses_discovery(monkeypatch):
    import main
    monkeypatch.setattr(main.cfg, "deepseek_model_fast", "")
    monkeypatch.setattr(main.cfg, "deepseek_model_thinking", "")
    monkeypatch.setattr(main.cfg, "deepseek_model_pro", "")
    dd.reset_cache()
    dd._cache["models"] = ["deepseek-v4-flash", "deepseek-v4-pro"]
    dd._cache["ts"] = 9e18
    try:
        m = main.deepseek_models()
        assert m.fast == "deepseek-v4-flash"      # tier cepat
        assert m.thinking == "deepseek-v4-pro"    # tier cerdas
        assert m.pro == "deepseek-v4-pro"
    finally:
        dd.reset_cache()


def test_env_override_beats_discovery(monkeypatch):
    import main
    monkeypatch.setattr(main.cfg, "deepseek_model_fast", "locked-fast")
    monkeypatch.setattr(main.cfg, "deepseek_model_thinking", "")
    monkeypatch.setattr(main.cfg, "deepseek_model_pro", "")
    dd.reset_cache()
    dd._cache["models"] = ["deepseek-v4-flash", "deepseek-v4-pro"]
    dd._cache["ts"] = 9e18
    try:
        assert main.deepseek_models().fast == "locked-fast"    # override menang
    finally:
        dd.reset_cache()
