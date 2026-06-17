"""
POST /webhooks/meta only verified X-Hub-Signature-256 when META_APP_SECRET
was set -- `if (cfg.meta_app_secret or "").strip(): ...`. If the operator
hadn't configured it (or unset it), the check was skipped entirely and any
unauthenticated POST was processed, able to trigger auto-replies on behalf
of whichever tenant the payload resolves to.

Fixed to fail closed: with no secret configured, every POST is rejected
(503) instead of silently accepted. With a secret configured, signature
verification works exactly as before (hmac.compare_digest, unchanged).
"""
from fastapi.testclient import TestClient

import main


def test_webhook_rejects_everything_when_secret_not_configured(monkeypatch):
    monkeypatch.setattr(main.cfg, "meta_app_secret", "")
    with TestClient(main.app) as client:
        response = client.post("/webhooks/meta", json={"entry": []})
    assert response.status_code == 503


def test_webhook_rejects_request_with_wrong_signature(monkeypatch):
    monkeypatch.setattr(main.cfg, "meta_app_secret", "test-secret")
    with TestClient(main.app) as client:
        response = client.post(
            "/webhooks/meta", json={"entry": []},
            headers={"X-Hub-Signature-256": "sha256=not-the-real-signature"},
        )
    assert response.status_code == 403


def test_webhook_rejects_request_with_no_signature_header(monkeypatch):
    monkeypatch.setattr(main.cfg, "meta_app_secret", "test-secret")
    with TestClient(main.app) as client:
        response = client.post("/webhooks/meta", json={"entry": []})
    assert response.status_code == 403


def test_webhook_accepts_request_with_correct_signature(monkeypatch):
    import hashlib
    import hmac
    import json as json_module

    monkeypatch.setattr(main.cfg, "meta_app_secret", "test-secret")
    body = json_module.dumps({"entry": []}).encode("utf-8")
    signature = "sha256=" + hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()

    with TestClient(main.app) as client:
        response = client.post(
            "/webhooks/meta", content=body,
            headers={"X-Hub-Signature-256": signature, "Content-Type": "application/json"},
        )
    assert response.status_code == 200
