"""
bn_platform/omnichannel.py — WhatsApp + Telegram + Website Chat -> Unified Inbox

BotNesia sudah punya integrasi WhatsApp (Meta Cloud API, lihat main.py
`_handle_meta_whatsapp_inbound` / `_meta_route_and_reply_whatsapp`) dan
Website Chat (widget bawaan, percakapan langsung lewat /chat). Modul ini
MENAMBAHKAN:

  1. Telegram Bot API sebagai channel baru (kirim/terima pesan, webhook)
  2. `channel_accounts` — registry channel per tenant (multi nomor WA,
     multi bot Telegram, dst), kredensial terenkripsi (lihat security.py)
  3. Unified Inbox — satu endpoint dashboard yang menggabungkan SEMUA
     channel (whatsapp/telegram/website/gmail/instagram) dengan status
     unread / assigned / closed / escalation (lihat VIEW `unified_inbox`
     di schema_platform.sql §4)

Integrasi dengan pipeline chat existing: route handler webhook Telegram di
sini meneruskan pesan masuk ke fungsi `route_inbound_message` yang dioper
dari main.py (membungkus pemanggilan SupervisorAgent + persist + balasan),
sehingga TIDAK ada duplikasi logic dengan `_meta_route_and_reply_whatsapp`.
"""
# from __future__ import annotations  # dihapus: menyebabkan Depends(closure_var) gagal di-resolve oleh FastAPI get_type_hints()

import json
import logging
from typing import Annotated, Awaitable, Callable

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from .config import cfg as platform_cfg
from .security import encrypt_value, decrypt_value, write_audit_log

logger = logging.getLogger("bn_platform.omnichannel")

GetCurrentUser = Callable[..., Awaitable[dict]]
GetPool        = Callable[..., Awaitable[asyncpg.Pool]]

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"

# RouteInboundMessage(org_id, bot_id, channel, external_user_id, text, display_name) -> str (balasan bot)
RouteInboundMessage = Callable[..., Awaitable[str]]


# ============================================================
# TELEGRAM BOT API CLIENT
# ============================================================

async def telegram_get_me(bot_token: str) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(TELEGRAM_API_BASE.format(token=bot_token) + "/getMe")
    data = resp.json()
    if not data.get("ok"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Token Telegram tidak valid: {data.get('description')}")
    return data["result"]


async def telegram_set_webhook(bot_token: str, webhook_url: str, secret_token: str | None = None) -> dict:
    payload = {"url": webhook_url, "allowed_updates": ["message"]}
    if secret_token:
        payload["secret_token"] = secret_token
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(TELEGRAM_API_BASE.format(token=bot_token) + "/setWebhook", json=payload)
    data = resp.json()
    if not data.get("ok"):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Gagal set webhook Telegram: {data.get('description')}")
    return data


async def telegram_send_message(bot_token: str, chat_id: int | str, text: str) -> None:
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            TELEGRAM_API_BASE.format(token=bot_token) + "/sendMessage",
            json={"chat_id": chat_id, "text": text[:4096]},
        )
    if resp.status_code >= 400:
        logger.error("Telegram sendMessage gagal: %s %s", resp.status_code, resp.text[:300])


# ============================================================
# REPOSITORY — channel accounts
# ============================================================

async def list_channel_accounts(pool: asyncpg.Pool, org_id: str) -> list[dict]:
    rows = await pool.fetch(
        """SELECT id, bot_id, channel_type, display_name, external_id, is_active,
                  connected_at, last_sync_at
           FROM channel_accounts WHERE org_id=$1 ORDER BY connected_at DESC""",
        org_id,
    )
    return [dict(r) for r in rows]


async def get_channel_account(pool: asyncpg.Pool, *, org_id: str | None, channel_type: str,
                              external_id: str) -> dict | None:
    if org_id:
        row = await pool.fetchrow(
            "SELECT * FROM channel_accounts WHERE org_id=$1 AND channel_type=$2 AND external_id=$3",
            org_id, channel_type, external_id,
        )
    else:
        row = await pool.fetchrow(
            "SELECT * FROM channel_accounts WHERE channel_type=$1 AND external_id=$2",
            channel_type, external_id,
        )
    return dict(row) if row else None


async def connect_channel(pool: asyncpg.Pool, *, org_id: str, bot_id: str, channel_type: str,
                          display_name: str, external_id: str | None, credentials: dict) -> dict:
    bot = await pool.fetchrow("SELECT id FROM bots WHERE id=$1 AND org_id=$2", bot_id, org_id)
    if not bot:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bot tidak ditemukan")

    encrypted = {k: (encrypt_value(v) if isinstance(v, str) else v) for k, v in credentials.items()}
    row = await pool.fetchrow(
        """INSERT INTO channel_accounts (org_id, bot_id, channel_type, display_name, external_id, credentials)
           VALUES ($1,$2,$3,$4,$5,$6)
           ON CONFLICT (org_id, channel_type, external_id) DO UPDATE SET
               display_name = EXCLUDED.display_name,
               credentials  = EXCLUDED.credentials,
               bot_id       = EXCLUDED.bot_id,
               is_active    = TRUE
           RETURNING id, bot_id, channel_type, display_name, external_id, is_active, connected_at""",
        org_id, bot_id, channel_type, display_name, external_id or "", json.dumps(encrypted),
    )
    return dict(row)


async def disconnect_channel(pool: asyncpg.Pool, *, org_id: str, channel_id: str) -> bool:
    result = await pool.execute(
        "UPDATE channel_accounts SET is_active=FALSE WHERE id=$1 AND org_id=$2", channel_id, org_id,
    )
    return result.endswith(" 1") if isinstance(result, str) else False


def _decrypt_credentials(creds: dict | str | None) -> dict:
    if isinstance(creds, str):
        try:
            creds = json.loads(creds)
        except json.JSONDecodeError:
            creds = {}
    return {k: (decrypt_value(v) if isinstance(v, str) else v) for k, v in (creds or {}).items()}


# ============================================================
# UNIFIED INBOX — query gabungan semua channel
# ============================================================

async def unified_inbox(pool: asyncpg.Pool, *, org_id: str, state: str | None = None,
                        channel: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    conditions = ["org_id = $1"]
    params: list = [org_id]
    if state:
        params.append(state)
        conditions.append(f"inbox_state = ${len(params)}")
    if channel:
        params.append(channel)
        conditions.append(f"channel = ${len(params)}")
    where = " AND ".join(conditions)
    params.extend([limit, offset])
    rows = await pool.fetch(
        f"""SELECT * FROM unified_inbox WHERE {where}
            ORDER BY last_msg_at DESC LIMIT ${len(params)-1} OFFSET ${len(params)}""",
        *params,
    )
    return [dict(r) for r in rows]


async def inbox_summary(pool: asyncpg.Pool, *, org_id: str) -> dict:
    row = await pool.fetchrow(
        """SELECT
             COUNT(*) FILTER (WHERE inbox_state='unread')      AS unread,
             COUNT(*) FILTER (WHERE inbox_state='assigned')    AS assigned,
             COUNT(*) FILTER (WHERE inbox_state='closed')      AS closed,
             COUNT(*) FILTER (WHERE inbox_state='escalation')  AS escalation,
             COUNT(*)                                          AS total
           FROM unified_inbox WHERE org_id=$1""",
        org_id,
    )
    by_channel = await pool.fetch(
        "SELECT channel, COUNT(*) AS total FROM unified_inbox WHERE org_id=$1 GROUP BY channel ORDER BY total DESC",
        org_id,
    )
    return {"by_state": dict(row), "by_channel": [dict(r) for r in by_channel]}


# ============================================================
# ROUTER
# ============================================================

class ConnectChannelReq(BaseModel):
    bot_id:       str
    channel_type: str = Field(pattern="^(whatsapp|telegram|website|instagram|email|gmail)$")
    display_name: str
    external_id:  str | None = None
    credentials:  dict = Field(default_factory=dict)   # mis. {"bot_token": "123:ABC..."} (Telegram)


def build_omnichannel_router(*, get_pool: GetPool, get_current_user: GetCurrentUser,
                             require_permission, app_url: str,
                             route_inbound_message: RouteInboundMessage | None = None,
                             check_limit=None) -> APIRouter:
    router = APIRouter(tags=["omnichannel"])

    # ── Channel account management ──────────────────────────
    @router.get("/channels")
    async def get_channels(
        user: Annotated[dict, Depends(require_permission("settings.manage"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        return {"channels": await list_channel_accounts(pool, user["org_id"])}

    @router.post("/channels/connect", status_code=status.HTTP_201_CREATED)
    async def connect(
        body: ConnectChannelReq,
        user: Annotated[dict, Depends(require_permission("settings.manage"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        if check_limit:
            ok, detail = await check_limit(pool, user["org_id"], "channels")
            if not ok:
                raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, f"Limit channel paket {detail['plan']} tercapai ({detail['used']}/{detail['limit']})")

        external_id = body.external_id
        if body.channel_type == "telegram":
            token = body.credentials.get("bot_token", "")
            if not token:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "credentials.bot_token wajib diisi untuk Telegram")
            me = await telegram_get_me(token)
            external_id = external_id or str(me.get("id"))
            webhook_url = f"{app_url.rstrip('/')}/webhooks/telegram/{user['org_id']}"
            await telegram_set_webhook(token, webhook_url, secret_token=platform_cfg.telegram_webhook_secret or None)

        account = await connect_channel(
            pool, org_id=user["org_id"], bot_id=body.bot_id, channel_type=body.channel_type,
            display_name=body.display_name, external_id=external_id, credentials=body.credentials,
        )
        await write_audit_log(pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
                              action="create", resource_type="channel_account", resource_id=str(account["id"]),
                              metadata={"channel_type": body.channel_type, "display_name": body.display_name})
        return {"channel": account}

    @router.delete("/channels/{channel_id}")
    async def disconnect(
        channel_id: str,
        user: Annotated[dict, Depends(require_permission("settings.manage"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        ok = await disconnect_channel(pool, org_id=user["org_id"], channel_id=channel_id)
        if not ok:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel tidak ditemukan")
        await write_audit_log(pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
                              action="delete", resource_type="channel_account", resource_id=channel_id, metadata={})
        return {"ok": True}

    # ── Unified Inbox ────────────────────────────────────────
    @router.get("/inbox")
    async def get_inbox(
        user: Annotated[dict, Depends(require_permission("conversations.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        state: str | None = None, channel: str | None = None, limit: int = 50, offset: int = 0,
    ):
        items = await unified_inbox(pool, org_id=user["org_id"], state=state, channel=channel,
                                    limit=limit, offset=offset)
        return {"inbox": items}

    @router.get("/inbox/summary")
    async def get_inbox_summary(
        user: Annotated[dict, Depends(require_permission("conversations.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        return await inbox_summary(pool, org_id=user["org_id"])

    # ── Telegram inbound webhook ─────────────────────────────
    # Didaftarkan tanpa /api prefix (top-level) supaya cocok dgn URL yang
    # didaftarkan ke Telegram saat connect: {app_url}/webhooks/telegram/{org_id}
    @router.post("/webhooks/telegram/{org_id}", include_in_schema=False)
    async def telegram_webhook(org_id: str, request: Request, pool: Annotated[asyncpg.Pool, Depends(get_pool)]):
        if platform_cfg.telegram_webhook_secret:
            secret = request.headers.get("x-telegram-bot-api-secret-token")
            if secret != platform_cfg.telegram_webhook_secret:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Secret token tidak valid")

        update = await request.json()
        message = update.get("message") or update.get("edited_message")
        if not message:
            return {"ok": True}

        chat = message.get("chat", {})
        chat_id = chat.get("id")
        text = (message.get("text") or "").strip()
        if not chat_id or not text:
            return {"ok": True}

        account = await get_channel_account(pool, org_id=org_id, channel_type="telegram", external_id=str(chat_id))
        if not account:
            # cari berdasar bot Telegram (bot_token cocok dgn update ini) -> fallback: channel pertama org ini
            account = await pool.fetchrow(
                "SELECT * FROM channel_accounts WHERE org_id=$1 AND channel_type='telegram' AND is_active=TRUE LIMIT 1",
                org_id,
            )
            account = dict(account) if account else None
        if not account:
            logger.warning("Telegram webhook: tidak ada channel_account utk org %s", org_id)
            return {"ok": True}

        creds = _decrypt_credentials(account["credentials"])
        bot_token = creds.get("bot_token")
        if not bot_token:
            return {"ok": True}

        display_name = chat.get("first_name") or chat.get("username") or "Telegram User"
        reply_text = "Maaf, sistem sedang sibuk. Coba lagi sebentar lagi ya."
        if route_inbound_message:
            try:
                reply_text = await route_inbound_message(
                    org_id=org_id, bot_id=str(account["bot_id"]), channel="telegram",
                    external_user_id=f"tg:{chat_id}", text=text, display_name=display_name,
                )
            except Exception:
                logger.exception("Gagal memproses pesan Telegram masuk (org=%s chat=%s)", org_id, chat_id)

        await telegram_send_message(bot_token, chat_id, reply_text)
        await pool.execute("UPDATE channel_accounts SET last_sync_at=NOW() WHERE id=$1", account["id"])
        return {"ok": True}

    return router
