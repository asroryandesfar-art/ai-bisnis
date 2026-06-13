"""
test_whatsapp_embedded_signup.py — Tes untuk Meta WhatsApp Embedded Signup:

- whatsapp_embedded_signup.py: klien Graph API (tukar code, register nomor,
  subscribe/unsubscribe webhook WABA) — di-mock via httpx.AsyncClient palsu.
- integrations_store.py: penyimpanan kredensial per tenant
  (whatsapp_embedded_accounts) — token terenkripsi (Fernet) di kolom
  access_token_enc, field lain plaintext untuk query.
- main.py: endpoint GET /integrations/whatsapp/connect,
  POST /integrations/whatsapp/callback, GET /integrations/whatsapp/status,
  POST /integrations/whatsapp/disconnect — termasuk tenant isolation
  (org_id+bot_id) dan CSRF state.

Mengikuti pola FakePool (test_security_platform.py / test_marketplace.py) —
tidak ada koneksi database sungguhan.
"""
import asyncio

import pytest
from fastapi import HTTPException

import integrations_store as istore
import whatsapp_embedded_signup as wes


# ─────────────────────────────────────────────────────────────────
# Helpers: fake asyncpg pool (acquire().execute/fetchrow/fetch)
# ─────────────────────────────────────────────────────────────────

class _AcquireCtx:
    def __init__(self, pool):
        self._pool = pool

    async def __aenter__(self):
        return self._pool

    async def __aexit__(self, *exc):
        return False


class FakePool:
    """Pool stateful minimal: oauth_states, whatsapp_embedded_accounts,
    meta_wa_phone_map, dan bots (untuk validasi tenant)."""

    def __init__(self, bots=None):
        self.bots = dict(bots or {})  # bot_id -> org_id
        self.oauth_states = {}        # (provider, state) -> {"org_id":..., "redirect_uri":...}
        self.whatsapp_accounts = {}   # (org_id, bot_id) -> row dict
        self.phone_map = {}           # phone_number_id -> {"org_id":..., "bot_id":...}
        self.calls = []

    def acquire(self):
        return _AcquireCtx(self)

    async def fetchrow(self, sql, *args):
        q = " ".join(sql.split())
        self.calls.append(("fetchrow", q, args))
        if "FROM bots WHERE id=$1 AND org_id=$2" in q:
            bot_id, org_id = args
            if self.bots.get(bot_id) == org_id:
                return {"id": bot_id}
            return None
        if "FROM oauth_states WHERE provider=$1 AND state=$2" in q:
            provider, state = args
            return self.oauth_states.get((provider, state))
        if "FROM whatsapp_embedded_accounts WHERE org_id=$1 AND bot_id=$2" in q:
            return self.whatsapp_accounts.get(args)
        if "FROM meta_wa_phone_map WHERE phone_number_id=$1" in q:
            (phone_number_id,) = args
            return self.phone_map.get(phone_number_id)
        return None

    async def fetch(self, sql, *args):
        q = " ".join(sql.split())
        self.calls.append(("fetch", q, args))
        if "FROM whatsapp_embedded_accounts WHERE org_id=$1" in q:
            (org_id,) = args
            return [row for (o, _b), row in self.whatsapp_accounts.items() if o == org_id]
        return []

    async def execute(self, sql, *args):
        q = " ".join(sql.split())
        self.calls.append(("execute", q, args))
        if "INSERT INTO oauth_states" in q:
            provider, state, org_id, redirect_uri = args
            self.oauth_states[(provider, state)] = {"org_id": org_id, "redirect_uri": redirect_uri}
        elif "DELETE FROM oauth_states" in q:
            provider, state = args
            self.oauth_states.pop((provider, state), None)
        elif "INSERT INTO whatsapp_embedded_accounts" in q:
            org_id, bot_id, waba_id, phone_number_id, business_id, access_token_enc, token_expires_at, connection_status = args
            self.whatsapp_accounts[(org_id, bot_id)] = {
                "org_id": org_id, "bot_id": bot_id, "waba_id": waba_id,
                "phone_number_id": phone_number_id, "business_id": business_id,
                "access_token_enc": access_token_enc, "token_expires_at": token_expires_at,
                "connection_status": connection_status,
            }
        elif "DELETE FROM whatsapp_embedded_accounts" in q:
            org_id, bot_id = args
            self.whatsapp_accounts.pop((org_id, bot_id), None)
        elif "INSERT INTO meta_wa_phone_map" in q:
            phone_number_id, org_id, bot_id = args
            self.phone_map[phone_number_id] = {"org_id": org_id, "bot_id": bot_id}
        elif "DELETE FROM meta_wa_phone_map" in q:
            (phone_number_id,) = args
            self.phone_map.pop(phone_number_id, None)
        return "OK"


# ─────────────────────────────────────────────────────────────────
# Helpers: fake httpx.AsyncClient for whatsapp_embedded_signup.py
# ─────────────────────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text

    def json(self):
        return self._json_data


class _FakeAsyncClient:
    def __init__(self, response, captured):
        self._response = response
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None):
        self._captured.append(("GET", url, params))
        return self._response

    async def post(self, url, json=None, headers=None):
        self._captured.append(("POST", url, json, headers))
        return self._response

    async def delete(self, url, headers=None):
        self._captured.append(("DELETE", url, headers))
        return self._response


def _patch_client(monkeypatch, response):
    captured = []
    monkeypatch.setattr(wes.httpx, "AsyncClient", lambda timeout=None: _FakeAsyncClient(response, captured))
    return captured


# ─────────────────────────────────────────────────────────────────
# 1) whatsapp_embedded_signup.py — Graph API client
# ─────────────────────────────────────────────────────────────────

def test_exchange_code_for_token_success(monkeypatch):
    captured = _patch_client(monkeypatch, _FakeResponse(200, {"access_token": "tok-123", "expires_in": 3600}))

    result = asyncio.run(wes.exchange_code_for_token(
        app_id="app-1", app_secret="secret-1", code="code-1", api_version="v21.0",
    ))

    assert result == {"success": True, "data": {"access_token": "tok-123", "expires_in": 3600}}
    method, url, params = captured[0]
    assert method == "GET"
    assert "v21.0/oauth/access_token" in url
    assert params == {"client_id": "app-1", "client_secret": "secret-1", "code": "code-1"}


def test_exchange_code_for_token_http_error(monkeypatch):
    _patch_client(monkeypatch, _FakeResponse(400, text="invalid code"))

    result = asyncio.run(wes.exchange_code_for_token(
        app_id="app-1", app_secret="secret-1", code="bad", api_version="v21.0",
    ))

    assert result["success"] is False
    assert "invalid code" in result["error"]


def test_register_phone_number_success(monkeypatch):
    captured = _patch_client(monkeypatch, _FakeResponse(200, {"success": True}))

    result = asyncio.run(wes.register_phone_number(
        phone_number_id="pn-1", access_token="tok-123", pin="112233", api_version="v21.0",
    ))

    assert result == {"success": True, "data": {"success": True}}
    method, url, payload, headers = captured[0]
    assert method == "POST"
    assert "pn-1/register" in url
    assert payload == {"messaging_product": "whatsapp", "pin": "112233"}
    assert headers == {"Authorization": "Bearer tok-123"}


def test_subscribe_app_to_waba_success(monkeypatch):
    captured = _patch_client(monkeypatch, _FakeResponse(200, {"success": True}))

    result = asyncio.run(wes.subscribe_app_to_waba(
        waba_id="waba-1", access_token="tok-123", api_version="v21.0",
    ))

    assert result["success"] is True
    method, url, _payload, headers = captured[0]
    assert method == "POST"
    assert "waba-1/subscribed_apps" in url
    assert headers == {"Authorization": "Bearer tok-123"}


def test_unsubscribe_app_from_waba_success(monkeypatch):
    captured = _patch_client(monkeypatch, _FakeResponse(200, {"success": True}))

    result = asyncio.run(wes.unsubscribe_app_from_waba(
        waba_id="waba-1", access_token="tok-123", api_version="v21.0",
    ))

    assert result["success"] is True
    method, url, headers = captured[0]
    assert method == "DELETE"
    assert "waba-1/subscribed_apps" in url


def test_register_phone_number_error_returns_message(monkeypatch):
    _patch_client(monkeypatch, _FakeResponse(401, text="Invalid OAuth access token"))

    result = asyncio.run(wes.register_phone_number(
        phone_number_id="pn-1", access_token="bad-token", pin="112233", api_version="v21.0",
    ))

    assert result["success"] is False
    assert "Invalid OAuth access token" in result["error"]


# ─────────────────────────────────────────────────────────────────
# 2) integrations_store.py — whatsapp_embedded_accounts (encrypted)
# ─────────────────────────────────────────────────────────────────

SECRET = "test-secret-key"


def test_set_and_get_whatsapp_account_roundtrip_decrypts_token():
    pool = FakePool()

    asyncio.run(istore.db_set_whatsapp_account(
        pool, org_id="org-1", bot_id="bot-1",
        waba_id="waba-1", phone_number_id="pn-1", business_id="biz-1",
        customer_access_token="super-secret-token", token_expires_at=None,
        connection_status="connected", secret_key=SECRET,
    ))

    acc = asyncio.run(istore.db_get_whatsapp_account(pool, org_id="org-1", bot_id="bot-1", secret_key=SECRET))

    assert acc["tenant_id"] == "org-1"
    assert acc["bot_id"] == "bot-1"
    assert acc["waba_id"] == "waba-1"
    assert acc["phone_number_id"] == "pn-1"
    assert acc["business_id"] == "biz-1"
    assert acc["customer_access_token"] == "super-secret-token"
    assert acc["connection_status"] == "connected"


def test_access_token_is_encrypted_at_rest():
    pool = FakePool()

    asyncio.run(istore.db_set_whatsapp_account(
        pool, org_id="org-1", bot_id="bot-1",
        waba_id="waba-1", phone_number_id="pn-1", business_id="biz-1",
        customer_access_token="super-secret-token", token_expires_at=None,
        connection_status="connected", secret_key=SECRET,
    ))

    stored = pool.whatsapp_accounts[("org-1", "bot-1")]
    assert "super-secret-token" not in stored["access_token_enc"]

    # Wrong secret key can't decrypt -> empty dict -> empty token (graceful, not a crash).
    acc_wrong_key = asyncio.run(istore.db_get_whatsapp_account(pool, org_id="org-1", bot_id="bot-1", secret_key="other-key"))
    assert acc_wrong_key["customer_access_token"] == ""


def test_get_whatsapp_accounts_lists_org_and_isolates_other_orgs():
    pool = FakePool()

    asyncio.run(istore.db_set_whatsapp_account(
        pool, org_id="org-1", bot_id="bot-1",
        waba_id="waba-1", phone_number_id="pn-1", business_id="biz-1",
        customer_access_token="token-org1", token_expires_at=None,
        connection_status="connected", secret_key=SECRET,
    ))
    asyncio.run(istore.db_set_whatsapp_account(
        pool, org_id="org-2", bot_id="bot-2",
        waba_id="waba-2", phone_number_id="pn-2", business_id="biz-2",
        customer_access_token="token-org2", token_expires_at=None,
        connection_status="connected", secret_key=SECRET,
    ))

    org1_accounts = asyncio.run(istore.db_get_whatsapp_accounts(pool, org_id="org-1", secret_key=SECRET))
    assert len(org1_accounts) == 1
    assert org1_accounts[0]["bot_id"] == "bot-1"
    assert org1_accounts[0]["customer_access_token"] == "token-org1"

    # org-2 has no access to org-1's account, even with bot_id collision.
    cross_org = asyncio.run(istore.db_get_whatsapp_account(pool, org_id="org-2", bot_id="bot-1", secret_key=SECRET))
    assert cross_org is None


def test_clear_whatsapp_account_removes_row():
    pool = FakePool()
    asyncio.run(istore.db_set_whatsapp_account(
        pool, org_id="org-1", bot_id="bot-1",
        waba_id="waba-1", phone_number_id="pn-1", business_id="biz-1",
        customer_access_token="token", token_expires_at=None,
        connection_status="connected", secret_key=SECRET,
    ))

    asyncio.run(istore.db_clear_whatsapp_account(pool, org_id="org-1", bot_id="bot-1"))

    assert asyncio.run(istore.db_get_whatsapp_account(pool, org_id="org-1", bot_id="bot-1", secret_key=SECRET)) is None


def test_clear_meta_phone_mapping_removes_entry():
    pool = FakePool()
    asyncio.run(istore.db_set_meta_phone_mapping(pool, phone_number_id="pn-1", org_id="org-1", bot_id="bot-1"))
    assert asyncio.run(istore.db_get_meta_phone_mapping(pool, phone_number_id="pn-1")) == ("org-1", "bot-1")

    asyncio.run(istore.db_clear_meta_phone_mapping(pool, phone_number_id="pn-1"))

    assert asyncio.run(istore.db_get_meta_phone_mapping(pool, phone_number_id="pn-1")) == (None, None)


# ─────────────────────────────────────────────────────────────────
# 3) main.py endpoints
# ─────────────────────────────────────────────────────────────────

import main  # noqa: E402


def _user(org_id="org-1"):
    return {"org_id": org_id, "id": "user-1", "email": "owner@x.com"}


@pytest.fixture(autouse=True)
def _meta_config(monkeypatch):
    monkeypatch.setattr(main.cfg, "meta_app_id", "app-123")
    monkeypatch.setattr(main.cfg, "meta_embedded_signup_config_id", "config-456")
    monkeypatch.setattr(main.cfg, "meta_app_secret", "app-secret")
    monkeypatch.setattr(main.cfg, "meta_register_pin", "112233")
    monkeypatch.setattr(main.cfg, "meta_api_version", "v21.0")


def test_connect_requires_meta_config(monkeypatch):
    monkeypatch.setattr(main.cfg, "meta_app_id", "")
    pool = FakePool(bots={"bot-1": "org-1"})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.whatsapp_embedded_connect(bot_id="bot-1", user=_user(), pool=pool))
    assert exc.value.status_code == 400


def test_connect_unknown_bot_returns_404():
    pool = FakePool(bots={"bot-1": "org-1"})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.whatsapp_embedded_connect(bot_id="bot-1", user=_user(org_id="org-2"), pool=pool))
    assert exc.value.status_code == 404


def test_connect_returns_signup_config_and_persists_state():
    pool = FakePool(bots={"bot-1": "org-1"})

    result = asyncio.run(main.whatsapp_embedded_connect(bot_id="bot-1", user=_user(), pool=pool))

    assert result["app_id"] == "app-123"
    assert result["config_id"] == "config-456"
    assert result["graph_api_version"] == "v21.0"
    assert result["bot_id"] == "bot-1"
    state = result["state"]
    assert pool.oauth_states[("whatsapp_embedded", state)] == {"org_id": "org-1", "redirect_uri": "bot-1"}


def _callback_body(state, **overrides):
    body = dict(state=state, code="auth-code-1", waba_id="waba-1", phone_number_id="pn-1", business_id="biz-1")
    body.update(overrides)
    return main.WhatsAppEmbeddedCallbackReq(**body)


def test_callback_invalid_state_returns_400():
    pool = FakePool(bots={"bot-1": "org-1"})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.whatsapp_embedded_callback(_callback_body("nonexistent-state"), user=_user(), pool=pool))
    assert exc.value.status_code == 400


def test_callback_rejects_state_from_other_tenant():
    pool = FakePool(bots={"bot-1": "org-1"})
    pool.oauth_states[("whatsapp_embedded", "state-1")] = {"org_id": "org-1", "redirect_uri": "bot-1"}

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.whatsapp_embedded_callback(_callback_body("state-1"), user=_user(org_id="org-2"), pool=pool))
    assert exc.value.status_code == 403


def test_callback_success_saves_encrypted_credentials_and_phone_mapping(monkeypatch):
    pool = FakePool(bots={"bot-1": "org-1"})
    pool.oauth_states[("whatsapp_embedded", "state-1")] = {"org_id": "org-1", "redirect_uri": "bot-1"}

    async def fake_exchange(**kwargs):
        assert kwargs["app_id"] == "app-123"
        assert kwargs["code"] == "auth-code-1"
        return {"success": True, "data": {"access_token": "long-lived-token", "expires_in": 5184000}}

    async def fake_register(**kwargs):
        assert kwargs["pin"] == "112233"
        assert kwargs["access_token"] == "long-lived-token"
        return {"success": True, "data": {"success": True}}

    async def fake_subscribe(**kwargs):
        assert kwargs["waba_id"] == "waba-1"
        return {"success": True, "data": {"success": True}}

    monkeypatch.setattr(main, "wa_exchange_code_for_token", fake_exchange)
    monkeypatch.setattr(main, "wa_register_phone_number", fake_register)
    monkeypatch.setattr(main, "wa_subscribe_app_to_waba", fake_subscribe)

    result = asyncio.run(main.whatsapp_embedded_callback(_callback_body("state-1"), user=_user(), pool=pool))

    assert result["connection_status"] == "connected"
    assert result["tenant_id"] == "org-1"
    assert result["bot_id"] == "bot-1"
    assert result["waba_id"] == "waba-1"
    assert result["token_expires_at"] is not None

    # state consumed (CSRF / replay protection)
    assert ("whatsapp_embedded", "state-1") not in pool.oauth_states

    # token encrypted at rest
    stored = pool.whatsapp_accounts[("org-1", "bot-1")]
    assert "long-lived-token" not in stored["access_token_enc"]
    assert stored["connection_status"] == "connected"

    # inbound webhook routing wired up
    assert pool.phone_map["pn-1"] == {"org_id": "org-1", "bot_id": "bot-1"}


def test_callback_token_exchange_failure_records_error_status(monkeypatch):
    pool = FakePool(bots={"bot-1": "org-1"})
    pool.oauth_states[("whatsapp_embedded", "state-1")] = {"org_id": "org-1", "redirect_uri": "bot-1"}

    async def fake_exchange(**kwargs):
        return {"success": False, "error": "invalid code"}

    monkeypatch.setattr(main, "wa_exchange_code_for_token", fake_exchange)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.whatsapp_embedded_callback(_callback_body("state-1"), user=_user(), pool=pool))
    assert exc.value.status_code == 400

    stored = pool.whatsapp_accounts[("org-1", "bot-1")]
    assert stored["connection_status"] == "error"
    assert pool.phone_map == {}


def test_callback_register_failure_records_error_status(monkeypatch):
    pool = FakePool(bots={"bot-1": "org-1"})
    pool.oauth_states[("whatsapp_embedded", "state-1")] = {"org_id": "org-1", "redirect_uri": "bot-1"}

    async def fake_exchange(**kwargs):
        return {"success": True, "data": {"access_token": "tok-1"}}

    async def fake_register(**kwargs):
        return {"success": False, "error": "register failed"}

    async def fake_subscribe(**kwargs):
        return {"success": True, "data": {}}

    monkeypatch.setattr(main, "wa_exchange_code_for_token", fake_exchange)
    monkeypatch.setattr(main, "wa_register_phone_number", fake_register)
    monkeypatch.setattr(main, "wa_subscribe_app_to_waba", fake_subscribe)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.whatsapp_embedded_callback(_callback_body("state-1"), user=_user(), pool=pool))
    assert exc.value.status_code == 400

    stored = pool.whatsapp_accounts[("org-1", "bot-1")]
    assert stored["connection_status"] == "error"
    assert pool.phone_map == {}


def test_status_without_connection_returns_disconnected():
    pool = FakePool(bots={"bot-1": "org-1"})

    result = asyncio.run(main.whatsapp_embedded_status(bot_id="bot-1", user=_user(), pool=pool))

    assert result["connected"] is False
    assert result["connection_status"] == "disconnected"


def test_status_returns_account_without_raw_token():
    pool = FakePool(bots={"bot-1": "org-1"})
    asyncio.run(istore.db_set_whatsapp_account(
        pool, org_id="org-1", bot_id="bot-1",
        waba_id="waba-1", phone_number_id="pn-1", business_id="biz-1",
        customer_access_token="super-secret-token", token_expires_at=None,
        connection_status="connected", secret_key=main.cfg.secret_key,
    ))

    result = asyncio.run(main.whatsapp_embedded_status(bot_id="bot-1", user=_user(), pool=pool))

    assert result["connected"] is True
    assert result["connection_status"] == "connected"
    assert result["waba_id"] == "waba-1"
    assert result["has_access_token"] is True
    assert "customer_access_token" not in result
    assert "super-secret-token" not in str(result)


def test_status_lists_all_accounts_for_org():
    pool = FakePool(bots={"bot-1": "org-1", "bot-2": "org-1"})
    for bot_id, waba_id in (("bot-1", "waba-1"), ("bot-2", "waba-2")):
        asyncio.run(istore.db_set_whatsapp_account(
            pool, org_id="org-1", bot_id=bot_id,
            waba_id=waba_id, phone_number_id=f"pn-{bot_id}", business_id="biz-1",
            customer_access_token="tok", token_expires_at=None,
            connection_status="connected", secret_key=main.cfg.secret_key,
        ))

    result = asyncio.run(main.whatsapp_embedded_status(bot_id=None, user=_user(), pool=pool))

    assert {a["bot_id"] for a in result["accounts"]} == {"bot-1", "bot-2"}


def test_status_unknown_bot_for_org_returns_404():
    pool = FakePool(bots={"bot-1": "org-1"})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.whatsapp_embedded_status(bot_id="bot-1", user=_user(org_id="org-2"), pool=pool))
    assert exc.value.status_code == 404


def test_disconnect_clears_account_and_phone_mapping_and_unsubscribes(monkeypatch):
    pool = FakePool(bots={"bot-1": "org-1"})
    asyncio.run(istore.db_set_whatsapp_account(
        pool, org_id="org-1", bot_id="bot-1",
        waba_id="waba-1", phone_number_id="pn-1", business_id="biz-1",
        customer_access_token="super-secret-token", token_expires_at=None,
        connection_status="connected", secret_key=main.cfg.secret_key,
    ))
    asyncio.run(istore.db_set_meta_phone_mapping(pool, phone_number_id="pn-1", org_id="org-1", bot_id="bot-1"))

    unsub_calls = []

    async def fake_unsubscribe(**kwargs):
        unsub_calls.append(kwargs)
        return {"success": True, "data": {}}

    monkeypatch.setattr(main, "wa_unsubscribe_app_from_waba", fake_unsubscribe)

    result = asyncio.run(main.whatsapp_embedded_disconnect(
        main.WhatsAppEmbeddedDisconnectReq(bot_id="bot-1"), user=_user(), pool=pool,
    ))

    assert result["connection_status"] == "disconnected"
    assert ("org-1", "bot-1") not in pool.whatsapp_accounts
    assert "pn-1" not in pool.phone_map
    assert unsub_calls and unsub_calls[0]["waba_id"] == "waba-1"


def test_disconnect_without_connection_returns_404():
    pool = FakePool(bots={"bot-1": "org-1"})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.whatsapp_embedded_disconnect(
            main.WhatsAppEmbeddedDisconnectReq(bot_id="bot-1"), user=_user(), pool=pool,
        ))
    assert exc.value.status_code == 404


# ─────────────────────────────────────────────────────────────────
# 4) Tenant isolation: no shared/global token across two organizations
# ─────────────────────────────────────────────────────────────────

def test_two_tenants_have_fully_isolated_whatsapp_credentials(monkeypatch):
    pool = FakePool(bots={"bot-1": "org-1", "bot-2": "org-2"})

    async def fake_exchange(**kwargs):
        # masing-masing tenant menukar code-nya sendiri -> token sendiri
        token = "token-for-" + kwargs["code"]
        return {"success": True, "data": {"access_token": token}}

    async def fake_register(**kwargs):
        return {"success": True, "data": {}}

    async def fake_subscribe(**kwargs):
        return {"success": True, "data": {}}

    monkeypatch.setattr(main, "wa_exchange_code_for_token", fake_exchange)
    monkeypatch.setattr(main, "wa_register_phone_number", fake_register)
    monkeypatch.setattr(main, "wa_subscribe_app_to_waba", fake_subscribe)

    # Org 1 connects bot-1
    conn1 = asyncio.run(main.whatsapp_embedded_connect(bot_id="bot-1", user=_user("org-1"), pool=pool))
    asyncio.run(main.whatsapp_embedded_callback(
        _callback_body(conn1["state"], code="org1-code", waba_id="waba-org1", phone_number_id="pn-org1"),
        user=_user("org-1"), pool=pool,
    ))

    # Org 2 connects bot-2
    conn2 = asyncio.run(main.whatsapp_embedded_connect(bot_id="bot-2", user=_user("org-2"), pool=pool))
    asyncio.run(main.whatsapp_embedded_callback(
        _callback_body(conn2["state"], code="org2-code", waba_id="waba-org2", phone_number_id="pn-org2"),
        user=_user("org-2"), pool=pool,
    ))

    acc1 = asyncio.run(istore.db_get_whatsapp_account(pool, org_id="org-1", bot_id="bot-1", secret_key=main.cfg.secret_key))
    acc2 = asyncio.run(istore.db_get_whatsapp_account(pool, org_id="org-2", bot_id="bot-2", secret_key=main.cfg.secret_key))

    assert acc1["customer_access_token"] == "token-for-org1-code"
    assert acc2["customer_access_token"] == "token-for-org2-code"
    assert acc1["customer_access_token"] != acc2["customer_access_token"]
    assert acc1["waba_id"] != acc2["waba_id"]

    # Org 2 cannot read org 1's account even by guessing bot_id.
    cross = asyncio.run(istore.db_get_whatsapp_account(pool, org_id="org-2", bot_id="bot-1", secret_key=main.cfg.secret_key))
    assert cross is None

    # Org 1 cannot fetch status for org 2's bot (tenant isolation at endpoint).
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.whatsapp_embedded_status(bot_id="bot-2", user=_user("org-1"), pool=pool))
    assert exc.value.status_code == 404
