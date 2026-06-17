"""
Telegram webhook punya satu lubang: bn_platform/omnichannel.py::channel_webhook
hanya memverifikasi header X-Telegram-Bot-Api-Secret-Token kalau
TELEGRAM_WEBHOOK_SECRET diisi di env (`if platform_cfg.telegram_webhook_secret
and channel == ChannelType.TELEGRAM`). Karena env itu kosong di .env, webhook
Telegram diam-diam TIDAK diverifikasi sama sekali -- siapa pun yang tahu
connection_id (UUID di URL) bisa POST payload palsu dan memicu bot membalas
atas nama org tersebut.

Fix: webhook_secret sekarang dibuat per-koneksi secara otomatis saat
connect_channel() (tidak lagi tergantung env var global), dan verifikasi
selalu jalan untuk channel Telegram (fail-closed, bukan fail-open kalau
secret belum pernah diisi).
"""
import asyncio
import json

import pytest

from bn_platform.channel_manager import ChannelManager
from bn_platform.channels.models import ChannelType


class _FakePool:
    def __init__(self, connection_row: dict | None):
        self._connection_row = connection_row
        self.fetchrow_calls: list[tuple] = []

    async def fetchrow(self, sql, *params):
        self.fetchrow_calls.append((sql, params))
        return self._connection_row

    async def execute(self, sql, *params):
        return "OK"


def _connection_row(webhook_secret: str | None) -> dict:
    return {
        "id": "conn-1",
        "tenant_id": "org-1",
        "channel_type": "telegram",
        "status": "connected",
        "config": json.dumps({"webhook_secret": webhook_secret} if webhook_secret is not None else {}),
        "credentials": json.dumps({}),
    }


def test_verify_webhook_secret_accepts_matching_secret():
    pool = _FakePool(_connection_row("the-real-secret"))
    manager = ChannelManager(pool)
    assert asyncio.run(manager.verify_webhook_secret(connection_id="conn-1", provided="the-real-secret")) is True


def test_verify_webhook_secret_rejects_wrong_secret():
    pool = _FakePool(_connection_row("the-real-secret"))
    manager = ChannelManager(pool)
    assert asyncio.run(manager.verify_webhook_secret(connection_id="conn-1", provided="guessed-secret")) is False


def test_verify_webhook_secret_rejects_missing_header():
    pool = _FakePool(_connection_row("the-real-secret"))
    manager = ChannelManager(pool)
    assert asyncio.run(manager.verify_webhook_secret(connection_id="conn-1", provided="")) is False


def test_verify_webhook_secret_fails_closed_when_no_secret_was_ever_stored():
    """Sebelum fix: secret kosong di kedua sisi (env & stored) berarti pengecekan
    dilewati sama sekali. Sekarang: stored secret kosong harus tetap menolak,
    bahkan kalau header yang dikirim juga kosong -- tidak ada cara untuk
    'cocok dengan string kosong' dan lolos."""
    pool = _FakePool(_connection_row(""))
    manager = ChannelManager(pool)
    assert asyncio.run(manager.verify_webhook_secret(connection_id="conn-1", provided="")) is False


def test_verify_webhook_secret_rejects_unknown_connection():
    pool = _FakePool(None)
    manager = ChannelManager(pool)
    assert asyncio.run(manager.verify_webhook_secret(connection_id="does-not-exist", provided="anything")) is False


class _FakeRow(dict):
    """Asyncpg Record stand-in -- dict(row) dan row['x'] sama-sama harus jalan."""


class _ConnectFakePool:
    """Cukup untuk men-drive ChannelManager.connect_channel(): 3 fetchrow
    (register_channel, channel_accounts, channel_connections) + execute
    untuk _event/_log setelahnya."""
    def __init__(self):
        self.inserted_configs: list[dict] = []

    async def fetchrow(self, sql, *params):
        if "SELECT id FROM bots" in sql:
            return _FakeRow({"id": params[0]})
        if "INSERT INTO channels" in sql:
            return _FakeRow({"id": "channel-1", "tenant_id": params[0], "channel_type": params[1]})
        if "INSERT INTO channel_accounts" in sql:
            return _FakeRow({"id": "legacy-1"})
        if "INSERT INTO channel_connections" in sql:
            # params order: connection_id, tenant_id, channel_id, legacy_account_id,
            # bot_id, external_id, display_name, status, credentials, config, error_message
            config = json.loads(params[9])
            self.inserted_configs.append(config)
            return _FakeRow({
                "id": params[0], "tenant_id": params[1], "channel_type": "telegram",
                "bot_id": params[4], "status": params[7], "config": params[9],
            })
        raise AssertionError(f"unexpected fetchrow: {sql}")

    async def execute(self, sql, *params):
        return "OK"


class _StubTelegramConnector:
    def __init__(self, *, tenant_id, connection_id, credentials, config=None):
        self.config = config or {}

    async def connect(self):
        return {"connected": True, "external_id": "999", "username": "stub_bot"}


def test_connect_channel_auto_generates_webhook_secret_when_env_var_is_empty(monkeypatch):
    """Inti dari fix: walau ChannelManager dibuat tanpa webhook_secret global
    (persis kondisi .env saat ini), setiap koneksi baru tetap mendapat secret
    acak sendiri -- bukan string kosong yang membuat verifikasi nanti gagal
    terbuka."""
    import bn_platform.channel_manager as cm

    monkeypatch.setattr(cm, "build_connector", lambda *a, **kw: _StubTelegramConnector(**kw))
    pool = _ConnectFakePool()
    manager = ChannelManager(pool, webhook_secret="")

    asyncio.run(manager.connect_channel(
        tenant_id="org-1", bot_id="bot-1", channel=ChannelType.TELEGRAM,
        display_name="Test Bot", external_id=None, credentials={"bot_token": "tok"},
    ))

    assert len(pool.inserted_configs) == 1
    secret = pool.inserted_configs[0]["webhook_secret"]
    assert secret  # tidak kosong
    assert len(secret) >= 20  # secrets.token_urlsafe(32) -> string panjang, bukan placeholder pendek


def test_connect_channel_reuses_global_secret_when_configured(monkeypatch):
    import bn_platform.channel_manager as cm

    monkeypatch.setattr(cm, "build_connector", lambda *a, **kw: _StubTelegramConnector(**kw))
    pool = _ConnectFakePool()
    manager = ChannelManager(pool, webhook_secret="operator-configured-secret")

    asyncio.run(manager.connect_channel(
        tenant_id="org-1", bot_id="bot-1", channel=ChannelType.TELEGRAM,
        display_name="Test Bot", external_id=None, credentials={"bot_token": "tok"},
    ))

    assert pool.inserted_configs[0]["webhook_secret"] == "operator-configured-secret"
