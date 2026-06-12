"""
bn_platform/security.py — Audit Log, encryption helper, & automated security scan.

  • encrypt_value/decrypt_value — enkripsi simetris (Fernet/AES-128-CBC+HMAC)
    untuk kredensial channel (token WhatsApp/Telegram) yang disimpan di DB.
    Kunci dari CHANNEL_ENCRYPTION_KEY (.env) — generate dengan:
        python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  • write_audit_log — pencatat jejak aksi (siapa melakukan apa, kapan, dari mana)
  • run_security_scan — pemeriksaan konfigurasi keamanan otomatis (checklist),
    dijadwalkan via Celery beat (lihat celery_app.py) atau dipicu manual lewat
    endpoint /security/scan
"""
# from __future__ import annotations  # dihapus: menyebabkan Depends(closure_var) gagal di-resolve oleh FastAPI get_type_hints()

import json
import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Annotated, Awaitable, Callable

import asyncpg
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request, status

from .config import cfg as platform_cfg

logger = logging.getLogger("bn_platform.security")

GetCurrentUser = Callable[..., Awaitable[dict]]
GetPool        = Callable[..., Awaitable[asyncpg.Pool]]

# ============================================================
# PER-ORG RATE LIMITER (in-memory sliding window)
# ============================================================
# Batas default: 60 req/menit untuk API management endpoints
# (bukan chat — chat punya rate limiter sendiri di rate_limiter.py)
_ORG_WINDOW_SECS = 60
_ORG_MAX_REQUESTS = 60           # 60 req per menit per org
_BILLING_MAX_REQUESTS = 10       # 10 req per menit untuk billing/checkout

_org_timestamps: dict[str, deque] = defaultdict(deque)


def _check_rate_limit(org_id: str, max_req: int = _ORG_MAX_REQUESTS) -> None:
    """Sliding window rate limiter per org. Raises 429 jika melewati batas."""
    now = time.monotonic()
    dq = _org_timestamps[org_id]
    # Hapus entri di luar jendela
    while dq and dq[0] < now - _ORG_WINDOW_SECS:
        dq.popleft()
    if len(dq) >= max_req:
        raise HTTPException(
            status_code=429,
            detail=f"Terlalu banyak request. Batas: {max_req} req/{_ORG_WINDOW_SECS}s. Coba lagi sebentar.",
            headers={"Retry-After": str(_ORG_WINDOW_SECS)},
        )
    dq.append(now)

# ============================================================
# ENCRYPTION — kredensial channel & rahasia lain yang disimpan di DB
# ============================================================

_fernet: Fernet | None = None
if platform_cfg.channel_encryption_key:
    try:
        _fernet = Fernet(platform_cfg.channel_encryption_key.encode("utf-8"))
    except Exception:
        logger.error("CHANNEL_ENCRYPTION_KEY tidak valid (harus urlsafe-base64, 32 byte) — enkripsi DINONAKTIFKAN")
        _fernet = None
else:
    logger.warning(
        "CHANNEL_ENCRYPTION_KEY belum diset di .env — kredensial channel akan "
        "disimpan TANPA enkripsi. Generate dgn: "
        "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )


def encrypt_value(plain: str) -> str:
    if not plain:
        return plain
    if _fernet is None:
        return plain
    return "enc:" + _fernet.encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_value(stored: str | None) -> str | None:
    if not stored:
        return stored
    if not stored.startswith("enc:"):
        return stored   # data lama / enkripsi nonaktif — kembalikan apa adanya
    if _fernet is None:
        logger.error("Menemukan nilai terenkripsi tapi CHANNEL_ENCRYPTION_KEY tidak diset — tidak bisa didekripsi")
        return None
    try:
        return _fernet.decrypt(stored[4:].encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.error("Gagal mendekripsi nilai — kemungkinan kunci enkripsi sudah berubah")
        return None


# ============================================================
# AUDIT LOG
# ============================================================

VALID_ACTIONS = {
    "create", "update", "delete", "login", "logout", "login_failed",
    "permission_denied", "export", "invite", "role_change", "plan_change",
    "payment", "security_scan",
}


async def write_audit_log(pool: asyncpg.Pool, *, org_id: str | None, actor_user_id: str | None,
                           actor_email: str | None, action: str, resource_type: str,
                           resource_id: str | None = None, ip_address: str | None = None,
                           user_agent: str | None = None, metadata: dict | None = None) -> None:
    if action not in VALID_ACTIONS:
        action = "update"
    try:
        meta_json = json.dumps(metadata or {})
        await pool.execute(
            """INSERT INTO audit_logs (org_id, actor_user_id, actor_email, action,
                                       resource_type, resource_id, ip_address, user_agent, metadata)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
            str(org_id) if org_id else None,
            str(actor_user_id) if actor_user_id else None,
            actor_email, action, resource_type,
            str(resource_id) if resource_id else None,
            ip_address, user_agent, meta_json,
        )
    except Exception:
        logger.exception("Gagal menulis audit log (action=%s resource=%s)", action, resource_type)


async def list_audit_logs(pool: asyncpg.Pool, *, org_id: str, action: str | None = None,
                          resource_type: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    conditions = ["org_id = $1"]
    params: list = [org_id]
    if action:
        params.append(action)
        conditions.append(f"action = ${len(params)}")
    if resource_type:
        params.append(resource_type)
        conditions.append(f"resource_type = ${len(params)}")
    where = " AND ".join(conditions)
    params.extend([limit, offset])
    rows = await pool.fetch(
        f"""SELECT id, actor_user_id, actor_email, action, resource_type, resource_id,
                   ip_address, metadata, created_at
            FROM audit_logs WHERE {where}
            ORDER BY created_at DESC LIMIT ${len(params)-1} OFFSET ${len(params)}""",
        *params,
    )
    return [dict(r) for r in rows]


# ============================================================
# AUTOMATED SECURITY SCAN
# ============================================================
# Checklist ringan yang bisa dijalankan tiap malam (Celery beat) ATAU
# manual oleh Owner — hasil disimpan sbg audit_log action='security_scan'
# supaya histori bisa ditelusuri di dashboard.

async def run_security_scan(pool: asyncpg.Pool, *, org_id: str) -> dict:
    findings: list[dict] = []

    # 1) API key yang kedaluwarsa / tidak pernah dipakai > 90 hari
    stale_keys = await pool.fetch(
        """SELECT id, name, last_used_at, expires_at FROM api_keys
           WHERE org_id=$1 AND is_active=TRUE
             AND (expires_at IS NOT NULL AND expires_at < NOW()
                  OR (last_used_at IS NULL AND created_at < NOW() - INTERVAL '90 days')
                  OR (last_used_at IS NOT NULL AND last_used_at < NOW() - INTERVAL '90 days'))""",
        org_id,
    )
    for k in stale_keys:
        findings.append({
            "severity": "medium", "category": "api_keys",
            "title": f"API key '{k['name']}' kedaluwarsa atau tidak aktif > 90 hari",
            "recommendation": "Cabut (revoke) API key ini jika tidak lagi digunakan.",
            "resource_id": str(k["id"]),
        })

    # 2) Anggota tim non-aktif yang masih punya role Owner/Admin
    risky_members = await pool.fetch(
        """SELECT u.id, u.email, u.is_active, r.key AS role_key
           FROM users u
           JOIN user_roles ur ON ur.user_id = u.id AND ur.org_id = u.org_id
           JOIN roles r       ON r.id = ur.role_id
           WHERE u.org_id=$1 AND u.is_active=FALSE AND r.key IN ('owner','admin')""",
        org_id,
    )
    for m in risky_members:
        findings.append({
            "severity": "high", "category": "rbac",
            "title": f"User non-aktif '{m['email']}' masih memiliki role '{m['role_key']}'",
            "recommendation": "Cabut role Owner/Admin dari akun yang sudah non-aktif.",
            "resource_id": str(m["id"]),
        })

    # 3) Webhook tanpa HTTPS
    insecure_hooks = await pool.fetch(
        "SELECT id, url FROM webhook_configs WHERE org_id=$1 AND is_active=TRUE AND url NOT ILIKE 'https://%'",
        org_id,
    )
    for h in insecure_hooks:
        findings.append({
            "severity": "high", "category": "webhooks",
            "title": f"Webhook '{h['url']}' tidak memakai HTTPS",
            "recommendation": "Gunakan endpoint HTTPS agar payload (termasuk secret HMAC) tidak bocor di jalur transit.",
            "resource_id": str(h["id"]),
        })

    # 4) Channel account dengan kredensial belum terenkripsi
    if _fernet is None:
        channels = await pool.fetch(
            "SELECT id, channel_type, display_name FROM channel_accounts WHERE org_id=$1 AND is_active=TRUE", org_id,
        )
        for c in channels:
            findings.append({
                "severity": "critical", "category": "encryption",
                "title": f"Kredensial channel '{c['display_name']}' ({c['channel_type']}) tersimpan TANPA enkripsi",
                "recommendation": "Set CHANNEL_ENCRYPTION_KEY di .env lalu sambungkan ulang channel agar token terenkripsi saat disimpan.",
                "resource_id": str(c["id"]),
            })

    # 5) Trial yang akan/sudah berakhir tanpa metode pembayaran
    sub = await pool.fetchrow(
        "SELECT status, trial_ends_at FROM subscriptions WHERE org_id=$1", org_id,
    )
    if sub and sub["status"] == "trialing" and sub["trial_ends_at"] and sub["trial_ends_at"] < datetime.now(timezone.utc) + timedelta(days=3):
        findings.append({
            "severity": "low", "category": "billing",
            "title": "Masa trial akan segera berakhir",
            "recommendation": "Upgrade ke paket berbayar agar layanan tidak terganggu (lihat /billing/checkout).",
            "resource_id": None,
        })

    score = max(0, 100 - sum({"critical": 30, "high": 15, "medium": 7, "low": 2}.get(f["severity"], 5) for f in findings))
    result = {
        "org_id": org_id, "scanned_at": datetime.now(timezone.utc).isoformat(),
        "score": score, "findings_count": len(findings), "findings": findings,
    }
    await write_audit_log(pool, org_id=org_id, actor_user_id=None, actor_email="system",
                          action="security_scan", resource_type="organization", resource_id=org_id,
                          metadata={"score": score, "findings_count": len(findings)})
    return result


# ============================================================
# ROUTER
# ============================================================

def build_security_router(*, get_pool: GetPool, get_current_user: GetCurrentUser,
                           require_permission) -> APIRouter:
    router = APIRouter(prefix="/security", tags=["security"])

    @router.get("/audit-logs")
    async def get_audit_logs(
        user: Annotated[dict, Depends(require_permission("audit.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        action: str | None = None, resource_type: str | None = None,
        limit: int = 50, offset: int = 0,
    ):
        return {"logs": await list_audit_logs(pool, org_id=user["org_id"], action=action,
                                               resource_type=resource_type, limit=limit, offset=offset)}

    @router.post("/scan")
    async def trigger_scan(
        user: Annotated[dict, Depends(require_permission("audit.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        _check_rate_limit(user["org_id"], 5)   # maks 5 scan/menit
        return await run_security_scan(pool, org_id=user["org_id"])

    # ── API Key management lanjutan (list/revoke + scopes) ──────
    # Pembuatan key tetap lewat POST /api-keys existing di main.py
    # (sudah menangani plan-gating & hashing) — di sini kita tambah
    # visibilitas (list tanpa expose hash) & pencabutan + scope granular.
    @router.get("/api-keys")
    async def list_api_keys(
        user: Annotated[dict, Depends(require_permission("apikeys.manage"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        rows = await pool.fetch(
            """SELECT id, name, key_prefix, scopes, last_used_at, expires_at, is_active, created_at
               FROM api_keys WHERE org_id=$1 ORDER BY created_at DESC""",
            user["org_id"],
        )
        return {"api_keys": [dict(r) for r in rows]}

    @router.patch("/api-keys/{key_id}/scopes")
    async def update_api_key_scopes(
        key_id: str, body: dict,
        user: Annotated[dict, Depends(require_permission("apikeys.manage"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        scopes = body.get("scopes")
        if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Body harus berisi `scopes`: daftar string, mis. ['chat:write','analytics:read']")
        row = await pool.fetchrow(
            "UPDATE api_keys SET scopes=$1 WHERE id=$2 AND org_id=$3 RETURNING id, name, scopes",
            scopes, key_id, user["org_id"],
        )
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "API key tidak ditemukan")
        await write_audit_log(pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
                              action="update", resource_type="api_key", resource_id=key_id,
                              metadata={"scopes": scopes})
        return {"api_key": dict(row)}

    @router.delete("/api-keys/{key_id}")
    async def revoke_api_key(
        key_id: str,
        user: Annotated[dict, Depends(require_permission("apikeys.manage"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        result = await pool.execute(
            "UPDATE api_keys SET is_active=FALSE WHERE id=$1 AND org_id=$2", key_id, user["org_id"],
        )
        if not (isinstance(result, str) and result.endswith(" 1")):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "API key tidak ditemukan")
        await write_audit_log(pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
                              action="delete", resource_type="api_key", resource_id=key_id, metadata={})
        return {"ok": True}

    return router
