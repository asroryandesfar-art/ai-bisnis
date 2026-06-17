"""
ChannelManager.disconnect_channel() and send_message() both validate
ownership once via _get_connection(connection_id, tenant_id=tenant_id), but
then ran a couple of trailing UPDATE statements scoped only by id (not
tenant_id/org_id):
  - disconnect_channel: UPDATE channel_accounts SET is_active=FALSE WHERE id=$1
  - send_message / _process_inbound: UPDATE channel_connections SET
    last_activity_at=... WHERE id=$1

Safe under the current call sites (the id values come from an
already-tenant-scoped row), but defense-in-depth -- consistent with the
org_id audit fixes elsewhere in this codebase -- means every later
mutating query on the same resource should independently filter by
tenant_id/org_id too, not just the first one.
"""
import asyncio
import json

from bn_platform.channel_manager import ChannelManager


class _FakePool:
    def __init__(self, connection_row: dict):
        self._connection_row = connection_row
        self.executed: list[tuple] = []

    async def fetchrow(self, sql, *params):
        return self._connection_row

    async def execute(self, sql, *params):
        self.executed.append((sql, params))
        if "channel_connections SET status='disconnected'" in sql:
            return "UPDATE 1"
        return "OK"


def _connection_row(*, tenant_id: str, legacy_account_id: str | None = "legacy-1") -> dict:
    return {
        "id": "conn-1",
        "tenant_id": tenant_id,
        "channel_type": "website",
        "status": "connected",
        "legacy_account_id": legacy_account_id,
        "config": json.dumps({}),
        "credentials": json.dumps({}),
    }


def test_disconnect_channel_scopes_legacy_account_update_by_org_id():
    pool = _FakePool(_connection_row(tenant_id="org-1"))
    manager = ChannelManager(pool)

    result = asyncio.run(manager.disconnect_channel(tenant_id="org-1", connection_id="conn-1"))

    assert result is True
    legacy_updates = [(sql, args) for sql, args in pool.executed if "channel_accounts" in sql]
    assert legacy_updates
    sql, args = legacy_updates[0]
    assert "org_id" in sql
    assert "org-1" in args


def test_disconnect_channel_skips_legacy_update_without_legacy_account():
    pool = _FakePool(_connection_row(tenant_id="org-1", legacy_account_id=None))
    manager = ChannelManager(pool)

    asyncio.run(manager.disconnect_channel(tenant_id="org-1", connection_id="conn-1"))

    legacy_updates = [(sql, args) for sql, args in pool.executed if "channel_accounts" in sql]
    assert legacy_updates == []


def test_send_message_scopes_last_activity_update_by_tenant_id():
    pool = _FakePool(_connection_row(tenant_id="org-1"))
    manager = ChannelManager(pool)

    result = asyncio.run(manager.send_message(
        tenant_id="org-1", connection_id="conn-1", user_id="web:1", message="halo",
    ))

    assert result["status"] == "sent"
    activity_updates = [(sql, args) for sql, args in pool.executed if "last_activity_at" in sql]
    assert activity_updates
    sql, args = activity_updates[0]
    assert "tenant_id" in sql
    assert "org-1" in args
