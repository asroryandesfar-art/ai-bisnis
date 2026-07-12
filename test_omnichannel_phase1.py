from pathlib import Path

import pytest

from bn_platform.channels import (
    BaseConnector,
    FacebookConnector,
    InstagramConnector,
    TelegramConnector,
    WebChatConnector,
    WhatsAppConnector,
)
from bn_platform.channels.models import ChannelType
from bn_platform.omnichannel import build_omnichannel_router, platform_channel_config
from bn_platform.config import cfg as platform_cfg

ROOT = Path(__file__).resolve().parent


def test_all_phase1_connectors_follow_base_contract():
    for connector in (WhatsAppConnector, TelegramConnector, InstagramConnector, FacebookConnector, WebChatConnector):
        assert issubclass(connector, BaseConnector)
        assert not connector.__abstractmethods__


@pytest.mark.asyncio
async def test_telegram_payload_is_normalized_to_unified_message():
    connector = TelegramConnector(tenant_id="tenant-1", connection_id="conn-1", credentials={"bot_token": "test"})
    messages = await connector.receive_message({"message": {"message_id": 12, "date": 1710000000, "chat": {"id": 42, "username": "nisa"}, "text": "Halo"}})
    assert len(messages) == 1
    assert messages[0].tenant_id == "tenant-1"
    assert messages[0].channel == ChannelType.TELEGRAM
    assert messages[0].user_id == "tg:42"
    assert messages[0].message == "Halo"


@pytest.mark.asyncio
async def test_meta_payloads_are_normalized_without_leaking_provider_shape():
    whatsapp = WhatsAppConnector(tenant_id="tenant-1", connection_id="wa-1", credentials={})
    wa = await whatsapp.receive_message({"entry": [{"changes": [{"value": {"contacts": [{"wa_id": "6281", "profile": {"name": "Ayu"}}], "messages": [{"id": "wamid.1", "from": "6281", "timestamp": "1710000000", "text": {"body": "Info produk"}}]}}]}]})
    assert wa[0].user_id == "wa:6281"
    assert wa[0].username == "Ayu"

    facebook = FacebookConnector(tenant_id="tenant-1", connection_id="fb-1", credentials={})
    fb = await facebook.receive_message({"entry": [{"messaging": [{"sender": {"id": "99"}, "timestamp": 1710000000000, "message": {"mid": "m1", "text": "Halo FB"}}]}]})
    assert fb[0].channel == ChannelType.FACEBOOK
    assert fb[0].user_id == "fb:99"


@pytest.mark.asyncio
async def test_webchat_payload_is_normalized():
    connector = WebChatConnector(tenant_id="tenant-1", connection_id="web-1", credentials={})
    messages = await connector.receive_message({"user_id": "web:session", "username": "Visitor", "message": "Butuh bantuan", "page": "/pricing"})
    assert messages[0].channel == ChannelType.WEBSITE
    assert messages[0].metadata == {"page": "/pricing"}


def test_schema_contains_all_tenant_scoped_omnichannel_tables():
    schema = (ROOT / "bn_platform/schema_platform.sql").read_text()
    for table in ("channels", "channel_connections", "channel_messages", "channel_events", "channel_logs"):
        section = schema.split(f"CREATE TABLE IF NOT EXISTS {table} (", 1)[1].split(");", 1)[0]
        assert "tenant_id" in section
    assert "'facebook'" in schema


def test_router_exposes_required_channel_api():
    async def dependency():
        return None

    def require_permission(_permission):
        return dependency

    router = build_omnichannel_router(get_pool=dependency, get_current_user=dependency, require_permission=require_permission, app_url="https://example.test")
    routes = {(method, route.path) for route in router.routes for method in getattr(route, "methods", set())}
    for expected in (("GET", "/channels"), ("POST", "/channels/connect"), ("POST", "/channels/disconnect"), ("GET", "/channels/status"), ("GET", "/channels/analytics")):
        assert expected in routes


def test_platform_channel_credentials_come_from_environment(monkeypatch):
    monkeypatch.setattr(platform_cfg, "telegram_bot_token", "platform-telegram")
    monkeypatch.setattr(platform_cfg, "instagram_access_token", "platform-instagram")
    monkeypatch.setattr(platform_cfg, "instagram_account_id", "ig-account")
    monkeypatch.setattr(platform_cfg, "facebook_page_access_token", "platform-facebook")
    monkeypatch.setattr(platform_cfg, "facebook_page_id", "fb-page")

    telegram, telegram_id = platform_channel_config(ChannelType.TELEGRAM)
    instagram, instagram_id = platform_channel_config(ChannelType.INSTAGRAM)
    facebook, facebook_id = platform_channel_config(ChannelType.FACEBOOK)

    assert telegram == {"bot_token": "platform-telegram"}
    assert telegram_id is None
    assert instagram == {"access_token": "platform-instagram", "instagram_account_id": "ig-account"}
    assert instagram_id == "ig-account"
    assert facebook == {"access_token": "platform-facebook", "page_id": "fb-page"}
    assert facebook_id == "fb-page"


def test_platform_channel_config_rejects_missing_operator_secret(monkeypatch):
    monkeypatch.setattr(platform_cfg, "telegram_bot_token", "")
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        platform_channel_config(ChannelType.TELEGRAM)


def test_widget_and_agent_channel_sanitization_are_wired():
    widget = (ROOT / "frontend/botnesia-widget.js").read_text()
    main_src = (ROOT / "main.py").read_text()
    assert "botnesia-chat" in widget
    assert "/api/channels/webchat/" in widget
    assert 'key not in {"channel", "_channel"}' in main_src
    # The /botnesia-widget.js route was extracted to bn_platform/pages.py during
    # the main.py strangler split; assert it is still wired on the app (behavior)
    # rather than defined in main.py source text (brittle to further extraction).
    import main as main_mod
    assert any(getattr(r, "path", None) == "/botnesia-widget.js" for r in main_mod.app.routes)
