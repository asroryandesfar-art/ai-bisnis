"""Wiring DeepSeek 3-otak ke main: harus OPT-IN (default OFF) & factory sehat."""
import main


def test_brain_disabled_by_default():
    # Produksi tidak berubah kecuali operator set DEEPSEEK_BRAIN_ENABLED=1.
    assert main.cfg.deepseek_brain_enabled is False


def test_models_factory_env_driven_and_r1_preserved():
    m = main.deepseek_models()
    assert m.thinking == "deepseek-reasoner"      # R1 dipertahankan
    assert m.fast and m.pro                        # selalu terisi (pro fallback ke thinking)


def test_brain_singleton_builds():
    b = main.get_deepseek_brain()
    assert type(b).__name__ == "DeepSeekBrain"
    assert b is main.get_deepseek_brain()          # singleton


def test_chat_wiring_guard_expr():
    # Branch hanya jalan bila flag ON *dan* ada api key (aman bila salah satu kosong).
    assert (main.cfg.deepseek_brain_enabled and bool(main.cfg.deepseek_api_key)) is False
