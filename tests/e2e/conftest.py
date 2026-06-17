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
