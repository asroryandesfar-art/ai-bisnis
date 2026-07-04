"""C-01 — guard kekuatan SECRET_KEY produksi.

Menguji pure function `audit_secret_key` dan `validate_startup_secrets`
(warn-only vs fail-closed via strict_secrets) tanpa harus boot server penuh.
"""
import logging

import pytest

import main


# ── audit_secret_key: deteksi secret lemah ──────────────────────────────
@pytest.mark.parametrize("weak", [
    "",
    "change-me-in-production",
    "changeme",
    "secret",
    "password",
    "default",
    "development-secret",
    "test-secret",
    "botnesia",
    "short8ch",          # < 32 char
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",  # panjang tapi entropi rendah
])
def test_audit_flags_weak_secret(weak):
    assert main.audit_secret_key(weak), f"harus terdeteksi lemah: {weak!r}"


def test_audit_accepts_strong_secret():
    strong = "kP3n_9xQz7Vw2mRt6Ub4Yc8Ld0Se1Fg5Hj-AaBbCc"  # >=32, entropi cukup
    assert main.audit_secret_key(strong) == []


# ── validate_startup_secrets: warn-only vs fail-closed ──────────────────
def _settings(secret: str, strict: bool):
    s = main.Settings()
    s.secret_key = secret
    s.strict_secrets = strict
    return s


def test_strict_mode_rejects_default_secret():
    s = _settings("change-me-in-production", strict=True)
    with pytest.raises(RuntimeError):
        main.validate_startup_secrets(s)


def test_strict_mode_rejects_empty_secret():
    s = _settings("", strict=True)
    with pytest.raises(RuntimeError):
        main.validate_startup_secrets(s)


def test_strict_mode_allows_strong_secret():
    s = _settings("kP3n_9xQz7Vw2mRt6Ub4Yc8Ld0Se1Fg5Hj-AaBbCc", strict=True)
    assert main.validate_startup_secrets(s) == []


def test_warn_mode_does_not_raise_but_reports(caplog):
    """Default (warn-only): server tetap boot, tapi log error keras."""
    s = _settings("change-me-in-production", strict=False)
    with caplog.at_level(logging.ERROR):
        issues = main.validate_startup_secrets(s)
    assert issues  # ada issue dilaporkan
    assert any("SECRET_KEY" in r.message for r in caplog.records)


# ── C-01: enkripsi integrasi memakai key terpisah (backward-compat) ─────
def test_encryption_key_falls_back_to_secret_key():
    s = main.Settings()
    s.secret_key = "primary-secret-value-abc"
    s.integration_encryption_key = ""
    assert s.effective_encryption_key == "primary-secret-value-abc"


def test_encryption_key_can_be_separated_for_rotation():
    s = main.Settings()
    s.secret_key = "new-rotated-jwt-secret"
    s.integration_encryption_key = "old-secret-for-legacy-integrations"
    # Integrasi lama tetap terbaca dengan key lama walau JWT secret sudah dirotasi.
    assert s.effective_encryption_key == "old-secret-for-legacy-integrations"
