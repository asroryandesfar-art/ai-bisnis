"""Tenant-scoped Meta OAuth for Facebook Pages and Instagram Business accounts."""

import asyncio
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Awaitable, Callable
from urllib.parse import urlencode

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from integrations_store import (
    db_clear_integration,
    db_get_integration,
    db_pop_oauth_state,
    db_set_integration,
    db_set_oauth_state,
    decrypt_dict,
)

from .channel_manager import ChannelManager
from .channels import ChannelType
from .config import cfg
from .security import write_audit_log

logger = logging.getLogger("bn_platform.meta_oauth")
GetCurrentUser = Callable[..., Awaitable[dict]]
GetPool = Callable[..., Awaitable[asyncpg.Pool]]
RouteInboundMessage = Callable[..., Awaitable[str]]
META_KEY = "meta_oauth"
META_SCOPES = (
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_metadata",
    "pages_messaging",
    "instagram_basic",
    "instagram_manage_messages",
    "business_management",
)


class MetaOAuthStartReq(BaseModel):
    bot_id: str
    channel: str = Field(default="facebook", pattern="^(facebook|instagram)$")


class MetaAssetSelectReq(BaseModel):
    bot_id: str
    page_id: str
    channels: list[str] = Field(default_factory=lambda: ["facebook"], min_length=1, max_length=2)
    instagram_id: str | None = None


class MetaDisconnectReq(BaseModel):
    channels: list[str] = Field(default_factory=lambda: ["facebook", "instagram"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_after(seconds: int | str | None) -> str | None:
    if not seconds:
        return None
    try:
        return (_now() + timedelta(seconds=int(seconds))).isoformat()
    except (TypeError, ValueError):
        return None


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


async def _graph(method: str, path: str, *, token: str | None = None, params: dict | None = None) -> dict:
    url = f"https://graph.facebook.com/{cfg.meta_api_version.strip() or 'v21.0'}/{path.lstrip('/')}"
    query = dict(params or {})
    if token:
        query["access_token"] = token
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.request(method, url, params=query)
    if response.status_code >= 400:
        raise RuntimeError(f"Meta Graph API gagal ({response.status_code}): {response.text[:500]}")
    return response.json() if response.content else {}


async def exchange_code(code: str, redirect_uri: str) -> dict:
    return await _graph("GET", "oauth/access_token", params={
        "client_id": cfg.meta_app_id,
        "client_secret": cfg.meta_app_secret,
        "redirect_uri": redirect_uri,
        "code": code,
    })


async def exchange_long_lived_token(token: str) -> dict:
    return await _graph("GET", "oauth/access_token", params={
        "grant_type": "fb_exchange_token",
        "client_id": cfg.meta_app_id,
        "client_secret": cfg.meta_app_secret,
        "fb_exchange_token": token,
    })


async def fetch_pages(user_token: str) -> list[dict]:
    data = await _graph("GET", "me/accounts", token=user_token, params={
        "fields": "id,name,access_token,instagram_business_account{id,username,name}",
        "limit": 200,
    })
    pages = []
    for raw in data.get("data") or []:
        instagram = raw.get("instagram_business_account") or None
        pages.append({
            "id": str(raw.get("id") or ""),
            "name": raw.get("name") or "Facebook Page",
            "access_token": raw.get("access_token") or "",
            "instagram": {
                "id": str(instagram.get("id") or ""),
                "username": instagram.get("username") or instagram.get("name") or "Instagram Business",
            } if instagram and instagram.get("id") else None,
        })
    return [page for page in pages if page["id"] and page["access_token"]]


async def subscribe_page(page_id: str, page_token: str) -> None:
    await _graph("POST", f"{page_id}/subscribed_apps", token=page_token, params={
        "subscribed_fields": "messages,messaging_postbacks,message_reads",
    })


def public_meta_account(account: dict) -> dict:
    selected = account.get("selected") or {}
    return {
        "connected": bool(account.get("user_access_token")),
        "status": account.get("status") or "disconnected",
        "token_expires_at": account.get("token_expires_at"),
        "pages": [{
            "id": page.get("id"),
            "name": page.get("name"),
            "instagram": page.get("instagram"),
        } for page in account.get("pages") or []],
        "selected": selected,
        "bot_id": account.get("bot_id"),
        "updated_at": account.get("updated_at"),
        "last_refresh_at": account.get("last_refresh_at"),
    }


async def _sync_selected_channel_tokens(pool: asyncpg.Pool, org_id: str, account: dict) -> None:
    selected = account.get("selected") or {}
    pages = {str(page.get("id")): page for page in account.get("pages") or []}
    for channel in ("facebook", "instagram"):
        choice = selected.get(channel) or {}
        page = pages.get(str(choice.get("page_id") or ""))
        if not page or not page.get("access_token"):
            continue
        if channel == "facebook":
            external_id = str(choice.get("page_id") or "")
            credentials = {"access_token": page["access_token"], "page_id": external_id}
        else:
            external_id = str(choice.get("instagram_id") or "")
            credentials = {"access_token": page["access_token"], "instagram_account_id": external_id}
        if not external_id:
            continue
        encrypted = ChannelManager._encrypt_credentials(credentials)
        await pool.execute(
            """UPDATE channel_connections cc SET credentials=$4, updated_at=NOW()
               FROM channels c WHERE cc.channel_id=c.id AND cc.tenant_id=$1
               AND c.channel_type=$2 AND cc.external_id=$3""",
            org_id, channel, external_id, json.dumps(encrypted),
        )
        await pool.execute(
            """UPDATE channel_accounts SET credentials=$4, last_sync_at=NOW()
               WHERE org_id=$1 AND channel_type=$2 AND external_id=$3""",
            org_id, channel, external_id, json.dumps(encrypted),
        )


async def refresh_meta_account(pool: asyncpg.Pool, org_id: str, *, force: bool = False) -> dict:
    account = await db_get_integration(pool, org_id=org_id, key=META_KEY, secret_key=cfg.secret_key)
    token = str(account.get("user_access_token") or "")
    if not token:
        return account
    expires_at = _parse_time(account.get("token_expires_at"))
    if not force and expires_at and expires_at > _now() + timedelta(days=7):
        return account
    try:
        refreshed = await exchange_long_lived_token(token)
        new_token = refreshed.get("access_token") or token
        account["user_access_token"] = new_token
        account["token_expires_at"] = _iso_after(refreshed.get("expires_in")) or account.get("token_expires_at")
        account["pages"] = await fetch_pages(new_token)
        account["status"] = "connected"
        account["last_refresh_at"] = _now().isoformat()
        account["updated_at"] = _now().isoformat()
        await _sync_selected_channel_tokens(pool, org_id, account)
    except Exception as exc:
        account["status"] = "reauth_required" if expires_at and expires_at <= _now() else "refresh_error"
        account["refresh_error"] = str(exc)[:500]
        logger.warning("Meta token refresh failed org=%s: %s", org_id, exc)
    await db_set_integration(pool, org_id=org_id, key=META_KEY, value=account, secret_key=cfg.secret_key)
    return account


async def refresh_due_meta_accounts(pool: asyncpg.Pool) -> int:
    rows = await pool.fetch("SELECT org_id, data_enc FROM org_integrations WHERE key=$1", META_KEY)
    refreshed = 0
    for row in rows:
        account = decrypt_dict(cfg.secret_key, row["data_enc"] or "")
        expires_at = _parse_time(account.get("token_expires_at"))
        if not expires_at or expires_at > _now() + timedelta(days=7):
            continue
        await refresh_meta_account(pool, str(row["org_id"]), force=True)
        refreshed += 1
    return refreshed


async def meta_refresh_loop(stop_event: asyncio.Event, get_pool: GetPool, interval_seconds: int = 21600) -> None:
    while not stop_event.is_set():
        try:
            pool = await get_pool()
            await refresh_due_meta_accounts(pool)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Meta OAuth refresh loop failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(300, interval_seconds))
        except asyncio.TimeoutError:
            pass


async def ensure_meta_asset_available(pool: asyncpg.Pool, *, org_id: str, channel: str, external_id: str) -> None:
    existing = await pool.fetchrow(
        """SELECT mar.org_id, cc.status FROM meta_asset_routes mar
           LEFT JOIN channel_connections cc ON cc.id=mar.connection_id
           WHERE mar.channel_type=$1 AND mar.external_id=$2""",
        channel, external_id,
    )
    if existing and str(existing["org_id"]) != org_id and existing.get("status") == "connected":
        raise ValueError("Aset Meta ini sudah terhubung ke tenant lain")


async def claim_meta_asset(pool: asyncpg.Pool, *, org_id: str, bot_id: str, channel: str, external_id: str, connection_id: str) -> None:
    await ensure_meta_asset_available(pool, org_id=org_id, channel=channel, external_id=external_id)
    await pool.execute(
        """INSERT INTO meta_asset_routes(channel_type, external_id, org_id, bot_id, connection_id, updated_at)
           VALUES($1,$2,$3,$4,$5,NOW())
           ON CONFLICT (channel_type, external_id) DO UPDATE SET
             org_id=EXCLUDED.org_id, bot_id=EXCLUDED.bot_id,
             connection_id=EXCLUDED.connection_id, updated_at=NOW()""",
        channel, external_id, org_id, bot_id, connection_id,
    )


def build_meta_oauth_router(
    *,
    get_pool: GetPool,
    get_current_user: GetCurrentUser,
    require_permission,
    route_inbound_message: RouteInboundMessage | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/integrations/meta/oauth", tags=["meta-oauth"])

    def manager(pool: asyncpg.Pool) -> ChannelManager:
        return ChannelManager(pool, route_inbound_message=route_inbound_message, app_url=cfg.app_url)

    @router.post("/start")
    async def start_oauth(
        body: MetaOAuthStartReq,
        user: Annotated[dict, Depends(require_permission("settings.manage"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        if not cfg.meta_app_id or not cfg.meta_app_secret:
            raise HTTPException(400, "META_APP_ID / META_APP_SECRET belum dikonfigurasi")
        if not cfg.secret_key or cfg.secret_key == "change-me-in-production":
            raise HTTPException(400, "SECRET_KEY production wajib dikonfigurasi sebelum Meta OAuth diaktifkan")
        if not cfg.channel_encryption_key:
            raise HTTPException(400, "CHANNEL_ENCRYPTION_KEY wajib dikonfigurasi sebelum Meta OAuth diaktifkan")
        bot = await pool.fetchrow("SELECT id FROM bots WHERE id=$1 AND org_id=$2", body.bot_id, user["org_id"])
        if not bot:
            raise HTTPException(404, "Bot tidak ditemukan untuk tenant ini")
        redirect_uri = cfg.meta_oauth_redirect_uri.strip() or f"{cfg.app_url.rstrip('/')}/api/integrations/meta/oauth/callback"
        state = secrets.token_urlsafe(32)
        context = json.dumps({"bot_id": body.bot_id, "channel": body.channel, "redirect_uri": redirect_uri})
        await db_set_oauth_state(pool, provider="meta_oauth", state=state, org_id=str(user["org_id"]), redirect_uri=context)
        auth_url = "https://www.facebook.com/dialog/oauth?" + urlencode({
            "client_id": cfg.meta_app_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": ",".join(META_SCOPES),
            "response_type": "code",
        })
        return {"auth_url": auth_url, "state": state}

    @router.get("/callback", include_in_schema=False)
    async def oauth_callback(
        code: str | None = Query(None),
        state: str | None = Query(None),
        error: str | None = Query(None),
        error_reason: str | None = Query(None),
        error_code: str | None = Query(None),
        error_message: str | None = Query(None),
        error_description: str | None = Query(None),
        pool: asyncpg.Pool = Depends(get_pool),
    ):
        dashboard = f"{cfg.app_url.rstrip('/')}/dashboard"
        # Meta mengirim parameter error → otorisasi ditolak / dibatalkan pengguna.
        # Tampilkan pesan error tanpa memaksa membaca state (jangan 422).
        if error or error_reason or error_code or error_message:
            logger.warning(
                "Meta OAuth authorization error: error=%s error_code=%s reason=%s message=%s description=%s",
                error, error_code, error_reason, error_message, error_description,
            )
            reason = error_message or error_reason or error_description or error or "authorization_error"
            return RedirectResponse(
                f"{dashboard}?{urlencode({'meta_oauth': 'error', 'meta_error': reason})}#channels"
            )
        # Tidak ada code → alur dibatalkan tanpa error eksplisit dari Meta.
        if not code:
            logger.info("Meta OAuth callback tanpa code (kemungkinan dibatalkan pengguna)")
            return RedirectResponse(f"{dashboard}?meta_oauth=cancelled#channels")
        # code ada tapi state tidak ada → tidak bisa memvalidasi CSRF/state; jangan 422.
        if not state:
            logger.warning("Meta OAuth callback menerima code tanpa parameter state")
            return RedirectResponse(f"{dashboard}?meta_oauth=missing_state#channels")
        # code + state ada → validasi state, lalu tukar code menjadi access token.
        org_id, raw_context = await db_pop_oauth_state(pool, provider="meta_oauth", state=state)
        if not org_id or not raw_context:
            return RedirectResponse(f"{dashboard}?meta_oauth=invalid_state#channels")
        try:
            context = json.loads(raw_context)
        except json.JSONDecodeError:
            context = {
                "bot_id": raw_context,
                "redirect_uri": cfg.meta_oauth_redirect_uri.strip()
                or f"{cfg.app_url.rstrip('/')}/api/integrations/meta/oauth/callback",
            }
        try:
            token_data = await exchange_code(code, context["redirect_uri"])
            short_token = token_data.get("access_token") or ""
            long_data = await exchange_long_lived_token(short_token)
            user_token = long_data.get("access_token") or short_token
            pages = await fetch_pages(user_token)
            account = {
                "status": "pending_selection",
                "user_access_token": user_token,
                "token_expires_at": _iso_after(long_data.get("expires_in") or token_data.get("expires_in")),
                "pages": pages,
                "selected": {},
                "bot_id": context.get("bot_id"),
                "updated_at": _now().isoformat(),
                "last_refresh_at": _now().isoformat(),
            }
            await db_set_integration(pool, org_id=org_id, key=META_KEY, value=account, secret_key=cfg.secret_key)
            return RedirectResponse(f"{dashboard}?meta_oauth=success&meta_channel={context.get('channel','facebook')}#channels")
        except Exception:
            logger.exception("Meta OAuth callback failed org=%s", org_id)
            return RedirectResponse(f"{dashboard}?meta_oauth=error#channels")

    @router.get("/status")
    async def oauth_status(
        user: Annotated[dict, Depends(require_permission("settings.manage"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = str(user["org_id"])
        account = await db_get_integration(pool, org_id=org_id, key=META_KEY, secret_key=cfg.secret_key)
        result = public_meta_account(account)
        rows = await pool.fetch(
            """SELECT bot_id, waba_id, phone_number_id, business_id, connection_status, token_expires_at
               FROM whatsapp_embedded_accounts WHERE org_id=$1 ORDER BY updated_at DESC""",
            org_id,
        )
        result["whatsapp_accounts"] = [dict(row) for row in rows]
        return result

    @router.post("/select", status_code=status.HTTP_201_CREATED)
    async def select_assets(
        body: MetaAssetSelectReq,
        user: Annotated[dict, Depends(require_permission("settings.manage"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = str(user["org_id"])
        bot = await pool.fetchrow("SELECT id FROM bots WHERE id=$1 AND org_id=$2", body.bot_id, user["org_id"])
        if not bot:
            raise HTTPException(404, "Bot tidak ditemukan untuk tenant ini")
        account = await db_get_integration(pool, org_id=org_id, key=META_KEY, secret_key=cfg.secret_key)
        page = next((item for item in account.get("pages") or [] if str(item.get("id")) == body.page_id), None)
        if not page:
            raise HTTPException(400, "Facebook Page tidak tersedia pada akun Meta ini")
        requested = set(body.channels)
        if not requested.issubset({"facebook", "instagram"}):
            raise HTTPException(400, "Channel Meta tidak valid")
        instagram = page.get("instagram") or {}
        if "instagram" in requested and (not instagram.get("id") or str(instagram.get("id")) != str(body.instagram_id or instagram.get("id"))):
            raise HTTPException(400, "Instagram Business tidak tertaut ke Page yang dipilih")
        page_token = page.get("access_token") or ""
        if "facebook" in requested:
            await ensure_meta_asset_available(pool, org_id=org_id, channel="facebook", external_id=page["id"])
        if "instagram" in requested:
            await ensure_meta_asset_available(pool, org_id=org_id, channel="instagram", external_id=str(instagram["id"]))
        await subscribe_page(page["id"], page_token)
        connections = []
        if "facebook" in requested:
            facebook_connection = await manager(pool).connect_channel(
                tenant_id=org_id, bot_id=body.bot_id, channel=ChannelType.FACEBOOK,
                display_name=page.get("name") or "Facebook Page", external_id=page["id"],
                credentials={"access_token": page_token, "page_id": page["id"]},
                config={"oauth_managed": True, "webhook_url": f"{cfg.app_url.rstrip('/')}/webhooks/meta"},
            )
            await claim_meta_asset(pool, org_id=org_id, bot_id=body.bot_id, channel="facebook", external_id=page["id"], connection_id=facebook_connection["id"])
            connections.append(facebook_connection)
        if "instagram" in requested:
            instagram_connection = await manager(pool).connect_channel(
                tenant_id=org_id, bot_id=body.bot_id, channel=ChannelType.INSTAGRAM,
                display_name=instagram.get("username") or "Instagram Business", external_id=str(instagram["id"]),
                credentials={"access_token": page_token, "instagram_account_id": str(instagram["id"])},
                config={"oauth_managed": True, "page_id": page["id"], "webhook_url": f"{cfg.app_url.rstrip('/')}/webhooks/meta"},
            )
            await claim_meta_asset(pool, org_id=org_id, bot_id=body.bot_id, channel="instagram", external_id=str(instagram["id"]), connection_id=instagram_connection["id"])
            connections.append(instagram_connection)
        account["status"] = "connected"
        selected = dict(account.get("selected") or {})
        if "facebook" in requested:
            selected["facebook"] = {
                "page_id": page["id"], "page_name": page.get("name"), "bot_id": body.bot_id,
            }
        if "instagram" in requested:
            selected["instagram"] = {
                "page_id": page["id"], "page_name": page.get("name"),
                "instagram_id": instagram.get("id"), "instagram_username": instagram.get("username"),
                "bot_id": body.bot_id,
            }
        account["selected"] = selected
        account["bot_id"] = body.bot_id
        account["updated_at"] = _now().isoformat()
        await db_set_integration(pool, org_id=org_id, key=META_KEY, value=account, secret_key=cfg.secret_key)
        await write_audit_log(pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"), action="create", resource_type="meta_oauth", resource_id=page["id"], metadata={"channels": sorted(requested), "bot_id": body.bot_id})
        return {"message": "Meta assets connected", "connections": connections, "meta": public_meta_account(account)}

    @router.post("/refresh")
    async def refresh_token(
        user: Annotated[dict, Depends(require_permission("settings.manage"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        account = await refresh_meta_account(pool, str(user["org_id"]), force=True)
        return public_meta_account(account)

    @router.post("/disconnect")
    async def disconnect_meta(
        body: MetaDisconnectReq,
        user: Annotated[dict, Depends(require_permission("settings.manage"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = str(user["org_id"])
        requested = set(body.channels)
        for connection in await manager(pool).list_connections(org_id):
            if connection.get("channel_type") in requested:
                await manager(pool).disconnect_channel(tenant_id=org_id, connection_id=connection["id"])
        await db_clear_integration(pool, org_id=org_id, key=META_KEY)
        await write_audit_log(pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"), action="delete", resource_type="meta_oauth", metadata={"channels": sorted(requested)})
        return {"ok": True}

    return router
