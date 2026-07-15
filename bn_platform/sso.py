"""Enterprise SSO via OpenID Connect (OIDC).

Per-organisasi: admin mengonfigurasi issuer + client_id/secret IdP mereka
(Okta, Azure AD/Entra, Google Workspace, Auth0, …). Alur authorization-code:

    /auth/sso/{org_slug}/login  → redirect ke IdP (state+nonce anti-CSRF/replay)
    /auth/sso/callback          → tukar code→token, VALIDASI id_token (JWKS/RS256,
                                   iss/aud/exp/nonce), cek domain, JIT provisioning,
                                   terbitkan sesi BotNesia (create_token + start_session)

Prinsip:
- SSO OPSIONAL: login password tetap jalan; ini jalur tambahan.
- JIT provisioning: user baru dibuat otomatis bila domain email cocok allowed_domains.
- client_secret disimpan TERENKRIPSI (Fernet, kunci diturunkan dari SECRET_KEY).
- Tidak memakai `from __future__ import annotations` (aturan repo: FastAPI router).
"""
import base64
import hashlib
import secrets
import time
import uuid
from typing import Annotated, Awaitable, Callable, Optional
from urllib.parse import quote

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from jose import jwt as jose_jwt
from jose.exceptions import JWTError
from pydantic import BaseModel, Field

# TTL cache sederhana (proses tunggal). Discovery & JWKS jarang berubah.
_DISCOVERY_TTL = 3600
_JWKS_TTL = 3600
_STATE_TTL = 600            # state OIDC valid 10 menit
_discovery_cache: dict = {}
_jwks_cache: dict = {}


# ── Enkripsi client_secret ──────────────────────────────────────────────
def _fernet(secret_key: str) -> Fernet:
    """Kunci Fernet 32-byte diturunkan deterministik dari SECRET_KEY aplikasi."""
    digest = hashlib.sha256((secret_key or "").encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str, secret_key: str) -> str:
    return _fernet(secret_key).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str, secret_key: str) -> str:
    try:
        return _fernet(secret_key).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            "Gagal mendekripsi kredensial SSO") from exc


# ── OIDC discovery + JWKS ───────────────────────────────────────────────
async def discover(issuer: str) -> dict:
    """Ambil dokumen discovery OIDC (.well-known/openid-configuration), di-cache."""
    issuer = (issuer or "").rstrip("/")
    hit = _discovery_cache.get(issuer)
    if hit and time.time() - hit["ts"] < _DISCOVERY_TTL:
        return hit["doc"]
    url = f"{issuer}/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            doc = resp.json()
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"Gagal memuat konfigurasi OIDC dari issuer: {exc}") from exc
    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri", "issuer"):
        if not doc.get(field):
            raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                                f"Dokumen discovery OIDC tidak lengkap (tanpa {field})")
    _discovery_cache[issuer] = {"doc": doc, "ts": time.time()}
    return doc


async def get_jwks(jwks_uri: str) -> dict:
    hit = _jwks_cache.get(jwks_uri)
    if hit and time.time() - hit["ts"] < _JWKS_TTL:
        return hit["jwks"]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(jwks_uri)
            resp.raise_for_status()
            jwks = resp.json()
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"Gagal memuat JWKS IdP: {exc}") from exc
    _jwks_cache[jwks_uri] = {"jwks": jwks, "ts": time.time()}
    return jwks


def _select_jwk(jwks: dict, kid: Optional[str]) -> dict:
    keys = (jwks or {}).get("keys") or []
    if kid:
        for k in keys:
            if k.get("kid") == kid:
                return k
    if len(keys) == 1:               # IdP tanpa kid & satu kunci
        return keys[0]
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Kunci penanda id_token tidak ditemukan di JWKS")


async def validate_id_token(id_token: str, *, jwks_uri: str, client_id: str,
                            issuer: str, nonce: str) -> dict:
    """Verifikasi signature (JWKS/RS256) + iss/aud/exp + nonce. Return claims."""
    try:
        header = jose_jwt.get_unverified_header(id_token)
    except JWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "id_token tidak valid") from exc
    jwk = _select_jwk(await get_jwks(jwks_uri), header.get("kid"))
    alg = header.get("alg", "RS256")
    if alg not in ("RS256", "RS384", "RS512", "ES256"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Algoritma id_token tidak didukung: {alg}")
    try:
        claims = jose_jwt.decode(
            id_token, jwk, algorithms=[alg], audience=client_id,
            issuer=issuer.rstrip("/"), options={"verify_at_hash": False},
        )
    except JWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Validasi id_token gagal: {exc}") from exc
    if not secrets.compare_digest(str(claims.get("nonce") or ""), str(nonce or "")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nonce id_token tidak cocok (kemungkinan replay)")
    return claims


# ── Helper repo config ──────────────────────────────────────────────────
async def get_sso_config(pool, org_id: str) -> Optional[dict]:
    row = await pool.fetchrow("SELECT * FROM org_sso_config WHERE org_id=$1", org_id)
    return dict(row) if row else None


def _base_url(request: Request, public_base_url: str) -> str:
    if public_base_url:
        return public_base_url.rstrip("/")
    return str(request.base_url).rstrip("/")


# ── Request models ──────────────────────────────────────────────────────
class SsoConfigReq(BaseModel):
    issuer:          str
    client_id:       str
    client_secret:   Optional[str] = None          # None saat update tanpa ganti secret
    allowed_domains: list[str] = Field(default_factory=list)
    jit_enabled:     bool = True
    default_role:    str = Field(default="member", pattern="^(member|admin)$")
    enabled:         bool = False


def build_sso_router(
    *,
    get_pool: Callable[..., Awaitable],
    get_current_user: Callable[..., Awaitable[dict]],
    require_permission: Callable[[str], Callable],
    create_token: Callable[..., str],
    start_session: Callable[..., Awaitable],
    hash_password: Callable[[str], str],
    cfg,                       # main Settings: secret_key
    platform_cfg,              # PlatformSettings: sso_enabled, public_base_url
    logger,
) -> APIRouter:
    router = APIRouter()

    def _require_enabled():
        if not platform_cfg.sso_enabled:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "SSO dinonaktifkan di platform ini")

    # ── Login: mulai alur OIDC ──────────────────────────────────────────
    @router.get("/auth/sso/{org_slug}/login")
    async def sso_login(org_slug: str, request: Request,
                        pool: Annotated[object, Depends(get_pool)]):
        _require_enabled()
        org = await pool.fetchrow("SELECT id FROM organizations WHERE slug=$1", org_slug)
        if not org:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisasi tidak ditemukan")
        conf = await get_sso_config(pool, str(org["id"]))
        if not conf or not conf["enabled"]:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "SSO belum diaktifkan untuk organisasi ini")
        doc = await discover(conf["issuer"])
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        redirect_uri = f"{_base_url(request, platform_cfg.public_base_url)}/auth/sso/callback"
        await pool.execute(
            "INSERT INTO sso_login_state (state, org_id, nonce, redirect_uri) VALUES ($1,$2,$3,$4)",
            state, org["id"], nonce, redirect_uri,
        )
        params = {
            "response_type": "code",
            "client_id": conf["client_id"],
            "redirect_uri": redirect_uri,
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
        }
        auth_url = httpx.URL(doc["authorization_endpoint"], params=params)
        return RedirectResponse(str(auth_url), status_code=status.HTTP_302_FOUND)

    # ── Callback: tukar code, validasi, provisioning, sesi ──────────────
    @router.get("/auth/sso/callback")
    async def sso_callback(request: Request, pool: Annotated[object, Depends(get_pool)],
                           code: str = "", state: str = "", error: str = ""):
        _require_enabled()
        base = _base_url(request, platform_cfg.public_base_url)

        def _fail(msg: str):
            # Balik ke SPA dengan pesan; jangan bocorkan detail teknis di URL.
            return RedirectResponse(f"{base}/ui/?sso_error={quote(msg)}",
                                    status_code=status.HTTP_302_FOUND)

        if error:
            return _fail("Login SSO dibatalkan di penyedia identitas")
        # Ambil & KONSUMSI state (sekali pakai). Bersihkan state basi sekalian.
        await pool.execute("DELETE FROM sso_login_state WHERE created_at < NOW() - ($1 || ' seconds')::interval",
                           str(_STATE_TTL))
        st = await pool.fetchrow("SELECT * FROM sso_login_state WHERE state=$1", state)
        if not st:
            return _fail("Sesi login SSO kedaluwarsa atau tidak valid")
        await pool.execute("DELETE FROM sso_login_state WHERE state=$1", state)
        if not code:
            return _fail("Kode otorisasi tidak diterima dari IdP")

        org_id = str(st["org_id"])
        conf = await get_sso_config(pool, org_id)
        if not conf or not conf["enabled"]:
            return _fail("SSO tidak aktif")
        try:
            doc = await discover(conf["issuer"])
            client_secret = decrypt_secret(conf["client_secret_enc"], cfg.secret_key)
            async with httpx.AsyncClient(timeout=10.0) as client:
                token_resp = await client.post(doc["token_endpoint"], data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": st["redirect_uri"],
                    "client_id": conf["client_id"],
                    "client_secret": client_secret,
                })
            if token_resp.status_code != 200:
                logger.warning("SSO token exchange gagal org=%s status=%s", org_id, token_resp.status_code)
                return _fail("Penukaran token dengan IdP gagal")
            tok = token_resp.json()
            id_token = tok.get("id_token")
            if not id_token:
                return _fail("IdP tidak mengembalikan id_token")
            claims = await validate_id_token(
                id_token, jwks_uri=doc["jwks_uri"], client_id=conf["client_id"],
                issuer=doc.get("issuer", conf["issuer"]), nonce=st["nonce"],
            )
        except HTTPException as exc:
            logger.warning("SSO callback ditolak org=%s: %s", org_id, exc.detail)
            return _fail("Verifikasi identitas gagal")
        except Exception:
            logger.exception("SSO callback error org=%s", org_id)
            return _fail("Terjadi kesalahan saat memproses login SSO")

        email = str(claims.get("email") or "").strip().lower()
        sub = str(claims.get("sub") or "")
        full_name = claims.get("name") or claims.get("preferred_username") or email.split("@")[0]
        if not email:
            return _fail("IdP tidak mengembalikan email")

        # Domain allowlist (bila diisi) — cegah akun luar organisasi.
        domains = list(conf["allowed_domains"] or [])
        if domains and email.split("@")[-1] not in [d.lower() for d in domains]:
            return _fail("Domain email Anda tidak diizinkan untuk organisasi ini")

        # Pemetaan user: link yang sudah ada / JIT provisioning.
        existing = await pool.fetchrow(
            "SELECT id, org_id, is_active FROM users WHERE lower(email)=$1", email)
        if existing:
            if str(existing["org_id"]) != org_id:
                return _fail("Email ini sudah terdaftar di organisasi lain")
            if not existing["is_active"]:
                return _fail("Akun dinonaktifkan")
            user_id = str(existing["id"])
            await pool.execute(
                "UPDATE users SET auth_provider='oidc', external_id=COALESCE(external_id,$2), last_login_at=NOW() WHERE id=$1",
                existing["id"], sub or None,
            )
        else:
            if not conf["jit_enabled"]:
                return _fail("Akun belum diundang ke organisasi ini")
            user_id = str(uuid.uuid4())
            # Hash acak tak-terpakai supaya kolom NOT NULL terpenuhi & login
            # password mustahil untuk user SSO.
            unusable = hash_password(secrets.token_urlsafe(32))
            try:
                await pool.execute(
                    """INSERT INTO users (id, org_id, email, hashed_password, full_name, role,
                                          auth_provider, external_id, last_login_at)
                       VALUES ($1,$2,$3,$4,$5,$6,'oidc',$7,NOW())""",
                    user_id, org_id, email, unusable, full_name,
                    conf["default_role"], sub or None,
                )
            except Exception:
                logger.exception("SSO JIT provisioning gagal org=%s email=%s", org_id, email)
                return _fail("Gagal membuat akun SSO")

        session_id = await start_session(pool, user_id=user_id, org_id=org_id,
                                         email=email, request=request, action="login")
        token = create_token(user_id, org_id, session_id)
        return RedirectResponse(f"{base}/ui/?sso_token={token}", status_code=status.HTTP_302_FOUND)

    # ── Admin: konfigurasi SSO organisasi ───────────────────────────────
    def _mask(conf: dict) -> dict:
        return {
            "provider": conf["provider"], "issuer": conf["issuer"],
            "client_id": conf["client_id"], "has_secret": bool(conf["client_secret_enc"]),
            "allowed_domains": list(conf["allowed_domains"] or []),
            "jit_enabled": conf["jit_enabled"], "default_role": conf["default_role"],
            "enabled": conf["enabled"],
        }

    @router.get("/api/sso/config")
    async def get_config(user: Annotated[dict, Depends(get_current_user)],
                         pool: Annotated[object, Depends(get_pool)]):
        conf = await get_sso_config(pool, user["org_id"])
        return {"configured": bool(conf), "config": _mask(conf) if conf else None,
                "sso_enabled": platform_cfg.sso_enabled}

    @router.put("/api/sso/config")
    async def put_config(
        body: SsoConfigReq,
        user: Annotated[dict, Depends(require_permission("settings.manage"))],
        pool: Annotated[object, Depends(get_pool)],
    ):
        _require_enabled()
        existing = await get_sso_config(pool, user["org_id"])
        # Secret wajib saat pertama kali; saat update boleh kosong (pertahankan lama).
        if body.client_secret:
            secret_enc = encrypt_secret(body.client_secret, cfg.secret_key)
        elif existing:
            secret_enc = existing["client_secret_enc"]
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "client_secret wajib diisi saat konfigurasi awal")
        domains = [d.strip().lower() for d in body.allowed_domains if d.strip()]
        await pool.execute(
            """INSERT INTO org_sso_config
                   (org_id, provider, issuer, client_id, client_secret_enc,
                    allowed_domains, jit_enabled, default_role, enabled, updated_at)
               VALUES ($1,'oidc',$2,$3,$4,$5,$6,$7,$8,NOW())
               ON CONFLICT (org_id) DO UPDATE SET
                   issuer=EXCLUDED.issuer, client_id=EXCLUDED.client_id,
                   client_secret_enc=EXCLUDED.client_secret_enc,
                   allowed_domains=EXCLUDED.allowed_domains, jit_enabled=EXCLUDED.jit_enabled,
                   default_role=EXCLUDED.default_role, enabled=EXCLUDED.enabled, updated_at=NOW()""",
            user["org_id"], body.issuer.strip(), body.client_id.strip(), secret_enc,
            domains, body.jit_enabled, body.default_role, body.enabled,
        )
        conf = await get_sso_config(pool, user["org_id"])
        return {"ok": True, "config": _mask(conf)}

    @router.delete("/api/sso/config")
    async def delete_config(
        user: Annotated[dict, Depends(require_permission("settings.manage"))],
        pool: Annotated[object, Depends(get_pool)],
    ):
        _require_enabled()
        await pool.execute("DELETE FROM org_sso_config WHERE org_id=$1", user["org_id"])
        return {"ok": True}

    return router
