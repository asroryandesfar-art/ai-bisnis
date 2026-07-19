import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

# tests/e2e/conftest.py -> project root is two levels up.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import main  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """H-02: /chat rate-limit sekarang di-key pada IP klien (server-derived,
    anti-spoof) — bukan lagi user_meta.userId. Di bawah TestClient session-scoped
    semua request berbagi satu IP sintetis, jadi bucket bersama akan menumpuk
    lintas-test dan akhirnya memblok. Reset state in-memory limiter sebelum tiap
    e2e test untuk memulihkan isolasi per-test (produksi memakai IP nyata yang
    berbeda-beda). Tidak melemahkan enforcement produksi."""
    rl = getattr(main, "_rate_limiter", None)
    if rl is not None:
        for attr in ("_windows", "_blocked", "_timestamps", "_buckets", "_audit", "_log"):
            obj = getattr(rl, attr, None)
            if hasattr(obj, "clear"):
                obj.clear()
    yield


@pytest.fixture(autouse=True)
def _force_multi_agent_chat():
    """E2E di direktori ini sengaja menguji rantai Supervisor -> Agent -> Knowledge
    (lihat docstring `client`). Fast-path brain single-model (DEEPSEEK_BRAIN_ENABLED)
    memintas rantai itu untuk pesan simpel -> asersi routing/intent/handoff jadi
    non-deterministik tergantung nilai .env lokal. Paksa brain OFF selama e2e agar
    tes selalu menjalankan pipeline multi-agent. Tidak mengubah perilaku produksi."""
    prev = main.cfg.deepseek_brain_enabled
    main.cfg.deepseek_brain_enabled = False
    try:
        yield
    finally:
        main.cfg.deepseek_brain_enabled = prev


@pytest.fixture(scope="session")
def client():
    """Real FastAPI app + real DB (same TestClient(main.app) pattern as
    test_app_smoke.py) — drives the actual API -> Supervisor -> Agent ->
    Knowledge -> DB -> Response chain, no mocks. Session-scoped because
    app lifespan startup (ensure_schema migrations, etc.) is expensive and
    idempotent — re-running it per test makes the suite intractably slow."""
    with TestClient(main.app) as c:
        yield c


@pytest.fixture()
def registered_org(client):
    """Register a fresh org+owner user via the real /auth/register endpoint
    and return {token, org_id, headers} for use by other e2e tests."""
    unique = uuid.uuid4().hex[:10]
    resp = client.post("/auth/register", json={
        "org_name": f"E2E Test Org {unique}",
        "email": f"e2e-{unique}@example.test",
        "password": "TestPassword123!",
        "full_name": "E2E Tester",
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {
        "token": data["token"],
        "org_id": data["org_id"],
        "headers": {"Authorization": f"Bearer {data['token']}"},
    }


@pytest.fixture()
def bot(client, registered_org):
    """Create a plain bot for the registered org and return its id."""
    resp = client.post(
        "/bots",
        json={"name": "E2E Test Bot", "greeting": "Halo dari E2E test"},
        headers=registered_org["headers"],
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["bot_id"]


@pytest.fixture()
def chat_user_meta():
    """/chat/{bot_id} is public and defaults to a shared 'anonymous' rate-limit
    bucket (rate_limiter.py Layer 2: per-user) when no userId is given. With a
    session-scoped client, every e2e test calling /chat without this would
    collide on the same bucket and eventually get blocked — give each test
    its own synthetic end-user, like a real distinct chat session would have."""
    return {"userId": f"e2e-user-{uuid.uuid4()}"}
