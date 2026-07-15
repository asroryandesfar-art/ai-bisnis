"""Enterprise SSO (OIDC) — validasi id_token, enkripsi secret, dan alur callback
(termasuk JIT provisioning) dengan IdP di-mock.

id_token ditandatangani RS256 pakai kunci RSA yang dibuat di test; JWKS publiknya
disuntik lewat monkeypatch get_jwks. Alur callback digerakkan via TestClient
dengan pool terprogram (FakePool) + discover/token-endpoint di-mock — tanpa
jaringan keluar & tanpa DB.
"""
import time
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from jose import jwk as jose_jwk, jwt as jose_jwt

import bn_platform.sso as sso
import main

ISSUER = "https://idp.example.com"
CLIENT_ID = "client-abc"
NONCE = "nonce-xyz"


def _keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()
    pub_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    pub_jwk = jose_jwk.construct(pub_pem, "RS256").to_dict()
    pub_jwk["kid"] = "k1"
    return priv_pem, {"keys": [pub_jwk]}


def _sign(priv_pem, **overrides):
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": CLIENT_ID, "iat": now, "exp": now + 3600,
              "nonce": NONCE, "email": "user@example.com", "sub": "idp-sub-1",
              "name": "Test User"}
    claims.update(overrides)
    return jose_jwt.encode(claims, priv_pem, algorithm="RS256", headers={"kid": "k1"})


# ── Enkripsi client_secret ──────────────────────────────────────────────
def test_secret_encrypt_roundtrip_and_ciphertext_differs():
    enc = sso.encrypt_secret("super-secret", "app-key")
    assert enc != "super-secret"                        # tersimpan terenkripsi
    assert sso.decrypt_secret(enc, "app-key") == "super-secret"


def test_decrypt_with_wrong_key_fails():
    enc = sso.encrypt_secret("s", "key-a")
    with pytest.raises(HTTPException):
        sso.decrypt_secret(enc, "key-b")


# ── Validasi id_token (signature + iss/aud + nonce) ─────────────────────
def test_validate_id_token_success(monkeypatch):
    priv, jwks = _keypair()
    async def fake_jwks(uri): return jwks
    monkeypatch.setattr(sso, "get_jwks", fake_jwks)
    token = _sign(priv)
    import asyncio
    claims = asyncio.run(sso.validate_id_token(
        token, jwks_uri="x", client_id=CLIENT_ID, issuer=ISSUER, nonce=NONCE))
    assert claims["email"] == "user@example.com" and claims["sub"] == "idp-sub-1"


def test_validate_id_token_rejects_bad_nonce(monkeypatch):
    priv, jwks = _keypair()
    async def fake_jwks(uri): return jwks
    monkeypatch.setattr(sso, "get_jwks", fake_jwks)
    import asyncio
    with pytest.raises(HTTPException) as ei:
        asyncio.run(sso.validate_id_token(
            _sign(priv), jwks_uri="x", client_id=CLIENT_ID, issuer=ISSUER, nonce="WRONG"))
    assert ei.value.status_code == 401


def test_validate_id_token_rejects_wrong_audience(monkeypatch):
    priv, jwks = _keypair()
    async def fake_jwks(uri): return jwks
    monkeypatch.setattr(sso, "get_jwks", fake_jwks)
    import asyncio
    with pytest.raises(HTTPException):
        asyncio.run(sso.validate_id_token(
            _sign(priv, aud="other-client"), jwks_uri="x", client_id=CLIENT_ID,
            issuer=ISSUER, nonce=NONCE))


# ── Callback end-to-end (FakePool + IdP mock) ───────────────────────────
class FakePool:
    def __init__(self, state_row, config_row, user_row=None):
        self.rows = {
            "FROM sso_login_state WHERE state": state_row,
            "FROM org_sso_config": config_row,
            "FROM users WHERE lower(email)": user_row,
        }
        self.executed = []

    async def fetchrow(self, sql, *a):
        for sub, val in self.rows.items():
            if sub in sql:
                return val
        return None

    async def fetchval(self, sql, *a):
        return None

    async def execute(self, sql, *a):
        self.executed.append((sql, a))
        return "OK"


def _wire(monkeypatch, priv, jwks, *, token_status=200):
    async def fake_discover(issuer):
        return {"authorization_endpoint": ISSUER + "/authorize",
                "token_endpoint": ISSUER + "/token", "jwks_uri": ISSUER + "/jwks",
                "issuer": ISSUER}
    async def fake_jwks(uri): return jwks
    monkeypatch.setattr(sso, "discover", fake_discover)
    monkeypatch.setattr(sso, "get_jwks", fake_jwks)

    signed = _sign(priv)

    class _Resp:
        status_code = token_status
        def json(self): return {"id_token": signed, "access_token": "at"}
    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, data=None): return _Resp()
    monkeypatch.setattr(sso.httpx, "AsyncClient", lambda *a, **k: _Client())


def _config_row(**over):
    row = {"org_id": str(uuid.uuid4()), "provider": "oidc", "issuer": ISSUER,
           "client_id": CLIENT_ID, "client_secret_enc": sso.encrypt_secret("s", main.cfg.secret_key),
           "allowed_domains": [], "jit_enabled": True, "default_role": "member", "enabled": True}
    row.update(over)
    return row


def _client(pool):
    main.app.dependency_overrides[main.get_pool] = lambda: pool
    return TestClient(main.app)


def _teardown():
    main.app.dependency_overrides.pop(main.get_pool, None)


def test_callback_jit_provisions_and_issues_session(monkeypatch):
    priv, jwks = _keypair()
    _wire(monkeypatch, priv, jwks)
    conf = _config_row()
    state = {"org_id": conf["org_id"], "nonce": NONCE, "redirect_uri": "https://app/auth/sso/callback"}
    pool = FakePool(state_row=state, config_row=conf, user_row=None)
    try:
        r = _client(pool).get("/auth/sso/callback?code=abc&state=s1", follow_redirects=False)
        assert r.status_code == 302
        assert "sso_token=" in r.headers["location"]              # sesi terbit
        assert any("INSERT INTO users" in sql for sql, _ in pool.executed)  # JIT provision
    finally:
        _teardown()


def test_callback_rejects_foreign_domain(monkeypatch):
    priv, jwks = _keypair()
    _wire(monkeypatch, priv, jwks)
    conf = _config_row(allowed_domains=["corp.com"])              # user@example.com tak diizinkan
    state = {"org_id": conf["org_id"], "nonce": NONCE, "redirect_uri": "https://app/cb"}
    pool = FakePool(state_row=state, config_row=conf, user_row=None)
    try:
        r = _client(pool).get("/auth/sso/callback?code=abc&state=s1", follow_redirects=False)
        assert r.status_code == 302
        assert "sso_error=" in r.headers["location"]
        assert not any("INSERT INTO users" in sql for sql, _ in pool.executed)
    finally:
        _teardown()


def test_callback_rejects_unknown_state(monkeypatch):
    priv, jwks = _keypair()
    _wire(monkeypatch, priv, jwks)
    pool = FakePool(state_row=None, config_row=_config_row(), user_row=None)  # state tak ada
    try:
        r = _client(pool).get("/auth/sso/callback?code=abc&state=nope", follow_redirects=False)
        assert r.status_code == 302 and "sso_error=" in r.headers["location"]
    finally:
        _teardown()


def test_sso_routes_present():
    paths = {getattr(r, "path", "") for r in main.app.routes}
    assert "/auth/sso/{org_slug}/login" in paths
    assert "/auth/sso/callback" in paths
    assert "/api/sso/config" in paths
