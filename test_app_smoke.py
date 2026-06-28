from fastapi.testclient import TestClient

import main


def test_health_reports_configured_ai():
    with TestClient(main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ai"]["configured"] is True
    # providers dict lists all three provider slots
    providers = payload["ai"]["providers"]
    assert "gemini" in providers
    assert "openrouter" in providers
    assert "groq" in providers
    # at least one must be active
    assert any(p["active"] for p in providers.values())


def test_dashboard_and_frontend_assets_are_served():
    with TestClient(main.app) as client:
        dashboard = client.get("/dashboard")
        app_js = client.get("/ui/app.js")
        api_client = client.get("/ui/api-client.js")

    assert dashboard.status_code == 200
    assert "text/html" in dashboard.headers["content-type"]
    assert app_js.status_code == 200
    assert "javascript" in app_js.headers["content-type"]
    assert api_client.status_code == 200


def test_root_serves_public_landing_page_not_login_redirect():
    with TestClient(main.app) as client:
        response = client.get("/", follow_redirects=False)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "BotNesia" in response.text
    assert "Mulai Gratis" in response.text


def test_dashboard_login_still_works_after_landing_page_added():
    with TestClient(main.app) as client:
        response = client.get("/dashboard")

    assert response.status_code == 200
    assert "auth-view" in response.text or "login-form" in response.text


def test_frontend_asset_path_traversal_is_blocked():
    with TestClient(main.app) as client:
        response = client.get("/ui/%2e%2e/main.py")

    assert response.status_code == 404


def test_cs_agent_does_not_discard_actionable_answer_with_apology():
    from cs_agent import CSAgent

    agent = CSAgent()
    answer = (
        "Maaf login Anda belum berhasil. Coba reset sandi, hapus cache browser, "
        "lalu pastikan email yang dipakai sama dengan akun terdaftar."
    )

    assert agent._is_refusal(answer) is False
    assert agent._is_refusal("Saya tidak bisa membantu.") is True


def test_news_context_contains_publisher_and_source_url(monkeypatch):
    import asyncio
    import news_fetcher

    item = news_fetcher.NewsItem(
        title="AI membantu usaha kecil",
        link="https://example.com/ai-usaha-kecil",
        source="Media Contoh",
        published="Fri, 12 Jun 2026 08:00:00 GMT",
        summary="Ringkasan berita untuk pengujian.",
    )

    async def fake_search_news(query, limit=6, rss_urls=None):
        return [item]

    monkeypatch.setattr(news_fetcher, "search_news", fake_search_news)
    context = asyncio.run(news_fetcher.build_news_context("berita AI", include_bodies=False))

    assert "Media Contoh" in context
    assert "Fri, 12 Jun 2026 08:00:00 GMT" in context
    assert "https://example.com/ai-usaha-kecil" in context


def test_intelligence_routes_are_mounted_on_main_app():
    paths = {getattr(route, "path", "") for route in main.app.routes}

    assert "/intel/dashboard/{bot_id}" in paths
    assert "/intel/faq/{bot_id}" in paths
    assert "/intel/learning/run" in paths


def test_local_nightly_schedule_always_targets_next_24_hours():
    from datetime import datetime, timezone
    from intelligence.pipeline import seconds_until_next_run

    delay = seconds_until_next_run(datetime(2026, 6, 12, 23, 30, tzinfo=timezone.utc))

    assert 0 < delay <= 24 * 60 * 60


def test_cs_prompt_forbids_unsourced_price_placeholders():
    from cs_agent import CSAgent

    # Prompt must forbid fabricated price placeholders
    assert "Rp X" in CSAgent.system_prompt
    # Prompt must forbid hallucinated facts / unsourced information
    assert any(
        phrase in CSAgent.system_prompt
        for phrase in ("tidak tersedia di konteks", "JANGAN mengarang", "jangan mengarang")
    )
