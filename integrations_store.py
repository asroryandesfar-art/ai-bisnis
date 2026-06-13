from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import asyncpg

try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:  # pragma: no cover
    Fernet = None  # type: ignore
    InvalidToken = Exception  # type: ignore


_DEFAULT_PATH = Path("data/integrations.json")


def _ensure_parent(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}


def _save(path: Path, data: dict[str, Any]) -> None:
    _ensure_parent(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_integrations(org_id: str, path: Path = _DEFAULT_PATH) -> dict[str, Any]:
    data = _load(path)
    return dict(data.get(org_id, {}) or {})


def set_integration(org_id: str, key: str, value: dict[str, Any], path: Path = _DEFAULT_PATH) -> None:
    data = _load(path)
    org = dict(data.get(org_id, {}) or {})
    org[key] = value
    data[org_id] = org
    _save(path, data)


def merge_integration(org_id: str, key: str, patch: dict[str, Any], path: Path = _DEFAULT_PATH) -> dict[str, Any]:
    data = _load(path)
    org = dict(data.get(org_id, {}) or {})
    current = dict(org.get(key, {}) or {})
    current.update(patch or {})
    org[key] = current
    data[org_id] = org
    _save(path, data)
    return current


def clear_integration(org_id: str, key: str, path: Path = _DEFAULT_PATH) -> None:
    data = _load(path)
    org = dict(data.get(org_id, {}) or {})
    if key in org:
        del org[key]
    data[org_id] = org
    _save(path, data)


def _fernet(secret_key: str) -> Fernet | None:
    """
    Derive a stable Fernet key from SECRET_KEY (any string).
    """
    if Fernet is None:
        return None
    raw = hashlib.sha256((secret_key or "").encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def encrypt_dict(secret_key: str, value: dict[str, Any]) -> str:
    f = _fernet(secret_key)
    if not f:
        # Fallback: store plaintext JSON (shouldn't happen if cryptography installed)
        return json.dumps(value or {}, ensure_ascii=False)
    token = f.encrypt(json.dumps(value or {}, ensure_ascii=False).encode("utf-8"))
    return token.decode("utf-8")


def decrypt_dict(secret_key: str, token: str) -> dict[str, Any]:
    token = (token or "").strip()
    if not token:
        return {}
    f = _fernet(secret_key)
    if not f:
        try:
            return json.loads(token)
        except Exception:
            return {}
    try:
        raw = f.decrypt(token.encode("utf-8"))
        return json.loads(raw.decode("utf-8") or "{}")
    except InvalidToken:
        return {}
    except Exception:
        return {}


async def db_set_integration(
    pool: asyncpg.Pool,
    *,
    org_id: str,
    key: str,
    value: dict[str, Any],
    secret_key: str,
) -> None:
    enc = encrypt_dict(secret_key, value)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO org_integrations(org_id, key, data_enc, updated_at)
            VALUES($1, $2, $3, NOW())
            ON CONFLICT (org_id, key)
            DO UPDATE SET data_enc=EXCLUDED.data_enc, updated_at=NOW()
            """,
            org_id,
            key,
            enc,
        )


async def db_get_integration(
    pool: asyncpg.Pool,
    *,
    org_id: str,
    key: str,
    secret_key: str,
) -> dict[str, Any]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT data_enc FROM org_integrations WHERE org_id=$1 AND key=$2",
            org_id,
            key,
        )
    if not row:
        return {}
    return decrypt_dict(secret_key, row["data_enc"] or "")


async def db_get_integrations(
    pool: asyncpg.Pool,
    *,
    org_id: str,
    secret_key: str,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT key, data_enc FROM org_integrations WHERE org_id=$1",
            org_id,
        )
    for r in rows:
        out[str(r["key"])] = decrypt_dict(secret_key, r["data_enc"] or "")
    return out


async def db_clear_integration(pool: asyncpg.Pool, *, org_id: str, key: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM org_integrations WHERE org_id=$1 AND key=$2", org_id, key)


async def db_set_oauth_state(
    pool: asyncpg.Pool,
    *,
    provider: str,
    state: str,
    org_id: str,
    redirect_uri: str,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO oauth_states(provider, state, org_id, redirect_uri, created_at)
            VALUES($1, $2, $3, $4, NOW())
            ON CONFLICT (provider, state)
            DO UPDATE SET org_id=EXCLUDED.org_id, redirect_uri=EXCLUDED.redirect_uri, created_at=NOW()
            """,
            provider,
            state,
            org_id,
            redirect_uri,
        )


async def db_pop_oauth_state(
    pool: asyncpg.Pool,
    *,
    provider: str,
    state: str,
) -> tuple[str | None, str | None]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT org_id, redirect_uri FROM oauth_states WHERE provider=$1 AND state=$2",
            provider,
            state,
        )
        if row:
            await conn.execute(
                "DELETE FROM oauth_states WHERE provider=$1 AND state=$2",
                provider,
                state,
            )
    if not row:
        return None, None
    return str(row["org_id"]), str(row["redirect_uri"])


async def db_set_meta_phone_mapping(
    pool: asyncpg.Pool,
    *,
    phone_number_id: str,
    org_id: str,
    bot_id: str,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO meta_wa_phone_map(phone_number_id, org_id, bot_id, updated_at)
            VALUES($1, $2, $3, NOW())
            ON CONFLICT (phone_number_id)
            DO UPDATE SET org_id=EXCLUDED.org_id, bot_id=EXCLUDED.bot_id, updated_at=NOW()
            """,
            phone_number_id,
            org_id,
            bot_id,
        )


async def db_get_meta_phone_mapping(
    pool: asyncpg.Pool,
    *,
    phone_number_id: str,
) -> tuple[str | None, str | None]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT org_id, bot_id FROM meta_wa_phone_map WHERE phone_number_id=$1",
            phone_number_id,
        )
    if not row:
        return None, None
    return str(row["org_id"]), str(row["bot_id"])


async def db_clear_meta_phone_mapping(pool: asyncpg.Pool, *, phone_number_id: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM meta_wa_phone_map WHERE phone_number_id=$1",
            phone_number_id,
        )


# ─── WhatsApp Embedded Signup — kredensial per tenant (org_id + bot_id) ────
#
# `customer_access_token` disimpan terenkripsi (Fernet, key dari SECRET_KEY,
# sama seperti `org_integrations`). Field lain (waba_id, phone_number_id,
# business_id, connection_status, token_expires_at) disimpan plaintext agar
# bisa di-query langsung (status endpoint, routing webhook) tanpa dekripsi.


def _whatsapp_row_to_dict(row: Any, secret_key: str) -> dict[str, Any]:
    decrypted = decrypt_dict(secret_key, row["access_token_enc"] or "")
    expires_at = row["token_expires_at"]
    return {
        "tenant_id": str(row["org_id"]),
        "org_id": str(row["org_id"]),
        "bot_id": str(row["bot_id"]),
        "waba_id": row["waba_id"],
        "phone_number_id": row["phone_number_id"],
        "business_id": row["business_id"],
        "customer_access_token": decrypted.get("customer_access_token", ""),
        "token_expires_at": expires_at.isoformat() if expires_at else None,
        "connection_status": row["connection_status"],
    }


async def db_set_whatsapp_account(
    pool: asyncpg.Pool,
    *,
    org_id: str,
    bot_id: str,
    waba_id: str,
    phone_number_id: str,
    business_id: str,
    customer_access_token: str,
    token_expires_at: Any,
    connection_status: str,
    secret_key: str,
) -> None:
    access_token_enc = encrypt_dict(secret_key, {"customer_access_token": customer_access_token or ""})
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO whatsapp_embedded_accounts(
                org_id, bot_id, waba_id, phone_number_id, business_id,
                access_token_enc, token_expires_at, connection_status, updated_at
            )
            VALUES($1, $2, $3, $4, $5, $6, $7, $8, NOW())
            ON CONFLICT (org_id, bot_id) DO UPDATE SET
                waba_id=EXCLUDED.waba_id,
                phone_number_id=EXCLUDED.phone_number_id,
                business_id=EXCLUDED.business_id,
                access_token_enc=EXCLUDED.access_token_enc,
                token_expires_at=EXCLUDED.token_expires_at,
                connection_status=EXCLUDED.connection_status,
                updated_at=NOW()
            """,
            org_id, bot_id, waba_id, phone_number_id, business_id,
            access_token_enc, token_expires_at, connection_status,
        )


async def db_get_whatsapp_account(
    pool: asyncpg.Pool,
    *,
    org_id: str,
    bot_id: str,
    secret_key: str,
) -> dict[str, Any] | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM whatsapp_embedded_accounts WHERE org_id=$1 AND bot_id=$2",
            org_id, bot_id,
        )
    if not row:
        return None
    return _whatsapp_row_to_dict(row, secret_key)


async def db_get_whatsapp_accounts(
    pool: asyncpg.Pool,
    *,
    org_id: str,
    secret_key: str,
) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM whatsapp_embedded_accounts WHERE org_id=$1 ORDER BY updated_at DESC",
            org_id,
        )
    return [_whatsapp_row_to_dict(r, secret_key) for r in rows]


async def db_clear_whatsapp_account(pool: asyncpg.Pool, *, org_id: str, bot_id: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM whatsapp_embedded_accounts WHERE org_id=$1 AND bot_id=$2",
            org_id, bot_id,
        )
