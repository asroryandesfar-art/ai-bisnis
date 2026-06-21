"""test_public_demo.py — Phase Next 16 (Public Demo Experience).

POST /api/public/investor-demo selalu memanggil exec_agent_module.run_investor_demo()
dengan agent NYATA (kredensial Groq dari env) -- konsisten dengan pola /chat/{bot_id}
yang juga tidak ditest lewat TestClient (lihat catatan di README/memory: rute publik
yang memanggil LLM nyata diverifikasi via live smoke test, bukan unit test, untuk
menghindari panggilan jaringan nyata di unit test). Modul run_investor_demo() sendiri
sudah ditest menyeluruh di test_executive_agent.py (Phase Next 15) dengan agent=None.
File ini hanya menguji bagian yang murni/tanpa-LLM: _real_client_ip() dan GET /demo.
"""
from types import SimpleNamespace

from fastapi.testclient import TestClient

import main


def _fake_request(headers: dict, client_host: str | None = "203.0.113.9"):
    return SimpleNamespace(
        headers=headers,
        client=SimpleNamespace(host=client_host) if client_host else None,
    )


def test_real_client_ip_prefers_x_forwarded_for():
    request = _fake_request({"X-Forwarded-For": "198.51.100.4, 10.0.0.1"})
    assert main._real_client_ip(request) == "198.51.100.4"


def test_real_client_ip_falls_back_to_cf_connecting_ip():
    request = _fake_request({"CF-Connecting-IP": "198.51.100.7"})
    assert main._real_client_ip(request) == "198.51.100.7"


def test_real_client_ip_falls_back_to_request_client_host():
    request = _fake_request({})
    assert main._real_client_ip(request) == "203.0.113.9"


def test_real_client_ip_returns_unknown_when_nothing_available():
    request = _fake_request({}, client_host=None)
    assert main._real_client_ip(request) == "unknown"


def test_public_demo_page_is_served_without_auth():
    with TestClient(main.app) as client:
        response = client.get("/demo")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Investor Demo" in response.text
