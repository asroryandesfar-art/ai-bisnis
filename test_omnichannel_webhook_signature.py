"""
POST /webhooks/channels/{channel}/{connection_id} verified Telegram's
secret-token header (fixed in test_channel_webhook_security.py) but had NO
verification at all for whatsapp/instagram/facebook -- only the
connection_id (a UUID embedded in the URL) gated it. Meta always sends
X-Hub-Signature-256 on these webhooks, so it's now checked the same way
main.py's separate /webhooks/meta endpoint already does (same
META_APP_SECRET, fail-closed if unset).

website channel (WebChatConnector) intentionally has no signature check --
it's a public browser widget endpoint by design, not a Meta API webhook.
"""
import hashlib
import hmac
import json

import pytest
from fastapi import HTTPException

import bn_platform.omnichannel as omnichannel_module
from bn_platform.channels.models import ChannelType
from bn_platform.omnichannel import build_omnichannel_router


class _FakeRequest:
    def __init__(self, payload: dict, headers: dict | None = None):
        self._body = json.dumps(payload).encode("utf-8")
        self.headers = headers or {}

    async def body(self):
        return self._body


def _get_route_endpoint(router, path: str, method: str):
    for route in router.routes:
        if route.path == path and method in route.methods:
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


def _build_router_and_handler(monkeypatch, app_secret: str):
    monkeypatch.setattr(omnichannel_module.platform_cfg, "meta_app_secret", app_secret)

    async def fake_dep():
        return None

    router = build_omnichannel_router(
        get_pool=fake_dep, get_current_user=fake_dep,
        require_permission=lambda key: fake_dep, app_url="https://example.test",
    )
    return _get_route_endpoint(router, "/webhooks/channels/{channel}/{connection_id}", "POST")


@pytest.mark.parametrize("channel", [ChannelType.WHATSAPP, ChannelType.INSTAGRAM, ChannelType.FACEBOOK])
def test_meta_channel_webhook_rejects_when_secret_not_configured(monkeypatch, channel):
    import asyncio
    handler = _build_router_and_handler(monkeypatch, app_secret="")
    request = _FakeRequest({"entry": []})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(channel, "conn-1", request, pool=None))
    assert exc.value.status_code == 503


@pytest.mark.parametrize("channel", [ChannelType.WHATSAPP, ChannelType.INSTAGRAM, ChannelType.FACEBOOK])
def test_meta_channel_webhook_rejects_wrong_signature(monkeypatch, channel):
    import asyncio
    handler = _build_router_and_handler(monkeypatch, app_secret="test-secret")
    request = _FakeRequest({"entry": []}, headers={"X-Hub-Signature-256": "sha256=not-the-real-signature"})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(channel, "conn-1", request, pool=None))
    assert exc.value.status_code == 403


@pytest.mark.parametrize("channel", [ChannelType.WHATSAPP, ChannelType.INSTAGRAM, ChannelType.FACEBOOK])
def test_meta_channel_webhook_rejects_missing_signature_header(monkeypatch, channel):
    import asyncio
    handler = _build_router_and_handler(monkeypatch, app_secret="test-secret")
    request = _FakeRequest({"entry": []})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(channel, "conn-1", request, pool=None))
    assert exc.value.status_code == 403


def test_meta_channel_webhook_accepts_correct_signature_and_proceeds(monkeypatch):
    import asyncio

    async def fake_receive_message(self, *, connection_id, payload):
        return []

    monkeypatch.setattr(omnichannel_module.ChannelManager, "receive_message", fake_receive_message)
    handler = _build_router_and_handler(monkeypatch, app_secret="test-secret")

    body = {"entry": []}
    raw = json.dumps(body).encode("utf-8")
    signature = "sha256=" + hmac.new(b"test-secret", raw, hashlib.sha256).hexdigest()
    request = _FakeRequest(body, headers={"X-Hub-Signature-256": signature})

    result = asyncio.run(handler(ChannelType.WHATSAPP, "conn-1", request, pool=object()))
    assert result == {"ok": True, "processed": 0}


def test_website_channel_webhook_has_no_signature_requirement(monkeypatch):
    """Website widget endpoint is intentionally public -- no Meta secret involved."""
    import asyncio

    async def fake_receive_message(self, *, connection_id, payload):
        return []

    monkeypatch.setattr(omnichannel_module.ChannelManager, "receive_message", fake_receive_message)
    handler = _build_router_and_handler(monkeypatch, app_secret="")
    request = _FakeRequest({"message": "halo", "user_id": "web:1"})

    result = asyncio.run(handler(ChannelType.WEBSITE, "conn-1", request, pool=object()))
    assert result == {"ok": True, "processed": 0}
