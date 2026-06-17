"""
Section 11 (Image Generation Validation): main._run_image_generation() now
auto-fails-over across cfg.image_provider_fallback_order ("google_imagen,
replicate" by default) when the caller does NOT request a specific provider
-- mirrors the chat auto-image path and the default /api/images/generate
call (provider="" means "use default"). When a caller DOES request a
specific provider explicitly, behavior is unchanged: only that provider is
tried, no silent override.

GOOGLE_API_KEY isn't configured in this environment (cfg.google_api_key is
empty), so these tests fake the provider objects via monkeypatching
image_providers.get_provider rather than hitting the real Imagen/Replicate
APIs -- this validates the failover *logic*, not the providers themselves
(those are exercised for real wherever cfg.google_api_key is actually set).
"""
import asyncio
import uuid

import asyncpg
import pytest
from fastapi import HTTPException

import image_providers
import main


def _run(coro_fn):
    async def _wrapped():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await coro_fn(pool)
        finally:
            await pool.close()
    asyncio.run(_wrapped())


async def _setup_org(pool) -> str:
    org_id = str(uuid.uuid4())
    slug = f"e2e-image-fallback-{uuid.uuid4().hex[:8]}"
    await pool.execute(
        """INSERT INTO organizations (id, name, slug, plan, billing_status)
           VALUES ($1,$2,$3,'starter','trialing')""",
        org_id, "Image Fallback Test Org", slug,
    )
    return org_id


class _FakeProvider:
    def __init__(self, name: str, *, available: bool, raises: Exception | None = None):
        self.name = name
        self._available = available
        self._raises = raises

    @property
    def available(self) -> bool:
        return self._available

    async def generate(self, prompt, *, size="1024x1024", style="", quality="medium"):
        if self._raises:
            raise self._raises
        return image_providers.ImageResult(
            data=b"fake-bytes", content_type="image/png", provider=self.name, model="fake-model",
        )


@pytest.fixture(autouse=True)
def _no_real_moderation_or_queue(monkeypatch):
    # Moderation would otherwise hit Groq for real; the Replicate job queue's
    # worker tasks are only started by the app's startup event (never run
    # here), so submit() would hang forever waiting on a future nothing
    # services -- bypass the queue and call the provider directly instead,
    # since these tests exercise the fallback logic, not the queue itself.
    monkeypatch.setattr(main, "_moderate_prompt", lambda text: _true())
    monkeypatch.setattr(main._replicate_image_queue, "submit", lambda coro_factory: coro_factory())


async def _true():
    return True


def test_falls_back_to_replicate_when_imagen_unavailable(monkeypatch):
    async def body(pool):
        org_id = await _setup_org(pool)

        def fake_get_provider(name, **kwargs):
            if name == "google_imagen":
                return _FakeProvider("google_imagen", available=False)
            if name == "replicate":
                return _FakeProvider("replicate", available=True)
            raise AssertionError(f"unexpected provider requested: {name}")

        monkeypatch.setattr(image_providers, "get_provider", fake_get_provider)

        result = await main._run_image_generation(
            org_id=org_id, pool=pool, prompt="logo kedai kopi minimalis",
        )
        assert result["provider"] == "replicate"

    _run(body)


def test_falls_back_to_replicate_when_imagen_raises(monkeypatch):
    async def body(pool):
        org_id = await _setup_org(pool)

        def fake_get_provider(name, **kwargs):
            if name == "google_imagen":
                return _FakeProvider("google_imagen", available=True,
                                      raises=image_providers.ImageProviderError("Imagen quota exceeded"))
            if name == "replicate":
                return _FakeProvider("replicate", available=True)
            raise AssertionError(f"unexpected provider requested: {name}")

        monkeypatch.setattr(image_providers, "get_provider", fake_get_provider)

        result = await main._run_image_generation(
            org_id=org_id, pool=pool, prompt="poster promo diskon akhir tahun",
        )
        assert result["provider"] == "replicate"

    _run(body)


def test_uses_imagen_when_available_and_no_explicit_provider(monkeypatch):
    async def body(pool):
        org_id = await _setup_org(pool)
        calls: list[str] = []

        def fake_get_provider(name, **kwargs):
            calls.append(name)
            if name == "google_imagen":
                return _FakeProvider("google_imagen", available=True)
            raise AssertionError(f"unexpected provider requested: {name}")

        monkeypatch.setattr(image_providers, "get_provider", fake_get_provider)

        result = await main._run_image_generation(
            org_id=org_id, pool=pool, prompt="dashboard concept untuk admin panel",
        )
        assert result["provider"] == "google_imagen"
        assert calls == ["google_imagen"]

    _run(body)


def test_raises_clear_error_when_all_providers_fail(monkeypatch):
    async def body(pool):
        org_id = await _setup_org(pool)

        def fake_get_provider(name, **kwargs):
            return _FakeProvider(name, available=False)

        monkeypatch.setattr(image_providers, "get_provider", fake_get_provider)

        with pytest.raises(HTTPException) as exc_info:
            await main._run_image_generation(org_id=org_id, pool=pool, prompt="apapun")
        assert exc_info.value.status_code == 502

    _run(body)


def test_explicit_provider_request_is_not_silently_overridden(monkeypatch):
    """Caller explicitly asks for 'replicate' even though Imagen would be
    tried first under the default fallback order -- explicit choice must be
    respected exactly like before this change, no auto-failover applied."""
    async def body(pool):
        org_id = await _setup_org(pool)
        calls: list[str] = []

        def fake_get_provider(name, **kwargs):
            calls.append(name)
            return _FakeProvider(name, available=True)

        monkeypatch.setattr(image_providers, "get_provider", fake_get_provider)

        result = await main._run_image_generation(
            org_id=org_id, pool=pool, prompt="logo eksplisit replicate", provider_name="replicate",
        )
        assert result["provider"] == "replicate"
        assert calls == ["replicate"]

    _run(body)


def test_explicit_unavailable_provider_raises_400_not_silently_falls_back(monkeypatch):
    async def body(pool):
        org_id = await _setup_org(pool)

        def fake_get_provider(name, **kwargs):
            return _FakeProvider(name, available=False)

        monkeypatch.setattr(image_providers, "get_provider", fake_get_provider)

        with pytest.raises(HTTPException) as exc_info:
            await main._run_image_generation(
                org_id=org_id, pool=pool, prompt="logo", provider_name="google_imagen",
            )
        assert exc_info.value.status_code == 400

    _run(body)
