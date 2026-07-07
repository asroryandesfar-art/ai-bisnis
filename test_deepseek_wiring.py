"""Wiring DeepSeek 3-otak ke main: harus OPT-IN (default OFF) & factory sehat."""
import main


def test_brain_off_by_default_in_code():
    # CODE default is OFF (env-independent). A deployment MAY enable it by
    # setting DEEPSEEK_BRAIN_ENABLED=1 in its own .env — that is expected and
    # does not change the shipped default.
    assert main.Settings.model_fields["deepseek_brain_enabled"].default is False


def test_models_factory_env_driven_and_r1_preserved():
    m = main.deepseek_models()
    assert m.thinking == "deepseek-reasoner"      # R1 dipertahankan
    assert m.fast and m.pro                        # selalu terisi (pro fallback ke thinking)


def test_brain_singleton_builds():
    b = main.get_deepseek_brain()
    assert type(b).__name__ == "DeepSeekBrain"
    assert b is main.get_deepseek_brain()          # singleton


def test_chat_brain_branch_requires_flag_and_key():
    # Code contract: the /chat brain branch runs only when the flag is ON *and*
    # an API key is present (so enabling the flag without a key can't break chat).
    import inspect
    src = inspect.getsource(main.chat)
    assert "cfg.deepseek_brain_enabled and cfg.deepseek_api_key" in src
