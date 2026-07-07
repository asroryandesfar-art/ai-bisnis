"""Product-readiness guard: the SHIPPED code defaults must be safe, regardless
of any local .env. Tests read the pydantic field defaults, not the loaded env.
"""
import main
from bn_platform.config import PlatformSettings


def _default(model, field):
    return model.model_fields[field].default


def test_api_docs_off_by_default():
    # Swagger/OpenAPI must not be exposed unless a deployment opts in.
    assert _default(main.Settings, "enable_api_docs") is False


def test_deepseek_brain_off_by_default():
    assert _default(main.Settings, "deepseek_brain_enabled") is False


def test_strict_secrets_flag_exists_and_defaults_false():
    # Fail-open by default so a live server never dies on deploy; operators
    # enable fail-closed explicitly (documented).
    assert _default(main.Settings, "strict_secrets") is False


def test_payments_default_to_sandbox():
    # Never default to real-money processing.
    assert _default(PlatformSettings, "midtrans_is_production") is False
    assert _default(PlatformSettings, "local_billing_enabled") is False


def test_secret_key_guard_present():
    # The C-01 secret-strength guard must exist and flag weak values.
    assert main.audit_secret_key("change-me-in-production")
    assert main.audit_secret_key("")
    assert main.audit_secret_key("kP3n_9xQz7Vw2mRt6Ub4Yc8Ld0Se1Fg5Hj-AaBbCc") == []
