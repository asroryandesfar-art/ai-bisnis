"""Authentication routes (register / login / logout), extracted from main.py.

Security-critical, so handler bodies are copied verbatim and guarded by the
characterization tests in test_auth_endpoints.py. Dependencies are injected
(factory-DI convention). The two platform hooks that main sets lazily at
startup (audit-log and session-revoke) are injected as getters so the router
reads their current value at request time — preserving main's late-binding
behavior exactly.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, status


def build_auth_router(
    *,
    get_pool: Callable[..., Awaitable],
    get_current_user: Callable[..., Awaitable[dict]],
    ensure_schema: Callable[..., Awaitable[bool]],
    hash_password: Callable[[str], str],
    verify_password: Callable[[str, str], bool],
    is_supported_password_hash: Callable[[str], bool],
    dummy_pwd_hash: str,
    start_session: Callable[..., Awaitable],
    create_token: Callable[..., str],
    logger,
    get_write_audit: Callable[[], object],
    get_revoke_session: Callable[[], object],
    RegisterReq,
    LoginReq,
) -> APIRouter:
    router = APIRouter()

    @router.post("/auth/register", status_code=201)
    async def register(body: RegisterReq, request: Request, pool=Depends(get_pool)):
        """Daftar organisasi baru + user owner pertama."""
        try:
            if not await ensure_schema(pool):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Database schema belum siap. Pastikan PostgreSQL aktif dan schema.sql bisa dijalankan.",
                )
            email = body.email.strip().lower()
            async with pool.acquire() as conn:
                existing = await conn.fetchval(
                    "SELECT id FROM users WHERE lower(email)=$1", email
                )
                if existing:
                    raise HTTPException(400, "Email sudah terdaftar")

                # Buat slug dari nama org
                slug = body.org_name.lower().replace(" ", "-")[:40]
                slug_exists = await conn.fetchval(
                    "SELECT id FROM organizations WHERE slug=$1", slug
                )
                if slug_exists:
                    slug = f"{slug}-{str(uuid.uuid4())[:6]}"

                org_id  = str(uuid.uuid4())
                user_id = str(uuid.uuid4())
                trial_end = datetime.now(timezone.utc) + timedelta(days=14)

                await conn.execute(
                    """INSERT INTO organizations (id, name, slug, plan, billing_status, trial_ends_at)
                       VALUES ($1,$2,$3,'starter','trialing',$4)""",
                    org_id, body.org_name, slug, trial_end,
                )
                await conn.execute(
                    """INSERT INTO users (id, org_id, email, hashed_password, full_name, role)
                       VALUES ($1,$2,$3,$4,$5,'owner')""",
                    user_id, org_id, email,
                    hash_password(body.password), body.full_name,
                )
        except HTTPException:
            raise
        except Exception as e:
            # M-01: jangan bocorkan detail exception (skema/DB) ke klien. Log lengkap
            # di server, kirim pesan generik ke user.
            logger.exception("Register gagal (org=%s email=%s): %s", body.org_name, email, e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Registrasi gagal karena kesalahan server. Coba lagi nanti.",
            )

        session_id = await start_session(pool, user_id=user_id, org_id=org_id, email=email, request=request)
        token = create_token(user_id, org_id, session_id)
        return {"token": token, "org_id": org_id, "trial_ends": trial_end.isoformat()}

    @router.post("/auth/login")
    async def login(body: LoginReq, request: Request, pool=Depends(get_pool)):
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")

        async def _log_failed(org_id: str | None, user_id: str | None, email: str, reason: str) -> None:
            write_audit = get_write_audit()
            if not write_audit:
                return
            try:
                await write_audit(
                    pool, org_id=org_id, actor_user_id=user_id, actor_email=email,
                    action="login_failed", resource_type="user", resource_id=user_id,
                    ip_address=ip_address, user_agent=user_agent, metadata={"reason": reason},
                )
            except Exception:
                pass

        try:
            if not await ensure_schema(pool):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Database schema belum siap. Pastikan PostgreSQL aktif dan schema.sql bisa dijalankan.",
                )
            email = body.email.strip().lower()
            row = await pool.fetchrow(
                "SELECT id, org_id, hashed_password, is_active FROM users WHERE lower(email)=$1",
                email,
            )
            if not row:
                # L-01: samakan waktu respons dgn kasus email ada (verify dummy),
                # supaya durasi tidak membocorkan apakah email terdaftar.
                try:
                    verify_password(body.password, dummy_pwd_hash)
                except Exception:
                    pass
                await _log_failed(None, None, email, "not_found")
                raise HTTPException(401, "Email atau password salah")

            if not is_supported_password_hash(row["hashed_password"]):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Akun ini dibuat sebelum update sistem. Silakan reset password (pakai reset_password.cmd) lalu login lagi.",
                )

            if not verify_password(body.password, row["hashed_password"]):
                await _log_failed(str(row["org_id"]), str(row["id"]), email, "bad_password")
                raise HTTPException(401, "Email atau password salah")
            if not row["is_active"]:
                raise HTTPException(403, "Akun dinonaktifkan")

            await pool.execute(
                "UPDATE users SET last_login_at=NOW() WHERE id=$1", row["id"]
            )
            session_id = await start_session(
                pool, user_id=str(row["id"]), org_id=str(row["org_id"]), email=email, request=request,
            )
            return {"token": create_token(str(row["id"]), str(row["org_id"]), session_id)}
        except HTTPException:
            raise
        except Exception as e:
            # M-01: pesan generik ke klien, detail hanya di log server.
            logger.exception("Login gagal (email=%s): %s", email, e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Login gagal karena kesalahan server. Coba lagi nanti.",
            )

    @router.post("/auth/logout")
    async def logout(
        user: Annotated[dict, Depends(get_current_user)],
        pool=Depends(get_pool),
    ):
        session_id = user.get("session_id")
        revoke_session = get_revoke_session()
        if session_id and revoke_session:
            try:
                await revoke_session(pool, session_id=session_id, org_id=str(user["org_id"]), reason="logout")
            except Exception:
                pass
        write_audit = get_write_audit()
        if write_audit:
            try:
                await write_audit(
                    pool, org_id=str(user["org_id"]), actor_user_id=str(user["id"]), actor_email=user.get("email"),
                    action="logout", resource_type="user", resource_id=str(user["id"]), metadata={},
                )
            except Exception:
                pass
        return {"ok": True}

    return router
