import asyncio

import pytest

import image_providers as ip


@pytest.mark.parametrize(
    "text",
    [
        "Buat logo restoran modern",
        "Buat ilustrasi cyberpunk",
        "Buat poster promo",
        "Buat desain dashboard SaaS",
        "Buat mascot perusahaan",
        "bikin banner promo lebaran",
        "tolong gambarkan ikon untuk aplikasi kasir",
    ],
)
def test_looks_like_image_request_matches_spec_examples(text):
    assert ip.looks_like_image_request(text)


@pytest.mark.parametrize(
    "text",
    [
        "Berapa harga paket Pro?",
        "Bagaimana cara menghubungkan WhatsApp?",
        "",
        "   ",
        "Buat laporan penjualan bulan ini",
    ],
)
def test_looks_like_image_request_rejects_non_image_text(text):
    assert not ip.looks_like_image_request(text)


def test_estimate_image_cost_usd_known_and_unknown_providers():
    assert ip.estimate_image_cost_usd("replicate") == ip.PRICE_PER_IMAGE_USD["replicate"]
    assert ip.estimate_image_cost_usd("openai") > 0
    assert ip.estimate_image_cost_usd("does-not-exist") == 0.0
    assert ip.estimate_image_cost_usd("") == 0.0


def test_size_to_dims_parses_and_falls_back():
    assert ip._size_to_dims("1536x1024") == (1536, 1024)
    assert ip._size_to_dims("not-a-size") == (1024, 1024)
    assert ip._size_to_dims("") == (1024, 1024)


@pytest.mark.parametrize(
    "name,kwarg",
    [
        ("openai", "openai_api_key"),
        ("google_imagen", "google_api_key"),
        ("stability", "stability_api_key"),
        ("fal", "fal_api_key"),
    ],
)
def test_provider_unavailable_without_key_and_available_with_key(name, kwarg):
    unavailable = ip.get_provider(name, **{kwarg: ""})
    assert unavailable.available is False

    available = ip.get_provider(name, **{kwarg: "test-key"})
    assert available.available is True


def test_replicate_provider_requires_token_and_version_or_model():
    no_creds = ip.get_provider("replicate", replicate_tokens=[], replicate_version="", replicate_model="")
    assert no_creds.available is False

    with_creds = ip.get_provider(
        "replicate", replicate_tokens=["tok"], replicate_version="some-version", replicate_model="",
    )
    assert with_creds.available is True


def test_get_provider_rejects_unknown_name():
    with pytest.raises(ip.ImageProviderError):
        ip.get_provider("not-a-real-provider")


def test_generate_raises_clear_error_when_unavailable():
    provider = ip.get_provider("openai", openai_api_key="")
    with pytest.raises(ip.ImageProviderError):
        asyncio.run(provider.generate("a cat"))


def test_replicate_overrides_for_flux_model_drops_width_height():
    overrides = ip._replicate_overrides_for_model(
        "black-forest-labs/flux-2-pro", "1536x1024", "high", None,
    )
    assert overrides["aspect_ratio"] == "3:2"
    assert overrides["output_quality"] == 90
    assert "width" not in overrides and "height" not in overrides


def test_replicate_overrides_for_generic_model_sets_width_height():
    overrides = ip._replicate_overrides_for_model("some/other-model", "1024x1536", "medium", None)
    assert overrides["width"] == 1024
    assert overrides["height"] == 1536
