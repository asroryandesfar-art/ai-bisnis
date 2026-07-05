"""M-03 — CORS: batasi origin app, buka endpoint publik widget."""
from fastapi.testclient import TestClient

import main

EVIL = "https://evil.example"
APP = (main.cfg.app_url or "https://botnesia.uk").rstrip("/")


# ── pure policy ─────────────────────────────────────────────────────────
def test_public_paths_open_to_any_origin():
    assert main._cors_allow_origin_for("/health", EVIL) == EVIL
    assert main._cors_allow_origin_for("/chat/abc", EVIL) == EVIL
    assert main._cors_allow_origin_for("/bots/xyz/config", EVIL) == EVIL


def test_app_paths_reject_unknown_origin():
    assert main._cors_allow_origin_for("/org", EVIL) is None
    assert main._cors_allow_origin_for("/dashboard", EVIL) is None


def test_app_paths_allow_configured_origin():
    assert main._cors_allow_origin_for("/org", APP) == APP


# ── integration via TestClient ──────────────────────────────────────────
def test_widget_endpoint_cors_header_echoed():
    with TestClient(main.app) as client:
        r = client.get("/health", headers={"Origin": EVIL})
    assert r.headers.get("Access-Control-Allow-Origin") == EVIL


def test_app_endpoint_no_cors_for_evil_origin():
    with TestClient(main.app) as client:
        r = client.get("/dashboard", headers={"Origin": EVIL})
    assert r.headers.get("Access-Control-Allow-Origin") in (None, "")


def test_preflight_on_chat_allowed():
    with TestClient(main.app) as client:
        r = client.options("/chat/some-bot", headers={
            "Origin": EVIL,
            "Access-Control-Request-Method": "POST",
        })
    assert r.status_code == 200
    assert r.headers.get("Access-Control-Allow-Origin") == EVIL
