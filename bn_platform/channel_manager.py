from __future__ import annotations

import json
import logging
import secrets
import time
import uuid
from typing import Any, Awaitable, Callable

import asyncpg

from .channels import ChannelType, UnifiedMessage, build_connector
from .security import decrypt_value, encrypt_value

logger = logging.getLogger("bn_platform.channel_manager")
RouteInboundMessage = Callable[..., Awaitable[str]]


class ChannelManager:
    def __init__(self, pool: asyncpg.Pool, *, route_inbound_message: RouteInboundMessage | None = None, app_url: str = "", webhook_secret: str = ""):
        self.pool = pool
        self.route_inbound_message = route_inbound_message
        self.app_url = app_url.rstrip("/")
        self.webhook_secret = webhook_secret

    async def register_channel(self, *, tenant_id: str, channel: ChannelType | str, display_name: str | None = None) -> dict[str, Any]:
        channel_type = ChannelType(channel)
        row = await self.pool.fetchrow(
            """INSERT INTO channels (tenant_id, channel_type, display_name)
               VALUES ($1,$2,$3)
               ON CONFLICT (tenant_id, channel_type) DO UPDATE SET
                 display_name=COALESCE(EXCLUDED.display_name, channels.display_name), updated_at=NOW()
               RETURNING *""",
            tenant_id, channel_type.value, display_name or self._channel_label(channel_type),
        )
        return dict(row)

    async def connect_channel(self, *, tenant_id: str, bot_id: str, channel: ChannelType | str, display_name: str, external_id: str | None, credentials: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        channel_type = ChannelType(channel)
        bot = await self.pool.fetchrow("SELECT id FROM bots WHERE id=$1 AND org_id=$2", bot_id, tenant_id)
        if not bot:
            raise ValueError("Bot tidak ditemukan untuk tenant ini")

        channel_row = await self.register_channel(tenant_id=tenant_id, channel=channel_type)
        connection_id = str(uuid.uuid4())
        connector_config = dict(config or {})
        connector_config["external_id"] = external_id or ""
        connector_config["webhook_url"] = f"{self.app_url}/api/webhooks/channels/{channel_type.value}/{connection_id}"
        connector_config["webhook_secret"] = self.webhook_secret
        connector_config["webhook_verify_token"] = str(connector_config.get("webhook_verify_token") or connection_id)
        connector = build_connector(channel_type, tenant_id=tenant_id, connection_id=connection_id, credentials=credentials, config=connector_config)

        encrypted = self._encrypt_credentials(credentials)
        status = "pending"
        error_message = None
        effective_external_id = external_id or (connector_config.get("domain") if channel_type == ChannelType.WEBSITE else None)
        try:
            connect_result = await connector.connect()
            effective_external_id = effective_external_id or connect_result.get("external_id") or connection_id
            connector_config["external_id"] = effective_external_id
            status = "connected"
        except Exception as exc:
            status = "error"
            error_message = str(exc)[:1000]
            await self._log(tenant_id, None, "error", "connect", error_message, {"channel": channel_type.value})
            raise

        legacy = await self.pool.fetchrow(
            """INSERT INTO channel_accounts (org_id, bot_id, channel_type, display_name, external_id, credentials, is_active)
               VALUES ($1,$2,$3,$4,$5,$6,TRUE)
               ON CONFLICT (org_id, channel_type, external_id) DO UPDATE SET
                 bot_id=EXCLUDED.bot_id, display_name=EXCLUDED.display_name,
                 credentials=EXCLUDED.credentials, is_active=TRUE, last_sync_at=NOW()
               RETURNING id""",
            tenant_id, bot_id, channel_type.value, display_name, effective_external_id, json.dumps(encrypted),
        )
        row = await self.pool.fetchrow(
            """INSERT INTO channel_connections
               (id, tenant_id, channel_id, legacy_account_id, bot_id, external_id, display_name, status, credentials, config, connected_at, error_message)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,NOW(),$11)
               ON CONFLICT (tenant_id, channel_id, external_id) DO UPDATE SET
                 legacy_account_id=EXCLUDED.legacy_account_id, bot_id=EXCLUDED.bot_id,
                 display_name=EXCLUDED.display_name, status=EXCLUDED.status,
                 credentials=EXCLUDED.credentials, config=EXCLUDED.config,
                 connected_at=NOW(), disconnected_at=NULL, error_message=EXCLUDED.error_message, updated_at=NOW()
               RETURNING *""",
            connection_id, tenant_id, channel_row["id"], legacy["id"], bot_id, effective_external_id, display_name,
            status, json.dumps(encrypted), json.dumps(connector_config), error_message,
        )
        await self._event(tenant_id, str(row["id"]), "connection.connected", {"channel": channel_type.value})
        await self._log(tenant_id, str(row["id"]), "info", "connect", "Channel connected", {"channel": channel_type.value})
        return self._public_connection(dict(row), channel_type.value)

    async def disconnect_channel(self, *, tenant_id: str, connection_id: str) -> bool:
        connection = await self._get_connection(connection_id, tenant_id=tenant_id)
        if not connection:
            return False
        connector = self._connector(connection)
        try:
            await connector.disconnect()
        except Exception:
            logger.exception("Provider disconnect failed connection=%s", connection_id)
        result = await self.pool.execute(
            """UPDATE channel_connections SET status='disconnected', disconnected_at=NOW(), updated_at=NOW()
               WHERE id=$1 AND tenant_id=$2""", connection_id, tenant_id,
        )
        if connection.get("legacy_account_id"):
            await self.pool.execute("UPDATE channel_accounts SET is_active=FALSE WHERE id=$1", connection["legacy_account_id"])
        await self._event(tenant_id, connection_id, "connection.disconnected", {})
        await self._log(tenant_id, connection_id, "info", "disconnect", "Channel disconnected", {})
        return str(result).endswith(" 1")

    async def send_message(self, *, tenant_id: str, connection_id: str, user_id: str, message: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        connection = await self._get_connection(connection_id, tenant_id=tenant_id)
        if not connection or connection["status"] != "connected":
            raise ValueError("Channel tidak terhubung")
        started = time.monotonic()
        try:
            provider_result = await self._connector(connection).send_message(user_id, message, metadata)
            status = "sent"
        except Exception as exc:
            await self._log(tenant_id, connection_id, "error", "send_message", str(exc), {"user_id": user_id})
            raise
        latency_ms = int((time.monotonic() - started) * 1000)
        message_id = str(uuid.uuid4())
        await self.pool.execute(
            """INSERT INTO channel_messages
               (id, tenant_id, connection_id, external_message_id, direction, user_id, message, status, response_time_ms, metadata)
               VALUES ($1,$2,$3,$4,'outbound',$5,$6,$7,$8,$9)""",
            message_id, tenant_id, connection_id, self._provider_message_id(provider_result), user_id, message, status, latency_ms, json.dumps(metadata or {}),
        )
        await self.pool.execute("UPDATE channel_connections SET last_activity_at=NOW(), updated_at=NOW() WHERE id=$1", connection_id)
        return {"id": message_id, "status": status, "latency_ms": latency_ms, "provider": provider_result}

    async def receive_message(self, *, connection_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        connection = await self._get_connection(connection_id)
        if not connection or connection["status"] != "connected":
            raise ValueError("Connection tidak ditemukan atau tidak aktif")
        connector = self._connector(connection)
        messages = await connector.receive_message(payload)
        responses: list[dict[str, Any]] = []
        for unified in messages:
            responses.append(await self._process_inbound(connection, connector, unified))
        return responses

    async def broadcast(self, *, tenant_id: str, connection_ids: list[str], recipients: list[str], message: str) -> dict[str, Any]:
        sent, failed = 0, []
        for connection_id in connection_ids:
            for recipient in recipients:
                try:
                    await self.send_message(tenant_id=tenant_id, connection_id=connection_id, user_id=recipient, message=message, metadata={"broadcast": True})
                    sent += 1
                except Exception as exc:
                    failed.append({"connection_id": connection_id, "user_id": recipient, "error": str(exc)})
        return {"sent": sent, "failed": failed}

    async def health_check(self, *, tenant_id: str, connection_id: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = [tenant_id]
        condition = "tenant_id=$1"
        if connection_id:
            params.append(connection_id)
            condition += " AND id=$2"
        rows = await self.pool.fetch(f"SELECT * FROM channel_connections WHERE {condition} ORDER BY display_name", *params)
        result = []
        for raw in rows:
            connection = dict(raw)
            healthy, error = False, None
            try:
                healthy = await self._connector(connection).validate()
            except Exception as exc:
                error = str(exc)[:500]
            new_status = "connected" if healthy else ("disconnected" if connection["status"] == "disconnected" else "error")
            await self.pool.execute("UPDATE channel_connections SET status=$2, last_health_check_at=NOW(), error_message=$3, updated_at=NOW() WHERE id=$1", connection["id"], new_status, error)
            result.append({"connection_id": str(connection["id"]), "channel": connection.get("channel_type"), "status": new_status, "healthy": healthy, "error": error})
        return result

    async def verify_webhook(self, *, connection_id: str, verify_token: str) -> str | None:
        connection = await self._get_connection(connection_id)
        if not connection:
            return None
        config = self._json(connection.get("config"))
        credentials = self._decrypt_credentials(connection.get("credentials"))
        expected = str(config.get("webhook_verify_token") or credentials.get("webhook_verify_token") or "")
        return str(connection.get("channel_type")) if expected and secrets.compare_digest(expected, str(verify_token)) else None

    async def list_connections(self, tenant_id: str) -> list[dict[str, Any]]:
        rows = await self.pool.fetch(
            """SELECT cc.*, c.channel_type,
                      COUNT(cm.id)::int AS message_count
               FROM channel_connections cc
               JOIN channels c ON c.id=cc.channel_id
               LEFT JOIN channel_messages cm ON cm.connection_id=cc.id
               WHERE cc.tenant_id=$1
               GROUP BY cc.id, c.channel_type
               ORDER BY cc.updated_at DESC""", tenant_id,
        )
        return [self._public_connection(dict(row), str(row["channel_type"])) for row in rows]

    async def analytics(self, tenant_id: str, *, days: int = 30) -> dict[str, Any]:
        summary = await self.pool.fetchrow(
            """SELECT COUNT(*)::int AS total_messages,
                      COUNT(DISTINCT user_id)::int AS active_users,
                      COALESCE(AVG(response_time_ms) FILTER (WHERE response_time_ms IS NOT NULL),0)::numeric(12,2) AS response_time_ms,
                      COUNT(*) FILTER (WHERE (metadata->>'conversion')::boolean IS TRUE)::int AS conversions
               FROM channel_messages WHERE tenant_id=$1 AND created_at >= NOW()-($2::text || ' days')::interval""", tenant_id, max(1, min(days, 365)),
        )
        usage = await self.pool.fetch(
            """SELECT c.channel_type AS channel, COUNT(cm.id)::int AS messages,
                      COUNT(DISTINCT cm.user_id)::int AS active_users
               FROM channels c
               LEFT JOIN channel_connections cc ON cc.channel_id=c.id AND cc.tenant_id=$1
               LEFT JOIN channel_messages cm ON cm.connection_id=cc.id AND cm.created_at >= NOW()-($2::text || ' days')::interval
               WHERE c.tenant_id=$1 GROUP BY c.channel_type ORDER BY messages DESC""", tenant_id, max(1, min(days, 365)),
        )
        total = int(summary["total_messages"] or 0)
        conversions = int(summary["conversions"] or 0)
        return {"total_messages": total, "active_users": int(summary["active_users"] or 0), "response_time_ms": float(summary["response_time_ms"] or 0), "conversion_rate": round(conversions / total * 100, 2) if total else 0.0, "top_channels": [dict(row) for row in usage], "channel_usage": [dict(row) for row in usage]}

    async def _process_inbound(self, connection: dict[str, Any], connector, unified: UnifiedMessage) -> dict[str, Any]:
        tenant_id, connection_id = str(connection["tenant_id"]), str(connection["id"])
        external_id = str(unified.metadata.get("external_message_id") or "") or None
        inbound_id = str(uuid.uuid4())
        await self.pool.execute(
            """INSERT INTO channel_messages
               (id, tenant_id, connection_id, external_message_id, direction, user_id, username, message, status, metadata)
               VALUES ($1,$2,$3,$4,'inbound',$5,$6,$7,'received',$8)
               ON CONFLICT DO NOTHING""",
            inbound_id, tenant_id, connection_id, external_id, unified.user_id, unified.username, unified.message, json.dumps(unified.metadata),
        )
        started = time.monotonic()
        reply = ""
        if self.route_inbound_message:
            reply = await self.route_inbound_message(org_id=tenant_id, bot_id=str(connection["bot_id"]), channel=unified.channel.value, external_user_id=unified.user_id, text=unified.message, display_name=unified.username or unified.user_id)
        latency_ms = int((time.monotonic() - started) * 1000)
        if reply:
            provider_result = await connector.send_message(unified.user_id, reply, {"in_reply_to": external_id})
            await self.pool.execute(
                """INSERT INTO channel_messages
                   (tenant_id, connection_id, external_message_id, direction, user_id, username, message, status, response_time_ms, metadata)
                   VALUES ($1,$2,$3,'outbound',$4,$5,$6,'sent',$7,$8)""",
                tenant_id, connection_id, self._provider_message_id(provider_result), unified.user_id, unified.username, reply, latency_ms, json.dumps({"in_reply_to": inbound_id}),
            )
        await self.pool.execute("UPDATE channel_connections SET last_activity_at=NOW(), updated_at=NOW() WHERE id=$1", connection_id)
        await self._event(tenant_id, connection_id, "message.received", {"message_id": inbound_id, "user_id": unified.user_id})
        return {"message": self._dump_message(unified), "reply": reply, "response_time_ms": latency_ms}

    async def _get_connection(self, connection_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
        condition = "cc.id=$1"
        params: list[Any] = [connection_id]
        if tenant_id:
            condition += " AND cc.tenant_id=$2"
            params.append(tenant_id)
        row = await self.pool.fetchrow(f"SELECT cc.*, c.channel_type FROM channel_connections cc JOIN channels c ON c.id=cc.channel_id WHERE {condition}", *params)
        return dict(row) if row else None

    def _connector(self, connection: dict[str, Any]):
        return build_connector(ChannelType(str(connection["channel_type"])), tenant_id=str(connection["tenant_id"]), connection_id=str(connection["id"]), credentials=self._decrypt_credentials(connection.get("credentials")), config=self._json(connection.get("config")))

    async def _event(self, tenant_id: str, connection_id: str | None, event_type: str, payload: dict[str, Any]) -> None:
        await self.pool.execute("INSERT INTO channel_events (tenant_id, connection_id, event_type, payload, status, processed_at) VALUES ($1,$2,$3,$4,'processed',NOW())", tenant_id, connection_id, event_type, json.dumps(payload))

    async def _log(self, tenant_id: str, connection_id: str | None, level: str, action: str, message: str, context: dict[str, Any]) -> None:
        await self.pool.execute("INSERT INTO channel_logs (tenant_id, connection_id, level, action, message, context) VALUES ($1,$2,$3,$4,$5,$6)", tenant_id, connection_id, level, action, message, json.dumps(context))

    @staticmethod
    def _encrypt_credentials(credentials: dict[str, Any]) -> dict[str, Any]:
        return {key: encrypt_value(value) if isinstance(value, str) and value else value for key, value in credentials.items()}

    @staticmethod
    def _decrypt_credentials(credentials: Any) -> dict[str, Any]:
        data = ChannelManager._json(credentials)
        result = {}
        for key, value in data.items():
            if isinstance(value, str) and value:
                try:
                    result[key] = decrypt_value(value)
                except Exception:
                    result[key] = value
            else:
                result[key] = value
        return result

    @staticmethod
    def _json(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return {}
        return dict(value or {})

    @staticmethod
    def _public_connection(row: dict[str, Any], channel: str) -> dict[str, Any]:
        row.pop("credentials", None)
        config = ChannelManager._json(row.get("config"))
        row["config"] = {key: value for key, value in config.items() if key not in {"webhook_secret", "app_secret"}}
        row["id"] = str(row["id"])
        row["tenant_id"] = str(row["tenant_id"])
        row["bot_id"] = str(row["bot_id"])
        row["channel_type"] = channel
        row["is_active"] = row.get("status") == "connected"
        row["last_sync_at"] = row.get("last_activity_at") or row.get("last_health_check_at")
        return row

    @staticmethod
    def _provider_message_id(payload: dict[str, Any]) -> str | None:
        if payload.get("result", {}).get("message_id"):
            return str(payload["result"]["message_id"])
        if payload.get("messages"):
            return str(payload["messages"][0].get("id") or "") or None
        return str(payload.get("message_id") or payload.get("id") or "") or None

    @staticmethod
    def _dump_message(message: UnifiedMessage) -> dict[str, Any]:
        return message.model_dump(mode="json") if hasattr(message, "model_dump") else message.dict()

    @staticmethod
    def _channel_label(channel: ChannelType) -> str:
        return {ChannelType.WHATSAPP: "WhatsApp", ChannelType.TELEGRAM: "Telegram", ChannelType.WEBSITE: "Website Chat", ChannelType.INSTAGRAM: "Instagram", ChannelType.FACEBOOK: "Facebook Messenger"}[channel]
