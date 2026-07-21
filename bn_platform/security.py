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
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Annotated, Awaitable, Callable

import asyncpg
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request, status

from .config import cfg as platform_cfg
from .observability import record_audit_log_failure

from platform_state import get_state_store   # P0-A C3: shared-state rate limiter

import security_agent as sec_agent

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

# P0-A C3: state rate-limit dipindah ke platform_state.StateStore — default
# in-process (perilaku & pesan 429 identik), atau lintas-worker via
# STATE_BACKEND=redis. `_check_rate_limit` kini ASYNC (semua pemanggil di-await).


async def _check_rate_limit(key: str, max_req: int = _ORG_MAX_REQUESTS, *,
                            window_s: int = _ORG_WINDOW_SECS) -> None:
    """Sliding-window rate limiter per key. Raises 429 bila melewati batas.
    Backend via platform_state (default in-process; opsional Redis lintas-worker).
    Slot TIDAK dikonsumsi saat ditolak (identik dengan versi lama)."""
    allowed, _count = await get_state_store().rate_incr(
        f"rl:{key}", window_s=window_s, limit=max_req)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Terlalu banyak request. Batas: {max_req} req/{window_s}s. Coba lagi sebentar.",
            headers={"Retry-After": str(window_s)},
        )

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
        record_audit_log_failure()
        logger.exception(
            "Gagal menulis audit log (action=%s resource_type=%s resource_id=%s org_id=%s actor_user_id=%s)",
            action, resource_type, resource_id, org_id, actor_user_id,
        )


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
# SESSION MANAGEMENT
# ============================================================
# Token JWT tetap stateless (lihat main.py create_token/get_current_user),
# tapi setiap login membuat baris `sessions` yang menyimpan klaim `sid`
# milik JWT tsb. get_current_user memvalidasi sesi ini (revoked_at IS NULL
# & belum expired) supaya logout/"revoke session" benar2 mencabut akses —
# bukan cuma menghapus token di sisi client. Token lama (tanpa klaim `sid`,
# diterbitkan sebelum fitur ini) tetap diterima sampai expired (no `sid`
# => skip pengecekan sesi, lihat main.py get_current_user).

SUSPICIOUS_LOGIN_WINDOW_DAYS = 30


async def create_session(pool: asyncpg.Pool, *, user_id: str, org_id: str,
                          ip_address: str | None, user_agent: str | None,
                          expires_at: datetime) -> dict:
    """Buat baris sesi baru & deteksi login mencurigakan (IP baru yang belum
    pernah dipakai user ini dalam SUSPICIOUS_LOGIN_WINDOW_DAYS terakhir).
    Return {"id", "is_suspicious"}."""
    is_suspicious = False
    if ip_address:
        prior = await pool.fetch(
            f"""SELECT DISTINCT ip_address FROM sessions
                WHERE user_id=$1 AND ip_address IS NOT NULL
                  AND created_at > NOW() - INTERVAL '{SUSPICIOUS_LOGIN_WINDOW_DAYS} days'""",
            user_id,
        )
        known_ips = {r["ip_address"] for r in prior}
        if known_ips and ip_address not in known_ips:
            is_suspicious = True
    row = await pool.fetchrow(
        """INSERT INTO sessions (user_id, org_id, ip_address, user_agent, is_suspicious, expires_at)
           VALUES ($1,$2,$3,$4,$5,$6) RETURNING id, is_suspicious""",
        user_id, org_id, ip_address, user_agent, is_suspicious, expires_at,
    )
    return dict(row)


async def touch_session(pool: asyncpg.Pool, session_id: str) -> bool:
    """Update last_seen_at. Return False jika sesi sudah dicabut/expired/tidak ada
    — dipanggil dari get_current_user untuk menolak token yang sesinya direvoke."""
    row = await pool.fetchrow(
        """UPDATE sessions SET last_seen_at=NOW()
           WHERE id=$1 AND revoked_at IS NULL AND expires_at > NOW()
           RETURNING id""",
        session_id,
    )
    return row is not None


async def list_sessions(pool: asyncpg.Pool, *, org_id: str, user_id: str | None = None,
                         active_only: bool = True) -> list[dict]:
    conditions = ["s.org_id=$1"]
    params: list = [org_id]
    if user_id:
        params.append(user_id)
        conditions.append(f"s.user_id=${len(params)}")
    if active_only:
        conditions.append("s.revoked_at IS NULL AND s.expires_at > NOW()")
    where = " AND ".join(conditions)
    rows = await pool.fetch(
        f"""SELECT s.id, s.user_id, u.email AS user_email, s.ip_address, s.user_agent,
                   s.is_suspicious, s.created_at, s.last_seen_at, s.expires_at, s.revoked_at
            FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE {where}
            ORDER BY s.last_seen_at DESC""",
        *params,
    )
    return [dict(r) for r in rows]


async def revoke_session(pool: asyncpg.Pool, *, session_id: str, org_id: str,
                          reason: str = "manual") -> dict | None:
    row = await pool.fetchrow(
        """UPDATE sessions SET revoked_at=NOW(), revoked_reason=$1
           WHERE id=$2 AND org_id=$3 AND revoked_at IS NULL
           RETURNING id, user_id""",
        reason, session_id, org_id,
    )
    return dict(row) if row else None


async def list_security_events(pool: asyncpg.Pool, *, org_id: str, limit: int = 20) -> list[dict]:
    """Ringkasan kejadian keamanan utk Security Dashboard: login gagal,
    permission denied, login mencurigakan, & riwayat security scan."""
    rows = await pool.fetch(
        """SELECT id, actor_email, action, resource_type, resource_id, ip_address, metadata, created_at
           FROM audit_logs
           WHERE org_id=$1 AND (action IN ('login_failed', 'permission_denied', 'security_scan')
                                 OR (action='login' AND metadata->>'suspicious'='true'))
           ORDER BY created_at DESC LIMIT $2""",
        org_id, limit,
    )
    return [dict(r) for r in rows]


# ============================================================
# API KEY: generation, authentication, rotation, usage tracking
# ============================================================

def generate_api_key() -> tuple[str, str]:
    """Buat raw API key baru + prefix-nya (utk display di UI)."""
    raw = f"bn_live_{os.urandom(20).hex()}"
    return raw, raw[:14]


async def record_api_key_usage(pool: asyncpg.Pool, key_id: str) -> None:
    await pool.execute(
        "UPDATE api_keys SET last_used_at=NOW(), usage_count=usage_count+1 WHERE id=$1",
        key_id,
    )


async def authenticate_api_key(pool: asyncpg.Pool, raw_key: str, *, verify_password) -> dict | None:
    """Validasi raw API key terhadap key_hash tersimpan. Cek is_active &
    expires_at. Jika valid, catat usage (last_used_at + usage_count) &
    kembalikan {"id","org_id","scopes"}. None jika tidak valid/kedaluwarsa."""
    if not raw_key or not raw_key.startswith("bn_live_"):
        return None
    prefix = raw_key[:14]
    rows = await pool.fetch(
        "SELECT id, org_id, key_hash, scopes, is_active, expires_at FROM api_keys WHERE key_prefix=$1",
        prefix,
    )
    now = datetime.now(timezone.utc)
    for row in rows:
        if not row["is_active"]:
            continue
        if row["expires_at"] and row["expires_at"] < now:
            continue
        if verify_password(raw_key, row["key_hash"]):
            await record_api_key_usage(pool, row["id"])
            return {"id": str(row["id"]), "org_id": str(row["org_id"]), "scopes": list(row["scopes"] or [])}
    return None


async def rotate_api_key(pool: asyncpg.Pool, *, key_id: str, org_id: str, hash_password) -> str | None:
    """Ganti key_hash/key_prefix dengan key baru (rotasi) & reset usage_count.
    Return raw key baru (hanya ditampilkan sekali) atau None jika key tidak ditemukan."""
    raw_key, prefix = generate_api_key()
    row = await pool.fetchrow(
        """UPDATE api_keys SET key_hash=$1, key_prefix=$2, rotated_at=NOW(), usage_count=0, last_used_at=NULL
           WHERE id=$3 AND org_id=$4 RETURNING id""",
        hash_password(raw_key), prefix, key_id, org_id,
    )
    if not row:
        return None
    return raw_key


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

    # 6) Login mencurigakan (IP baru) dalam 7 hari terakhir
    suspicious = await pool.fetch(
        """SELECT s.id, u.email FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.org_id=$1 AND s.is_suspicious=TRUE AND s.created_at > NOW() - INTERVAL '7 days'""",
        org_id,
    )
    for s in suspicious:
        findings.append({
            "severity": "medium", "category": "sessions",
            "title": f"Login mencurigakan dari IP baru untuk akun '{s['email']}'",
            "recommendation": "Konfirmasi ke pengguna apakah login ini sah. Jika tidak, cabut sesi tersebut & ganti password.",
            "resource_id": str(s["id"]),
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
                           require_permission, hash_password,
                           get_agent_config: Callable[[], dict] | None = None) -> APIRouter:
    router = APIRouter(prefix="/security", tags=["security"])
    cfg = get_agent_config() if get_agent_config else {}
    agent = sec_agent.SecurityAgent(api_key=cfg.get("api_key"), model=cfg.get("model"),
                                     base_url=cfg.get("base_url"), deepseek_api_key=cfg.get("deepseek_api_key", ""), openrouter_api_key=cfg.get("openrouter_api_key", ""), app_url=cfg.get("app_url", "https://botnesia.id"))

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
        await _check_rate_limit(user["org_id"], 5)   # maks 5 scan/menit
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
            """SELECT id, name, key_prefix, scopes, usage_count, last_used_at, rotated_at,
                      expires_at, is_active, created_at
               FROM api_keys WHERE org_id=$1 ORDER BY created_at DESC""",
            user["org_id"],
        )
        return {"api_keys": [dict(r) for r in rows]}

    @router.post("/api-keys/{key_id}/rotate")
    async def rotate_api_key_route(
        key_id: str,
        user: Annotated[dict, Depends(require_permission("apikeys.manage"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        raw_key = await rotate_api_key(pool, key_id=key_id, org_id=user["org_id"], hash_password=hash_password)
        if not raw_key:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "API key tidak ditemukan")
        await write_audit_log(pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
                              action="update", resource_type="api_key", resource_id=key_id,
                              metadata={"rotated": True})
        return {"key": raw_key, "note": "Simpan key baru ini — hanya ditampilkan sekali. Key lama langsung tidak berlaku."}

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

    # ── Session management ──────────────────────────────────────
    @router.get("/sessions")
    async def get_sessions(
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        scope: str = "me",
    ):
        if scope == "org":
            await require_permission("audit.read")(user=user, pool=pool)
            sessions = await list_sessions(pool, org_id=user["org_id"])
        else:
            sessions = await list_sessions(pool, org_id=user["org_id"], user_id=user["id"])
        return {"sessions": sessions}

    @router.post("/sessions/{session_id}/revoke")
    async def revoke_session_route(
        session_id: str,
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        target = await pool.fetchrow(
            "SELECT user_id FROM sessions WHERE id=$1 AND org_id=$2", session_id, user["org_id"],
        )
        if not target:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Sesi tidak ditemukan")
        if str(target["user_id"]) != str(user["id"]):
            # Mencabut sesi milik anggota tim lain butuh izin team.manage
            await require_permission("team.manage")(user=user, pool=pool)
        result = await revoke_session(pool, session_id=session_id, org_id=user["org_id"], reason="revoked_by_user")
        if not result:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Sesi sudah dicabut sebelumnya")
        await write_audit_log(pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
                              action="update", resource_type="session", resource_id=session_id,
                              metadata={"revoked_user_id": str(target["user_id"]), "reason": "revoked_by_user"})
        return {"ok": True}

    # ── Security Dashboard ──────────────────────────────────────
    @router.get("/dashboard")
    async def security_dashboard(
        user: Annotated[dict, Depends(require_permission("audit.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        sessions = await list_sessions(pool, org_id=user["org_id"])
        audit_logs = await list_audit_logs(pool, org_id=user["org_id"], limit=10)
        security_events = await list_security_events(pool, org_id=user["org_id"], limit=10)
        api_key_rows = await pool.fetch(
            """SELECT id, name, key_prefix, scopes, usage_count, last_used_at, rotated_at,
                      expires_at, is_active, created_at
               FROM api_keys WHERE org_id=$1 ORDER BY created_at DESC""",
            user["org_id"],
        )
        api_keys = [dict(r) for r in api_key_rows]
        risk = await sec_agent.dashboard_summary(pool, user["org_id"])
        return {
            "active_sessions": sessions,
            "active_sessions_count": len(sessions),
            "suspicious_sessions_count": sum(1 for s in sessions if s["is_suspicious"]),
            "audit_logs": audit_logs,
            "security_events": security_events,
            "api_keys": api_keys,
            "active_api_keys_count": sum(1 for k in api_keys if k["is_active"]),
            "score": risk["score"],
            "risk_level": risk["risk_level"],
            "open_security_alerts_by_severity": risk["open_alerts_by_severity"],
        }

    # ── AI Workforce Phase 5: lapisan tipis di atas run_security_scan ──
    # (deteksi API abuse & tenant isolation BARU + alert persisten lewat
    # ops_alerts/ops_reports yang sudah ada dari Operations Agent)
    @router.post("/scan-and-alert")
    async def scan_and_alert(
        user: Annotated[dict, Depends(require_permission("security.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        await _check_rate_limit(f"security-scan-alert:{org_id}", 5)
        scan_result = await run_security_scan(pool, org_id=org_id)
        api_abuse = await sec_agent.detect_api_abuse(pool, org_id)
        isolation_violations = await sec_agent.check_tenant_isolation(pool, org_id)
        created = await sec_agent.sync_alerts_from_scan(pool, org_id, scan_result, api_abuse, isolation_violations)
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="security_scan", resource_type="organization", resource_id=org_id,
            metadata={"alerts_created": len(created), "api_abuse_count": len(api_abuse),
                      "isolation_violations": len(isolation_violations)},
        )
        return {
            "scan": scan_result, "api_abuse": api_abuse,
            "tenant_isolation_violations": isolation_violations, "alerts_created": created,
        }

    @router.get("/risk-alerts")
    async def list_risk_alerts(
        user: Annotated[dict, Depends(require_permission("security.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        status_filter: str | None = None,
        limit: int = 50,
    ):
        org_id = user["org_id"]
        limit = max(1, min(limit, 200))
        if status_filter:
            rows = await pool.fetch(
                "SELECT * FROM ops_alerts WHERE org_id=$1 AND source='security' AND status=$2 ORDER BY created_at DESC LIMIT $3",
                org_id, status_filter, limit,
            )
        else:
            rows = await pool.fetch(
                "SELECT * FROM ops_alerts WHERE org_id=$1 AND source='security' ORDER BY created_at DESC LIMIT $2",
                org_id, limit,
            )
        return {"alerts": [dict(r) for r in rows]}

    @router.patch("/risk-alerts/{alert_id}")
    async def update_risk_alert(
        alert_id: str, body: dict,
        user: Annotated[dict, Depends(require_permission("security.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        new_status = body.get("status")
        try:
            row = await sec_agent.update_alert_status(pool, org_id=user["org_id"], alert_id=alert_id,
                                                        status=new_status, actor_id=user["id"])
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert tidak ditemukan")
        await write_audit_log(
            pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="ops_alert", resource_id=alert_id, metadata={"status": new_status},
        )
        return row

    @router.get("/reports")
    async def list_security_reports(
        user: Annotated[dict, Depends(require_permission("security.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        report_type: str | None = None,
        limit: int = 20,
    ):
        org_id = user["org_id"]
        limit = max(1, min(limit, 100))
        if report_type:
            rows = await pool.fetch(
                "SELECT id, org_id, report_type, period_start, period_end, summary, created_at FROM ops_reports "
                "WHERE org_id=$1 AND source='security' AND report_type=$2 ORDER BY created_at DESC LIMIT $3",
                org_id, report_type, limit,
            )
        else:
            rows = await pool.fetch(
                "SELECT id, org_id, report_type, period_start, period_end, summary, created_at FROM ops_reports "
                "WHERE org_id=$1 AND source='security' ORDER BY created_at DESC LIMIT $2",
                org_id, limit,
            )
        return {"reports": [dict(r) for r in rows]}

    @router.post("/reports/generate", status_code=201)
    async def generate_security_report_route(
        body: dict,
        user: Annotated[dict, Depends(require_permission("security.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        await _check_rate_limit(f"security-report:{org_id}", 5)
        try:
            report = await sec_agent.generate_security_report(
                pool, org_id, body.get("report_type"), generated_by=user["id"], agent=agent,
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="create", resource_type="ops_report", resource_id=report["id"],
            metadata={"report_type": body.get("report_type"), "source": "security"},
        )
        return _security_report_out(report)

    @router.get("/reports/{report_id}")
    async def get_security_report(
        report_id: str,
        user: Annotated[dict, Depends(require_permission("security.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        row = await pool.fetchrow(
            "SELECT * FROM ops_reports WHERE id=$1 AND org_id=$2 AND source='security'", report_id, user["org_id"],
        )
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Laporan tidak ditemukan")
        return _security_report_out(dict(row))

    return router


def _security_report_out(row: dict) -> dict:
    out = dict(row)
    if isinstance(out.get("data"), str):
        try:
            out["data"] = json.loads(out["data"])
        except Exception:
            out["data"] = {}
    return out
