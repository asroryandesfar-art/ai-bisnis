import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI

from bn_platform.channels.models import ChannelType
from bn_platform.meta_oauth import (
    META_SCOPES,
    _sync_selected_channel_tokens,
    build_meta_oauth_router,
    claim_meta_asset,
    fetch_pages,
    public_meta_account,
)


def test_public_meta_account_never_exposes_tokens():
    public = public_meta_account({
        "status": "connected",
        "user_access_token": "secret-user-token",
        "pages": [{
            "id": "page-1", "name": "Acme", "access_token": "secret-page-token",
            "instagram": {"id": "ig-1", "username": "acme"},
        }],
        "selected": {"facebook": {"page_id": "page-1"}},
    })
    assert public["connected"] is True
    assert "user_access_token" not in public
    assert "access_token" not in public["pages"][0]
    assert public["pages"][0]["instagram"]["id"] == "ig-1"


def test_meta_scopes_cover_page_and_instagram_messaging():
    assert "pages_show_list" in META_SCOPES
    assert "pages_messaging" in META_SCOPES
    assert "instagram_basic" in META_SCOPES
    assert "instagram_manage_messages" in META_SCOPES


def test_fetch_pages_normalizes_linked_instagram(monkeypatch):
    async def fake_graph(method, path, **kwargs):
        assert method == "GET"
        assert path == "me/accounts"
        assert kwargs["token"] == "user-token"
        return {"data": [{
            "id": "page-1", "name": "Acme Page", "access_token": "page-token",
            "instagram_business_account": {"id": "ig-1", "username": "acme.id"},
        }]}

    monkeypatch.setattr("bn_platform.meta_oauth._graph", fake_graph)
    pages = asyncio.run(fetch_pages("user-token"))
    assert pages == [{
        "id": "page-1", "name": "Acme Page", "access_token": "page-token",
        "instagram": {"id": "ig-1", "username": "acme.id"},
    }]


def test_meta_oauth_router_has_complete_saas_flow():
    async def dependency():
        return None

    def require_permission(permission):
        assert permission == "settings.manage"
        return dependency

    router = build_meta_oauth_router(
        get_pool=dependency,
        get_current_user=dependency,
        require_permission=require_permission,
    )
    routes = {(method, route.path) for route in router.routes for method in getattr(route, "methods", set())}
    assert ("POST", "/integrations/meta/oauth/start") in routes
    assert ("GET", "/integrations/meta/oauth/callback") in routes
    assert ("GET", "/integrations/meta/oauth/status") in routes
    assert ("POST", "/integrations/meta/oauth/select") in routes
    assert ("POST", "/integrations/meta/oauth/refresh") in routes
    assert ("POST", "/integrations/meta/oauth/disconnect") in routes


def test_meta_oauth_dependencies_are_not_exposed_as_query_parameters():
    async def dependency():
        return None

    def require_permission(_permission):
        return dependency

    router = build_meta_oauth_router(
        get_pool=dependency,
        get_current_user=dependency,
        require_permission=require_permission,
    )
    app = FastAPI()
    app.include_router(router)
    schema = app.openapi()
    for path, operations in schema["paths"].items():
        if not path.startswith("/integrations/meta/oauth"):
            continue
        for operation in operations.values():
            query_names = {
                parameter["name"]
                for parameter in operation.get("parameters", [])
                if parameter.get("in") == "query"
            }
            assert "user" not in query_names
            assert "pool" not in query_names


class FakePool:
    def __init__(self):
        self.calls = []

    async def execute(self, sql, *args):
        self.calls.append((" ".join(sql.split()), args))
        return "UPDATE 1"


def test_refresh_syncs_page_token_to_each_selected_channel(monkeypatch):
    monkeypatch.setattr(
        "bn_platform.meta_oauth.ChannelManager._encrypt_credentials",
        staticmethod(lambda value: {key: f"encrypted:{item}" for key, item in value.items()}),
    )
    pool = FakePool()
    account = {
        "pages": [{"id": "page-1", "access_token": "new-page-token"}],
        "selected": {
            "facebook": {"page_id": "page-1"},
            "instagram": {"page_id": "page-1", "instagram_id": "ig-1"},
        },
    }
    asyncio.run(_sync_selected_channel_tokens(pool, "tenant-1", account))
    assert len(pool.calls) == 4
    serialized = " ".join(str(call) for call in pool.calls)
    assert "encrypted:new-page-token" in serialized
    assert "facebook" in serialized
    assert "instagram" in serialized


class FakeAssetPool:
    def __init__(self, existing=None):
        self.existing = existing
        self.executed = []

    async def fetchrow(self, sql, *args):
        return self.existing

    async def execute(self, sql, *args):
        self.executed.append(args)
        return "INSERT 1"


def test_meta_asset_cannot_be_claimed_by_another_active_tenant():
    pool = FakeAssetPool({"org_id": "tenant-other", "status": "connected"})
    try:
        asyncio.run(claim_meta_asset(pool, org_id="tenant-1", bot_id="bot-1", channel="facebook", external_id="page-1", connection_id="conn-1"))
        assert False, "claim should fail"
    except ValueError as exc:
        assert "tenant lain" in str(exc)
    assert pool.executed == []


def test_disconnected_meta_asset_can_be_reclaimed():
    pool = FakeAssetPool({"org_id": "tenant-old", "status": "disconnected"})
    asyncio.run(claim_meta_asset(pool, org_id="tenant-new", bot_id="bot-2", channel="instagram", external_id="ig-1", connection_id="conn-2"))
    assert pool.executed
    assert pool.executed[0][:3] == ("instagram", "ig-1", "tenant-new")
