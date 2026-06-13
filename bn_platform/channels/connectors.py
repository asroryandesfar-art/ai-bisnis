from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from .base import BaseConnector
from .models import ChannelType, UnifiedMessage


class ConnectorError(RuntimeError):
    pass


class _HttpConnector(BaseConnector):
    timeout = 20.0

    async def _request(self, method: str, url: str, **kwargs) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(method, url, **kwargs)
        if response.status_code >= 400:
            raise ConnectorError(f"Provider request failed ({response.status_code}): {response.text[:300]}")
        return response.json() if response.content else {}

    async def disconnect(self) -> None:
        return None

    async def sync(self) -> dict[str, Any]:
        return {"healthy": await self.validate()}


class TelegramConnector(_HttpConnector):
    channel = ChannelType.TELEGRAM

    @property
    def token(self) -> str:
        return str(self.credentials.get("bot_token") or "")

    async def validate(self) -> bool:
        if not self.token:
            return False
        data = await self._request("GET", f"https://api.telegram.org/bot{self.token}/getMe")
        return bool(data.get("ok"))

    async def connect(self) -> dict[str, Any]:
        if not self.token:
            raise ConnectorError("Token Telegram wajib diisi")
        identity = await self._request("GET", f"https://api.telegram.org/bot{self.token}/getMe")
        if not identity.get("ok"):
            raise ConnectorError("Token Telegram tidak valid")
        webhook_url = self.config.get("webhook_url")
        if webhook_url:
            payload: dict[str, Any] = {"url": webhook_url, "allowed_updates": ["message", "edited_message"]}
            if self.config.get("webhook_secret"):
                payload["secret_token"] = self.config["webhook_secret"]
            data = await self._request("POST", f"https://api.telegram.org/bot{self.token}/setWebhook", json=payload)
            if not data.get("ok"):
                raise ConnectorError(data.get("description") or "Gagal memasang webhook Telegram")
        me = identity.get("result") or {}
        return {"connected": True, "external_id": str(me.get("id") or ""), "username": me.get("username")}

    async def send_message(self, user_id: str, message: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        chat_id = str(user_id).removeprefix("tg:")
        return await self._request("POST", f"https://api.telegram.org/bot{self.token}/sendMessage", json={"chat_id": chat_id, "text": message[:4096]})

    async def receive_message(self, payload: dict[str, Any]) -> list[UnifiedMessage]:
        item = payload.get("message") or payload.get("edited_message") or {}
        chat = item.get("chat") or {}
        text = (item.get("text") or item.get("caption") or "").strip()
        if not chat.get("id") or not text:
            return []
        return [UnifiedMessage(tenant_id=self.tenant_id, channel=self.channel, user_id=f"tg:{chat['id']}", username=chat.get("username") or chat.get("first_name"), message=text, timestamp=_timestamp(item.get("date")), metadata={"external_message_id": str(item.get("message_id") or ""), "raw": payload})]


class _MetaConnector(_HttpConnector):
    graph_version = "v21.0"
    channel: ChannelType
    id_key: str

    @property
    def token(self) -> str:
        return str(self.credentials.get("access_token") or "")

    @property
    def account_id(self) -> str:
        return str(self.credentials.get(self.id_key) or self.config.get("external_id") or "")

    async def validate(self) -> bool:
        if not self.token or not self.account_id:
            return False
        await self._request("GET", f"https://graph.facebook.com/{self.graph_version}/{self.account_id}", params={"access_token": self.token, "fields": "id,name"})
        return True

    async def connect(self) -> dict[str, Any]:
        if not await self.validate():
            raise ConnectorError(f"Kredensial {self.channel.value} tidak valid")
        return {"connected": True, "account_id": self.account_id}

    async def send_message(self, user_id: str, message: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        recipient = str(user_id).split(":", 1)[-1]
        if self.channel == ChannelType.WHATSAPP:
            payload = {"messaging_product": "whatsapp", "to": recipient, "type": "text", "text": {"body": message}}
            return await self._request("POST", f"https://graph.facebook.com/{self.graph_version}/{self.account_id}/messages", params={"access_token": self.token}, json=payload)
        payload = {"recipient": {"id": recipient}, "message": {"text": message}}
        return await self._request("POST", f"https://graph.facebook.com/{self.graph_version}/{self.account_id}/messages", params={"access_token": self.token}, json=payload)

    async def receive_message(self, payload: dict[str, Any]) -> list[UnifiedMessage]:
        return _parse_meta_messages(payload, tenant_id=self.tenant_id, channel=self.channel)


class WhatsAppConnector(_MetaConnector):
    channel = ChannelType.WHATSAPP
    id_key = "phone_number_id"


class InstagramConnector(_MetaConnector):
    channel = ChannelType.INSTAGRAM
    id_key = "instagram_account_id"


class FacebookConnector(_MetaConnector):
    channel = ChannelType.FACEBOOK
    id_key = "page_id"


class WebChatConnector(BaseConnector):
    channel = ChannelType.WEBSITE

    async def connect(self) -> dict[str, Any]:
        return {"connected": True, "domain": self.config.get("domain")}

    async def disconnect(self) -> None:
        return None

    async def validate(self) -> bool:
        return True

    async def sync(self) -> dict[str, Any]:
        return {"healthy": True}

    async def send_message(self, user_id: str, message: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"accepted": True, "user_id": user_id, "message": message}

    async def receive_message(self, payload: dict[str, Any]) -> list[UnifiedMessage]:
        text = str(payload.get("message") or "").strip()
        user_id = str(payload.get("user_id") or payload.get("session_id") or "").strip()
        if not text or not user_id:
            return []
        return [UnifiedMessage(tenant_id=self.tenant_id, channel=self.channel, user_id=user_id, username=payload.get("username"), message=text, metadata={k: v for k, v in payload.items() if k not in {"message", "user_id", "username"}})]


CONNECTOR_TYPES: dict[ChannelType, type[BaseConnector]] = {
    ChannelType.WHATSAPP: WhatsAppConnector,
    ChannelType.TELEGRAM: TelegramConnector,
    ChannelType.INSTAGRAM: InstagramConnector,
    ChannelType.FACEBOOK: FacebookConnector,
    ChannelType.WEBSITE: WebChatConnector,
}


def build_connector(channel: ChannelType | str, **kwargs) -> BaseConnector:
    channel_type = ChannelType(channel)
    return CONNECTOR_TYPES[channel_type](**kwargs)


def _timestamp(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return datetime.now(timezone.utc)


def _parse_meta_messages(payload: dict[str, Any], *, tenant_id: str, channel: ChannelType) -> list[UnifiedMessage]:
    result: list[UnifiedMessage] = []
    for entry in payload.get("entry") or []:
        if channel == ChannelType.WHATSAPP:
            for change in entry.get("changes") or []:
                value = change.get("value") or {}
                contacts = {str(c.get("wa_id")): (c.get("profile") or {}).get("name") for c in value.get("contacts") or []}
                for item in value.get("messages") or []:
                    text = ((item.get("text") or {}).get("body") or "").strip()
                    sender = str(item.get("from") or "")
                    if text and sender:
                        result.append(UnifiedMessage(tenant_id=tenant_id, channel=channel, user_id=f"wa:{sender}", username=contacts.get(sender), message=text, timestamp=_timestamp(item.get("timestamp") and int(item["timestamp"])), metadata={"external_message_id": str(item.get("id") or ""), "raw": item}))
            continue
        for event in entry.get("messaging") or []:
            message = event.get("message") or {}
            text = str(message.get("text") or "").strip()
            sender = str((event.get("sender") or {}).get("id") or "")
            if text and sender and not message.get("is_echo"):
                prefix = "ig" if channel == ChannelType.INSTAGRAM else "fb"
                result.append(UnifiedMessage(tenant_id=tenant_id, channel=channel, user_id=f"{prefix}:{sender}", username=None, message=text, timestamp=_timestamp((event.get("timestamp") or 0) / 1000), metadata={"external_message_id": str(message.get("mid") or ""), "raw": event}))
    return result
