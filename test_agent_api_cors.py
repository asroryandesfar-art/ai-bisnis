"""Unit test untuk kebijakan CORS agent_api (Phase 1: security hardening).

agent_api adalah service server-to-server (auth header x-agent-secret). CORS
wildcard tak perlu; diganti allowlist konfigurable dengan default aman.
"""
import agent_api


def _settings(**over):
    # cors_allowed_origins default dikosongkan agar tes deterministik: Settings()
    # membaca .env asli yang mungkin sudah menyetel allowlist produksi.
    s = agent_api.Settings()
    s.cors_allowed_origins = over.pop("cors_allowed_origins", "")
    for k, v in over.items():
        setattr(s, k, v)
    return s


def test_default_is_not_wildcard():
    origins = agent_api.resolve_cors_origins(_settings())
    assert "*" not in origins
    assert origins, "default allowlist tidak boleh kosong"


def test_default_includes_app_url_and_localhost():
    s = _settings(app_url="https://botnesia.id")
    origins = agent_api.resolve_cors_origins(s)
    assert "https://botnesia.id" in origins
    assert "http://localhost:8000" in origins


def test_env_configured_allowlist_is_respected():
    # Nilai nyata dari .env (bila ada) harus dipakai apa adanya, tanpa wildcard.
    origins = agent_api.resolve_cors_origins(agent_api.Settings())
    assert "*" not in origins


def test_explicit_wildcard_escape_hatch():
    origins = agent_api.resolve_cors_origins(_settings(cors_allowed_origins="*"))
    assert origins == ["*"]


def test_custom_origins_are_parsed_and_trimmed():
    s = _settings(cors_allowed_origins="https://a.com, https://b.com ,")
    origins = agent_api.resolve_cors_origins(s)
    assert origins == ["https://a.com", "https://b.com"]
