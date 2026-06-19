"""
bn_platform/rbac.py — Role-Based Access Control

5 role baku: Owner, Admin, Manager, Agent, Viewer (lihat schema_platform.sql
§1 & §11 untuk seed data role+permission). Role disimpan sebagai baris
`roles` dengan org_id NULL (role sistem, dipakai bersama semua tenant);
penugasan ke user dicatat di `user_roles` (mendukung multi-role per user).

MIGRASI HALUS dari skema lama: kolom `users.role` (TEXT bebas:
'owner'|'admin'|'member') TETAP ada & tetap diisi saat register (lihat
main.py /auth/register) — tidak kita hapus. RBAC baru membaca dari
`user_roles`; kalau user belum punya baris di sana (user lama / migrasi
belum jalan), `_legacy_role_key()` memetakan `users.role` lama ke role
sistem baru secara on-the-fly DAN menuliskannya ke `user_roles` (lazy
migration — sekali jalan per user, tidak perlu skrip migrasi data masal).

Pemakaian di main.py (lihat ARCHITECTURE.md §5 utk detail wiring):

    from bn_platform.rbac import build_rbac_router, make_permission_checker

    require_permission = make_permission_checker(get_current_user=get_current_user, get_pool=get_pool)
    app.include_router(build_rbac_router(get_pool=get_pool, get_current_user=get_current_user))

    @app.post("/bots")
    async def create_bot(..., user=Depends(require_permission("bots.write"))):
        ...
"""
# from __future__ import annotations  # dihapus: menyebabkan Depends(closure_var) gagal di-resolve oleh FastAPI get_type_hints()

import json
import logging
import uuid
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

logger = logging.getLogger("bn_platform.rbac")

# ============================================================
# PERMISSION CATALOG — HARUS sinkron dengan seed di schema_platform.sql §11
# ============================================================

PERMISSIONS: dict[str, str] = {
    "bots.read":           "Melihat daftar & konfigurasi bot",
    "bots.write":          "Membuat & mengubah bot",
    "bots.delete":         "Menghapus bot",
    "conversations.read":  "Melihat percakapan & inbox",
    "conversations.reply": "Membalas percakapan (human handoff)",
    "conversations.assign":"Menugaskan percakapan ke agent lain",
    "knowledge.read":      "Melihat dokumen knowledge base",
    "knowledge.write":     "Mengunggah/menghapus dokumen knowledge base",
    "analytics.read":      "Melihat dashboard analitik & laporan",
    "billing.read":        "Melihat invoice, riwayat pembayaran, status langganan",
    "billing.manage":      "Mengubah paket langganan & metode pembayaran",
    "team.read":           "Melihat anggota tim & role",
    "team.manage":         "Mengundang, menghapus, mengubah role anggota tim",
    "settings.manage":     "Mengubah pengaturan organisasi, channel, integrasi",
    "apikeys.manage":      "Membuat & mencabut API key",
    "audit.read":          "Melihat audit log",
    "marketplace.install": "Memasang template dari marketplace",
    "finance.read":        "Melihat invoice, expense, dan laporan keuangan tenant",
    "finance.write":       "Membuat/mengubah invoice, expense, dan pembayaran tenant",
    "finance.approve":     "Menyetujui/menolak expense dan keputusan keuangan penting",
    "marketing.read":      "Melihat campaign, konten, kalender, dan analitik marketing",
    "marketing.write":     "Membuat/mengubah campaign, konten, dan menjadwalkan publikasi",
    "marketing.approve":   "Menyetujui konten sebelum dipublikasikan",
    "hr.read":             "Melihat data kandidat, karyawan, evaluasi, dan training",
    "hr.write":            "Membuat/mengubah kandidat, karyawan, dan rencana training",
    "hr.approve":          "Menyetujui (finalisasi) evaluasi karyawan",
    "operations.read":     "Melihat health score, alert, dan laporan operasional",
    "operations.write":    "Menjalankan scan operasional dan menindaklanjuti alert",
    "security.read":       "Melihat risk level, security alert, dan laporan keamanan",
    "security.write":      "Menjalankan security scan dan menindaklanjuti security alert",
    "executive.read":      "Melihat company health score dan executive brief",
    "executive.write":     "Membuat executive brief (sintesis lintas-agent)",
    "workforce.read":      "Melihat task koordinasi lintas-agent AI Workforce",
    "workforce.write":     "Membuat/mengubah task koordinasi lintas-agent",
    "workforce.approve":   "Menyetujui task yang butuh human approval",
    "learning.read":       "Melihat insight organizational memory (Self-Learning Company)",
    "learning.write":      "Menjalankan learning scan (membuat insight kandidat)",
    "learning.approve":    "Menyetujui/menolak insight yang akan memengaruhi jawaban bot",
}

# Role sistem -> daftar permission (cermin dari seed role_permissions di SQL;
# dipakai sebagai fallback in-memory bila DB belum ter-seed, mis. saat test)
SYSTEM_ROLE_PERMISSIONS: dict[str, set[str]] = {
    "owner":   set(PERMISSIONS.keys()),
    "admin":   set(PERMISSIONS.keys()) - {"billing.manage", "bots.delete"},
    "manager": {
        "bots.read", "conversations.read", "conversations.reply",
        "conversations.assign", "knowledge.read", "analytics.read",
        "team.read", "billing.read", "finance.read", "finance.write",
        "marketing.read", "marketing.write", "hr.read", "hr.write",
        "operations.read", "operations.write", "workforce.read", "workforce.write",
        "learning.read", "learning.write",
    },
    "agent":   {"bots.read", "conversations.read", "conversations.reply", "knowledge.read"},
    "viewer":  {"bots.read", "conversations.read", "analytics.read", "knowledge.read", "finance.read", "marketing.read", "operations.read", "workforce.read", "learning.read"},
}

ROLE_ORDER = ["owner", "admin", "manager", "agent", "viewer"]


def _legacy_role_key(legacy_role: str | None) -> str:
    """Petakan users.role lama (free-text) ke role sistem RBAC baru."""
    legacy = (legacy_role or "").strip().lower()
    if legacy in SYSTEM_ROLE_PERMISSIONS:
        return legacy
    if legacy in ("member", "staff", "employee"):
        return "agent"
    if legacy in ("owner", "founder", "ceo"):
        return "owner"
    if legacy in ("admin", "administrator"):
        return "admin"
    return "viewer"   # default paling aman (least privilege)


# ============================================================
# REPOSITORY — akses data RBAC
# ============================================================

async def _get_or_assign_role_id(pool: asyncpg.Pool, user_id: str, org_id: str, role_key: str) -> str | None:
    row = await pool.fetchrow(
        "SELECT id FROM roles WHERE org_id IS NULL AND key=$1", role_key,
    )
    if not row:
        return None
    role_id = row["id"]
    await pool.execute(
        """INSERT INTO user_roles (user_id, role_id, org_id)
           VALUES ($1, $2, $3) ON CONFLICT (user_id, role_id) DO NOTHING""",
        user_id, role_id, org_id,
    )
    return role_id


async def get_user_permissions(pool: asyncpg.Pool, user_id: str, org_id: str) -> set[str]:
    """Kumpulkan semua permission user (gabungan dari semua role yang dimiliki)."""
    rows = await pool.fetch(
        """SELECT DISTINCT p.key
           FROM user_roles ur
           JOIN role_permissions rp ON rp.role_id = ur.role_id
           JOIN permissions p       ON p.id = rp.permission_id
           WHERE ur.user_id = $1 AND ur.org_id = $2""",
        user_id, org_id,
    )
    if rows:
        return {r["key"] for r in rows}

    # Lazy migration: user belum punya baris user_roles — petakan dari users.role lama
    urow = await pool.fetchrow("SELECT role FROM users WHERE id=$1 AND org_id=$2", user_id, org_id)
    if not urow:
        return set()
    role_key = _legacy_role_key(urow["role"])
    role_id = await _get_or_assign_role_id(pool, user_id, org_id, role_key)
    if role_id:
        rows = await pool.fetch(
            """SELECT p.key FROM role_permissions rp
               JOIN permissions p ON p.id = rp.permission_id
               WHERE rp.role_id = $1""",
            role_id,
        )
        if rows:
            return {r["key"] for r in rows}
    # Fallback total (DB belum ter-seed): pakai mapping in-memory
    return set(SYSTEM_ROLE_PERMISSIONS.get(role_key, SYSTEM_ROLE_PERMISSIONS["viewer"]))


async def get_user_roles(pool: asyncpg.Pool, user_id: str, org_id: str) -> list[dict]:
    rows = await pool.fetch(
        """SELECT r.id, r.key, r.name, r.description, r.is_system
           FROM user_roles ur JOIN roles r ON r.id = ur.role_id
           WHERE ur.user_id = $1 AND ur.org_id = $2
           ORDER BY r.key""",
        user_id, org_id,
    )
    if rows:
        return [dict(r) for r in rows]
    # trigger lazy migration lalu coba lagi sekali
    await get_user_permissions(pool, user_id, org_id)
    rows = await pool.fetch(
        """SELECT r.id, r.key, r.name, r.description, r.is_system
           FROM user_roles ur JOIN roles r ON r.id = ur.role_id
           WHERE ur.user_id = $1 AND ur.org_id = $2
           ORDER BY r.key""",
        user_id, org_id,
    )
    return [dict(r) for r in rows]


async def assign_role(pool: asyncpg.Pool, *, user_id: str, org_id: str, role_key: str) -> bool:
    if role_key not in SYSTEM_ROLE_PERMISSIONS:
        # bisa jadi custom role milik tenant ini
        row = await pool.fetchrow("SELECT id FROM roles WHERE org_id=$1 AND key=$2", org_id, role_key)
    else:
        row = await pool.fetchrow("SELECT id FROM roles WHERE org_id IS NULL AND key=$1", role_key)
    if not row:
        return False
    await pool.execute(
        """INSERT INTO user_roles (user_id, role_id, org_id) VALUES ($1, $2, $3)
           ON CONFLICT (user_id, role_id) DO NOTHING""",
        user_id, row["id"], org_id,
    )
    return True


async def revoke_role(pool: asyncpg.Pool, *, user_id: str, org_id: str, role_key: str) -> bool:
    result = await pool.execute(
        """DELETE FROM user_roles ur USING roles r
           WHERE ur.role_id = r.id AND ur.user_id=$1 AND ur.org_id=$2 AND r.key=$3""",
        user_id, org_id, role_key,
    )
    return result.endswith(" 1") if isinstance(result, str) else False


async def list_roles_with_permissions(pool: asyncpg.Pool, org_id: str) -> list[dict]:
    rows = await pool.fetch(
        """SELECT r.id, r.key, r.name, r.description, r.is_system,
                  COALESCE(array_agg(p.key ORDER BY p.key) FILTER (WHERE p.key IS NOT NULL), '{}') AS permissions
           FROM roles r
           LEFT JOIN role_permissions rp ON rp.role_id = r.id
           LEFT JOIN permissions p       ON p.id = rp.permission_id
           WHERE r.org_id IS NULL OR r.org_id = $1
           GROUP BY r.id
           ORDER BY r.is_system DESC, r.key""",
        org_id,
    )
    return [dict(r) for r in rows]


# ============================================================
# FASTAPI DEPENDENCY FACTORIES
# ============================================================
# Pola factory dipakai di seluruh bn_platform supaya TIDAK ada
# `from main import ...` di top-level modul (mencegah circular import —
# main.py mengimpor router2 bn_platform, jadi bn_platform tidak boleh
# balik mengimpor main.py).

GetCurrentUser = Callable[..., Awaitable[dict]]
GetPool        = Callable[..., Awaitable[asyncpg.Pool]]


def make_permission_checker(*, get_current_user: GetCurrentUser, get_pool: GetPool):
    """
    Hasilkan dependency-factory `require_permission(key)` yang dipakai di
    setiap endpoint yang butuh otorisasi granular:

        @app.delete("/bots/{id}")
        async def delete_bot(..., user=Depends(require_permission("bots.delete"))):
    """

    def require_permission(permission_key: str):
        if permission_key not in PERMISSIONS:
            raise ValueError(f"Permission tidak dikenal: {permission_key}")

        async def _checker(
            user: Annotated[dict, Depends(get_current_user)],
            pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        ) -> dict:
            perms = await get_user_permissions(pool, user["id"], user["org_id"])
            if permission_key not in perms and "*" not in perms:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    f"Akun Anda tidak memiliki izin '{permission_key}' untuk aksi ini.",
                )
            return user

        return _checker

    return require_permission


# ============================================================
# ROUTER — manajemen role & penugasan tim
# ============================================================

class AssignRoleReq(BaseModel):
    user_id:  str
    role_key: str


class RevokeRoleReq(BaseModel):
    user_id:  str
    role_key: str


class InviteMemberReq(BaseModel):
    email: str
    full_name: str | None = None
    role_key: str = "agent"
    password: str = Field(min_length=8, max_length=128)


def build_rbac_router(*, get_pool: GetPool, get_current_user: GetCurrentUser, hash_password, check_limit=None) -> APIRouter:
    require_permission = make_permission_checker(get_current_user=get_current_user, get_pool=get_pool)
    router = APIRouter(prefix="/rbac", tags=["rbac"])

    @router.get("/permissions")
    async def list_permissions(user=Depends(get_current_user)):
        return {"permissions": [{"key": k, "description": v} for k, v in PERMISSIONS.items()]}

    @router.get("/roles")
    async def list_roles(
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        return {"roles": await list_roles_with_permissions(pool, user["org_id"])}

    @router.get("/me")
    async def my_roles_permissions(
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        roles = await get_user_roles(pool, user["id"], user["org_id"])
        perms = await get_user_permissions(pool, user["id"], user["org_id"])
        return {"user_id": user["id"], "roles": roles, "permissions": sorted(perms)}

    @router.get("/team")
    async def team_roles(
        user: Annotated[dict, Depends(require_permission("team.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        rows = await pool.fetch(
            """SELECT u.id, u.email, u.full_name, u.is_active, u.last_login_at,
                      COALESCE(array_agg(r.key ORDER BY r.key) FILTER (WHERE r.key IS NOT NULL), '{}') AS roles
               FROM users u
               LEFT JOIN user_roles ur ON ur.user_id = u.id AND ur.org_id = u.org_id
               LEFT JOIN roles r       ON r.id = ur.role_id
               WHERE u.org_id = $1
               GROUP BY u.id
               ORDER BY u.created_at""",
            user["org_id"],
        )
        # pastikan tiap anggota sudah punya pemetaan role (lazy migration)
        for r in rows:
            if not r["roles"]:
                await get_user_permissions(pool, str(r["id"]), user["org_id"])
        if any(not r["roles"] for r in rows):
            rows = await pool.fetch(
                """SELECT u.id, u.email, u.full_name, u.is_active, u.last_login_at,
                          COALESCE(array_agg(r.key ORDER BY r.key) FILTER (WHERE r.key IS NOT NULL), '{}') AS roles
                   FROM users u
                   LEFT JOIN user_roles ur ON ur.user_id = u.id AND ur.org_id = u.org_id
                   LEFT JOIN roles r       ON r.id = ur.role_id
                   WHERE u.org_id = $1
                   GROUP BY u.id
                   ORDER BY u.created_at""",
                user["org_id"],
            )
        return {"team": [dict(r) for r in rows]}

    @router.post("/invite", status_code=status.HTTP_201_CREATED)
    async def invite_member_route(
        body: InviteMemberReq,
        user: Annotated[dict, Depends(require_permission("team.manage"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        email = body.email.strip().lower()
        if body.role_key not in SYSTEM_ROLE_PERMISSIONS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Role tidak valid")
        if check_limit:
            ok, detail = await check_limit(pool, user["org_id"], "users")
            if not ok:
                raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, f"Limit user paket {detail['plan']} tercapai ({detail['used']}/{detail['limit']})")
        existing = await pool.fetchrow("SELECT id FROM users WHERE lower(email)=$1", email)
        if existing:
            raise HTTPException(status.HTTP_409_CONFLICT, "Email sudah terdaftar")
        user_id = str(uuid.uuid4())
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """INSERT INTO users (id, org_id, email, hashed_password, full_name, role)
                       VALUES ($1,$2,$3,$4,$5,$6)""",
                    user_id, user["org_id"], email, hash_password(body.password), body.full_name, body.role_key,
                )
                ok = await assign_role(conn, user_id=user_id, org_id=user["org_id"], role_key=body.role_key)
                if not ok:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Role tidak ditemukan")
                await conn.execute(
                    """INSERT INTO audit_logs (org_id, actor_user_id, actor_email, action, resource_type, resource_id, metadata)
                       VALUES ($1,$2,$3,'invite','user',$4,$5)""",
                    user["org_id"], user["id"], user.get("email"), user_id,
                    json.dumps({"email": email, "role": body.role_key}),
                )
        return {"ok": True, "user_id": user_id, "email": email, "role_key": body.role_key}

    @router.post("/assign", status_code=status.HTTP_200_OK)
    async def assign_role_route(
        body: AssignRoleReq,
        user: Annotated[dict, Depends(require_permission("team.manage"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        target = await pool.fetchrow("SELECT id FROM users WHERE id=$1 AND org_id=$2", body.user_id, user["org_id"])
        if not target:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User tidak ditemukan di organisasi ini")
        ok = await assign_role(pool, user_id=body.user_id, org_id=user["org_id"], role_key=body.role_key)
        if not ok:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Role '{body.role_key}' tidak ditemukan")
        await pool.execute(
            """INSERT INTO audit_logs (org_id, actor_user_id, actor_email, action, resource_type, resource_id, metadata)
               VALUES ($1,$2,$3,'role_change','user',$4,$5)""",
            user["org_id"], user["id"], user.get("email"), body.user_id,
            f'{{"granted_role": "{body.role_key}"}}',
        )
        return {"ok": True, "user_id": body.user_id, "role_key": body.role_key}

    @router.post("/revoke", status_code=status.HTTP_200_OK)
    async def revoke_role_route(
        body: RevokeRoleReq,
        user: Annotated[dict, Depends(require_permission("team.manage"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        if body.user_id == user["id"] and body.role_key == "owner":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tidak bisa mencabut role Owner dari diri sendiri")
        ok = await revoke_role(pool, user_id=body.user_id, org_id=user["org_id"], role_key=body.role_key)
        if not ok:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Penugasan role tidak ditemukan")
        await pool.execute(
            """INSERT INTO audit_logs (org_id, actor_user_id, actor_email, action, resource_type, resource_id, metadata)
               VALUES ($1,$2,$3,'role_change','user',$4,$5)""",
            user["org_id"], user["id"], user.get("email"), body.user_id,
            f'{{"revoked_role": "{body.role_key}"}}',
        )
        return {"ok": True, "user_id": body.user_id, "role_key": body.role_key}

    return router
