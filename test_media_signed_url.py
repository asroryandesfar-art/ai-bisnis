"""M-02 — signed media URL + enforcement (default-off flag).

Menguji penandatanganan HMAC dan penegakan di GET /media/{path}.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

import main


def test_sign_is_deterministic_and_appended():
    url = "/media/generated/abc123.png"
    signed = main._media_signed_url(url)
    assert signed.startswith("/media/generated/abc123.png?sig=")
    # idempoten: menandatangani lagi menghasilkan URL setara
    assert main._media_signed_url(signed) == signed


def test_sign_ignores_non_media_url():
    assert main._media_signed_url("https://x/y.png") == "https://x/y.png"
    assert main._media_signed_url("") == ""


@pytest.fixture()
def media_file():
    d = main._MEDIA_DIR / "test"
    d.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.txt"
    f = d / name
    f.write_text("hello-media")
    yield f"test/{name}"
    try:
        f.unlink()
    except FileNotFoundError:
        pass


def test_media_open_when_flag_off(media_file, monkeypatch):
    monkeypatch.setattr(main.cfg, "media_require_signature", False)
    with TestClient(main.app) as client:
        r = client.get(f"/media/{media_file}")
    assert r.status_code == 200


def test_media_requires_valid_sig_when_flag_on(media_file, monkeypatch):
    monkeypatch.setattr(main.cfg, "media_require_signature", True)
    with TestClient(main.app) as client:
        # tanpa sig -> ditolak
        assert client.get(f"/media/{media_file}").status_code == 403
        # sig salah -> ditolak
        assert client.get(f"/media/{media_file}?sig=deadbeef").status_code == 403
        # sig sah -> boleh
        good = main._sign_media_rel(media_file)
        ok = client.get(f"/media/{media_file}?sig={good}")
    assert ok.status_code == 200
    assert ok.text == "hello-media"


def test_signed_url_from_helper_passes_enforcement(media_file, monkeypatch):
    monkeypatch.setattr(main.cfg, "media_require_signature", True)
    signed = main._media_signed_url(f"/media/{media_file}")
    with TestClient(main.app) as client:
        r = client.get(signed)
    assert r.status_code == 200
