"""Omni Channel Phase 1: one tenant-safe manager for WhatsApp, Telegram, Website Chat, Instagram, and Facebook."""

import hashlib
import hmac
import json
import logging
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from .channel_manager import ChannelManager
from .channels import ChannelType
from .config import cfg as platform_cfg
from .security import write_audit_log

logger = logging.getLogger("bn_platform.omnichannel")
GetCurrentUser = Callable[..., Awaitable[dict]]
GetPool = Callable[..., Awaitable[asyncpg.Pool]]

# Channel yang webhook-nya datang dari Meta Graph API -- diverifikasi lewat
# X-Hub-Signature-256 (App Secret yang sama dengan main.py's /webhooks/meta),
# bukan token/secret per-koneksi seperti Telegram.
_META_CHANNELS = {ChannelType.WHATSAPP, ChannelType.INSTAGRAM, ChannelType.FACEBOOK}
RouteInboundMessage = Callable[..., Awaitable[str]]


async def list_channel_accounts(pool: asyncpg.Pool, org_id: str) -> list[dict]:
    """Backward-compatible repository used by billing and self-knowledge."""
    rows = await pool.fetch(
        """SELECT id, bot_id, channel_type, display_name, external_id, is_active,
                  connected_at, last_sync_at
           FROM channel_accounts WHERE org_id=$1 ORDER BY connected_at DESC""", org_id,
    )
    return [dict(row) for row in rows]


async def get_channel_account(pool: asyncpg.Pool, *, org_id: str | None, channel_type: str, external_id: str) -> dict | None:
    if org_id:
        row = await pool.fetchrow("SELECT * FROM channel_accounts WHERE org_id=$1 AND channel_type=$2 AND external_id=$3", org_id, channel_type, external_id)
    else:
        row = await pool.fetchrow("SELECT * FROM channel_accounts WHERE channel_type=$1 AND external_id=$2", channel_type, external_id)
    return dict(row) if row else None


async def unified_inbox(pool: asyncpg.Pool, *, org_id: str, state: str | None = None, channel: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    conditions, params = ["org_id = $1"], [org_id]
    if state:
        params.append(state); conditions.append(f"inbox_state = ${len(params)}")
    if channel:
        params.append(channel); conditions.append(f"channel = ${len(params)}")
    params.extend([limit, offset])
    rows = await pool.fetch(f"SELECT * FROM unified_inbox WHERE {' AND '.join(conditions)} ORDER BY last_msg_at DESC LIMIT ${len(params)-1} OFFSET ${len(params)}", *params)
    return [dict(row) for row in rows]


async def inbox_summary(pool: asyncpg.Pool, *, org_id: str) -> dict:
    row = await pool.fetchrow(
        """SELECT COUNT(*) FILTER (WHERE inbox_state='unread') AS unread,
                  COUNT(*) FILTER (WHERE inbox_state='assigned') AS assigned,
                  COUNT(*) FILTER (WHERE inbox_state='closed') AS closed,
                  COUNT(*) FILTER (WHERE inbox_state='escalation') AS escalation,
                  COUNT(*) AS total FROM unified_inbox WHERE org_id=$1""", org_id,
    )
    by_channel = await pool.fetch("SELECT channel, COUNT(*) AS total FROM unified_inbox WHERE org_id=$1 GROUP BY channel ORDER BY total DESC", org_id)
    return {"by_state": dict(row), "by_channel": [dict(item) for item in by_channel]}


class ConnectChannelReq(BaseModel):
    bot_id: str
    channel_type: ChannelType
    display_name: str = Field(min_length=2, max_length=120)
    external_id: str | None = Field(default=None, max_length=255)
    credentials: dict = Field(default_factory=dict)
    config: dict = Field(default_factory=dict)


class DisconnectChannelReq(BaseModel):
    connection_id: str


class SendMessageReq(BaseModel):
    connection_id: str
    user_id: str
    message: str = Field(min_length=1, max_length=10000)
    metadata: dict = Field(default_factory=dict)


class BroadcastReq(BaseModel):
    connection_ids: list[str] = Field(min_length=1, max_length=20)
    recipients: list[str] = Field(min_length=1, max_length=1000)
    message: str = Field(min_length=1, max_length=10000)


def platform_channel_config(channel: ChannelType) -> tuple[dict, str | None]:
    if channel == ChannelType.TELEGRAM:
        if not platform_cfg.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN belum dikonfigurasi oleh operator")
        return {"bot_token": platform_cfg.telegram_bot_token}, None
    if channel == ChannelType.INSTAGRAM:
        if not platform_cfg.instagram_access_token or not platform_cfg.instagram_account_id:
            raise ValueError("INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_ACCOUNT_ID belum dikonfigurasi oleh operator")
        return {
            "access_token": platform_cfg.instagram_access_token,
            "instagram_account_id": platform_cfg.instagram_account_id,
        }, platform_cfg.instagram_account_id
    if channel == ChannelType.FACEBOOK:
        if not platform_cfg.facebook_page_access_token or not platform_cfg.facebook_page_id:
            raise ValueError("FACEBOOK_PAGE_ACCESS_TOKEN / FACEBOOK_PAGE_ID belum dikonfigurasi oleh operator")
        return {
            "access_token": platform_cfg.facebook_page_access_token,
            "page_id": platform_cfg.facebook_page_id,
        }, platform_cfg.facebook_page_id
    if channel == ChannelType.WEBSITE:
        return {}, None
    raise ValueError("WhatsApp harus dihubungkan melalui Meta Embedded Signup")


def build_omnichannel_router(*, get_pool: GetPool, get_current_user: GetCurrentUser, require_permission, app_url: str, route_inbound_message: RouteInboundMessage | None = None, check_limit=None) -> APIRouter:
    router = APIRouter(tags=["omnichannel"])

    def manager(pool: asyncpg.Pool) -> ChannelManager:
        return ChannelManager(pool, route_inbound_message=route_inbound_message, app_url=app_url, webhook_secret=platform_cfg.telegram_webhook_secret)

    @router.get("/channels")
    async def get_channels(user: Annotated[dict, Depends(require_permission("settings.manage"))], pool: Annotated[asyncpg.Pool, Depends(get_pool)]):
        return {"channels": await manager(pool).list_connections(str(user["org_id"]))}

    @router.post("/channels/connect", status_code=status.HTTP_201_CREATED)
    async def connect(body: ConnectChannelReq, user: Annotated[dict, Depends(require_permission("settings.manage"))], pool: Annotated[asyncpg.Pool, Depends(get_pool)]):
        if check_limit:
            ok, detail = await check_limit(pool, user["org_id"], "channels")
            if not ok:
                raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, f"Limit channel paket {detail['plan']} tercapai ({detail['used']}/{detail['limit']})")
        try:
            credentials, platform_external_id = platform_channel_config(body.channel_type)
            connection = await manager(pool).connect_channel(
                tenant_id=str(user["org_id"]),
                bot_id=body.bot_id,
                channel=body.channel_type,
                display_name=body.display_name,
                external_id=platform_external_id or body.external_id,
                credentials=credentials,
                config=body.config,
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        except Exception as exc:
            logger.exception("Channel connect failed tenant=%s channel=%s", user["org_id"], body.channel_type.value)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Gagal menghubungkan {body.channel_type.value}. Coba lagi nanti.") from exc
        await write_audit_log(pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"), action="create", resource_type="channel_connection", resource_id=connection["id"], metadata={"channel_type": body.channel_type.value, "display_name": body.display_name})
        return {"channel": connection}

    async def perform_disconnect(connection_id: str, user: dict, pool: asyncpg.Pool):
        ok = await manager(pool).disconnect_channel(tenant_id=str(user["org_id"]), connection_id=connection_id)
        if not ok:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel tidak ditemukan")
        await write_audit_log(pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"), action="delete", resource_type="channel_connection", resource_id=connection_id, metadata={})
        return {"ok": True}

    @router.post("/channels/disconnect")
    async def disconnect_post(body: DisconnectChannelReq, user: Annotated[dict, Depends(require_permission("settings.manage"))], pool: Annotated[asyncpg.Pool, Depends(get_pool)]):
        return await perform_disconnect(body.connection_id, user, pool)

    @router.delete("/channels/{connection_id}")
    async def disconnect_legacy(connection_id: str, user: Annotated[dict, Depends(require_permission("settings.manage"))], pool: Annotated[asyncpg.Pool, Depends(get_pool)]):
        return await perform_disconnect(connection_id, user, pool)

    @router.get("/channels/status")
    async def channel_status(user: Annotated[dict, Depends(require_permission("settings.manage"))], pool: Annotated[asyncpg.Pool, Depends(get_pool)], refresh: bool = Query(False)):
        service = manager(pool)
        if refresh:
            await service.health_check(tenant_id=str(user["org_id"]))
        connections = await service.list_connections(str(user["org_id"]))
        return {"channels": connections, "summary": {state: sum(1 for item in connections if item.get("status") == state) for state in ("connected", "disconnected", "pending", "error")}}

    @router.get("/channels/analytics")
    async def channel_analytics(user: Annotated[dict, Depends(require_permission("analytics.read"))], pool: Annotated[asyncpg.Pool, Depends(get_pool)], days: int = Query(30, ge=1, le=365)):
        return await manager(pool).analytics(str(user["org_id"]), days=days)

    @router.post("/channels/send")
    async def send_message(body: SendMessageReq, user: Annotated[dict, Depends(require_permission("settings.manage"))], pool: Annotated[asyncpg.Pool, Depends(get_pool)]):
        try:
            return await manager(pool).send_message(tenant_id=str(user["org_id"]), connection_id=body.connection_id, user_id=body.user_id, message=body.message, metadata=body.metadata)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    @router.post("/channels/broadcast")
    async def broadcast(body: BroadcastReq, user: Annotated[dict, Depends(require_permission("settings.manage"))], pool: Annotated[asyncpg.Pool, Depends(get_pool)]):
        return await manager(pool).broadcast(tenant_id=str(user["org_id"]), connection_ids=body.connection_ids, recipients=body.recipients, message=body.message)

    @router.get("/inbox")
    async def get_inbox(user: Annotated[dict, Depends(require_permission("conversations.read"))], pool: Annotated[asyncpg.Pool, Depends(get_pool)], state: str | None = None, channel: str | None = None, limit: int = 50, offset: int = 0):
        return {"inbox": await unified_inbox(pool, org_id=user["org_id"], state=state, channel=channel, limit=limit, offset=offset)}

    @router.get("/inbox/summary")
    async def get_inbox_summary(user: Annotated[dict, Depends(require_permission("conversations.read"))], pool: Annotated[asyncpg.Pool, Depends(get_pool)]):
        return await inbox_summary(pool, org_id=user["org_id"])

    @router.get("/webhooks/channels/{channel}/{connection_id}", include_in_schema=False)
    async def verify_channel_webhook(channel: ChannelType, connection_id: str, request: Request, pool: Annotated[asyncpg.Pool, Depends(get_pool)]):
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token") or ""
        challenge = request.query_params.get("hub.challenge")
        verified_channel = await manager(pool).verify_webhook(connection_id=connection_id, verify_token=token)
        if mode != "subscribe" or verified_channel != channel.value or challenge is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Webhook verification gagal")
        return int(challenge) if challenge.isdigit() else challenge

    @router.post("/webhooks/channels/{channel}/{connection_id}", include_in_schema=False)
    async def channel_webhook(channel: ChannelType, connection_id: str, request: Request, pool: Annotated[asyncpg.Pool, Depends(get_pool)]):
        body_bytes = await request.body()
        if channel == ChannelType.TELEGRAM:
            provided = request.headers.get("x-telegram-bot-api-secret-token") or ""
            if not await manager(pool).verify_webhook_secret(connection_id=connection_id, provided=provided):
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Webhook secret tidak valid")
        elif channel in _META_CHANNELS:
            # Sebelumnya endpoint ini sama sekali tidak verifikasi apa pun untuk
            # whatsapp/instagram/facebook -- hanya connection_id (UUID di URL)
            # yang menjaga, mirip lubang Telegram yang sudah diperbaiki. Meta
            # selalu mengirim X-Hub-Signature-256, jadi wajib dicek di sini juga.
            app_secret = (platform_cfg.meta_app_secret or "").strip()
            if not app_secret:
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Meta webhook belum dikonfigurasi di server ini")
            sig = (request.headers.get("X-Hub-Signature-256") or "").strip()
            expected = "sha256=" + hmac.new(app_secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
            if not (sig and hmac.compare_digest(sig, expected)):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid signature")
        payload = json.loads(body_bytes.decode("utf-8") or "{}") if body_bytes else {}
        try:
            responses = await manager(pool).receive_message(connection_id=connection_id, payload=payload)
        except ValueError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        except Exception:
            logger.exception("Inbound channel processing failed connection=%s", connection_id)
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Pesan gagal diproses")
        return {"ok": True, "processed": len(responses)}

    @router.post("/channels/webchat/{connection_id}/messages")
    async def webchat_message(connection_id: str, request: Request, pool: Annotated[asyncpg.Pool, Depends(get_pool)]):
        payload = await request.json()
        try:
            responses = await manager(pool).receive_message(connection_id=connection_id, payload=payload)
        except ValueError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        response = responses[0] if responses else None
        return {"answer": response.get("reply") if response else "", "response_time_ms": response.get("response_time_ms") if response else 0}

    return router
