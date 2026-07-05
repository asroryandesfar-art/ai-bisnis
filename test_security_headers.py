"""M-04 — security headers hadir di response."""
from fastapi.testclient import TestClient

import main


def test_security_headers_present_on_dashboard():
    with TestClient(main.app) as client:
        r = client.get("/dashboard")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert "strict-origin" in (r.headers.get("Referrer-Policy") or "")
    assert "max-age" in (r.headers.get("Strict-Transport-Security") or "")


def test_security_headers_present_on_api():
    with TestClient(main.app) as client:
        r = client.get("/health")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"


def test_widget_js_still_served():
    # widget tetap bisa diambil (script inline di situs pelanggan, bukan iframe)
    with TestClient(main.app) as client:
        r = client.get("/botnesia-widget.js")
    assert r.status_code == 200
