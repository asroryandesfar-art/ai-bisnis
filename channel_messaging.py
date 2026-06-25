"""channel_messaging.py — Channel Messaging safety layer (Tool Framework Phase 7).

`channel_messaging` adalah satu-satunya tool di tool_executor.py yang
sifatnya WRITE (mengirim pesan nyata ke pelanggan asli) -- semua tool lain
di Tool Framework read/generate-only. Mengikuti pola persis computer_agent.py:
agent (lewat tool_executor._exec_channel_messaging) TIDAK PERNAH mengirim
langsung, hanya membuat baris `channel_message_tasks` berstatus
'pending_approval'. Pengiriman SUNGGUHAN (lewat ChannelManager.send_message())
hanya terjadi di approve_task() setelah manusia menyetujui -- approval gate
adalah batas keamanannya, sama seperti Computer Agent's write actions.

Persistensi dilakukan modul ini (bukan tool_executor.py) supaya bisa dipakai
ulang oleh router (bn_platform/channel_messaging.py), sama seperti
computer_agent.py.
"""
from __future__ import annotations

import json

import asyncpg


async def create_task(
    pool: asyncpg.Pool, *, org_id: str, bot_id: str | None, agent_name: str,
    channel: str, recipient: str, message: str,
) -> dict:
    row = await pool.fetchrow(
        """INSERT INTO channel_message_tasks
               (org_id, bot_id, agent_name, channel, recipient, message, status)
           VALUES ($1,$2,$3,$4,$5,$6,'pending_approval')
           RETURNING *""",
        org_id, bot_id, agent_name, channel, recipient, message,
    )
    return dict(row)


async def get_task(pool: asyncpg.Pool, *, org_id: str, task_id: str) -> dict | None:
    row = await pool.fetchrow(
        "SELECT * FROM channel_message_tasks WHERE id=$1 AND org_id=$2", task_id, org_id,
    )
    return dict(row) if row else None


async def list_tasks(pool: asyncpg.Pool, *, org_id: str, status: str | None = None, limit: int = 50) -> list[dict]:
    limit = max(1, min(limit, 200))
    if status:
        rows = await pool.fetch(
            "SELECT * FROM channel_message_tasks WHERE org_id=$1 AND status=$2 ORDER BY created_at DESC LIMIT $3",
            org_id, status, limit,
        )
    else:
        rows = await pool.fetch(
            "SELECT * FROM channel_message_tasks WHERE org_id=$1 ORDER BY created_at DESC LIMIT $2",
            org_id, limit,
        )
    return [dict(r) for r in rows]


async def _find_connection_id(pool: asyncpg.Pool, *, org_id: str, channel: str) -> str | None:
    row = await pool.fetchrow(
        """SELECT cc.id FROM channel_connections cc JOIN channels c ON c.id=cc.channel_id
           WHERE cc.tenant_id=$1 AND c.channel_type=$2 AND cc.status='connected'
           ORDER BY cc.connected_at DESC LIMIT 1""",
        org_id, channel,
    )
    return str(row["id"]) if row else None


async def approve_task(pool: asyncpg.Pool, *, org_id: str, task_id: str, approver_id: str, app_url: str = "") -> dict | None:
    """Kirim pesan SUNGGUHAN via ChannelManager, lalu simpan hasilnya.
    None kalau task tidak ditemukan atau tidak berstatus pending_approval
    (juga mencegah approve dobel mengirim pesan dua kali)."""
    from bn_platform.channel_manager import ChannelManager

    task = await get_task(pool, org_id=org_id, task_id=task_id)
    if not task or task["status"] != "pending_approval":
        return None

    connection_id = await _find_connection_id(pool, org_id=org_id, channel=task["channel"])
    if not connection_id:
        result, new_status = {"success": False, "error": f"Channel '{task['channel']}' tidak terhubung untuk tenant ini"}, "failed"
    else:
        manager = ChannelManager(pool, app_url=app_url, webhook_secret="")
        try:
            send_result = await manager.send_message(
                tenant_id=org_id, connection_id=connection_id, user_id=task["recipient"], message=task["message"],
                metadata={"source": "channel_messaging_tool", "agent_name": task["agent_name"]},
            )
            result, new_status = send_result, "sent"
        except Exception as exc:
            result, new_status = {"success": False, "error": str(exc)}, "failed"

    row = await pool.fetchrow(
        """UPDATE channel_message_tasks
           SET status=$1, result=$2, approved_by=$3, approved_at=NOW(), updated_at=NOW()
           WHERE id=$4 AND org_id=$5
           RETURNING *""",
        new_status, json.dumps(result, default=str), approver_id, task_id, org_id,
    )
    return dict(row) if row else None


async def reject_task(pool: asyncpg.Pool, *, org_id: str, task_id: str, approver_id: str, reason: str | None) -> dict | None:
    task = await get_task(pool, org_id=org_id, task_id=task_id)
    if not task or task["status"] != "pending_approval":
        return None
    row = await pool.fetchrow(
        """UPDATE channel_message_tasks
           SET status='rejected', rejected_reason=$1, approved_by=$2, approved_at=NOW(), updated_at=NOW()
           WHERE id=$3 AND org_id=$4
           RETURNING *""",
        reason, approver_id, task_id, org_id,
    )
    return dict(row) if row else None
