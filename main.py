"""
BotNesia — API Layer
FastAPI + PostgreSQL (asyncpg) + AI Lokal (heuristik)

Struktur file:
  main.py         ← entry point (file ini)
  .env            ← konfigurasi (jangan di-commit ke git)

Jalankan:
  python run_server.py
  # (opsional) --reload untuk dev, kalau bermasalah di Windows jalankan tanpa --reload

Buka dashboard:
  lihat output run_server.py (port bisa 8000/8001/8002/8010)
"""

# ─── requirements.txt ────────────────────────────────────────
# fastapi>=0.111
# uvicorn[standard]
# asyncpg
# sqlalchemy[asyncio]
# python-jose[cryptography]  # JWT
# passlib[bcrypt]
# pinecone-client
# python-multipart           # file upload
# pydantic-settings
# httpx                      # webhook dispatch / HTTP client
# ─────────────────────────────────────────────────────────────

from __future__ import annotations

import hashlib
import hmac
import html
import json
import logging
import os
import re
import time
import uuid
import asyncio
import secrets
import sys
import urllib.parse
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Annotated

import vendor_bootstrap  # noqa: F401

import asyncpg
import httpx
import numpy as np
from fastapi import (
    Depends, FastAPI, File, HTTPException, Request,
    UploadFile, status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from passlib.exc import UnknownHashError
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

# Multi-agent AI pipeline (user-built)
from supervisor import SupervisorAgent
from rate_limiter import RateLimiter, LimitStatus
from integrations_store import (
    get_integrations,
    set_integration,
    merge_integration,
    clear_integration,
    db_get_integrations,
    db_get_integration,
    db_set_integration,
    db_clear_integration,
    db_set_oauth_state,
    db_pop_oauth_state,
    db_set_meta_phone_mapping,
    db_get_meta_phone_mapping,
    decrypt_dict,
)
from media_gen import (
    ReplicateRateLimitError,
    generate_image_replicate,
    generate_video_replicate,
)
from finance_fetcher import (
    build_crypto_market_context,
    build_stock_market_context,
    combine_market_answers,
    fetch_crypto_quotes,
    fetch_stock_quotes,
    format_crypto_market_answer,
    looks_like_market_price_query,
)
from news_fetcher import build_news_context


# ─── CONFIG ──────────────────────────────────────────────────

class Settings(BaseSettings):
    database_url:         str = "postgresql+asyncpg://user:pass@localhost/botnesia"
    db_connect_timeout_seconds: float = 2.5
    secret_key:           str = "change-me-in-production"
    replicate_api_token:  str = ""
    replicate_api_tokens: str = ""  # optional: comma-separated Replicate tokens
    replicate_image_version: str = ""  # Replicate model version id for image generation
    replicate_video_version: str = ""  # Replicate model version id for video generation
    replicate_image_model: str = ""  # Replicate model id (e.g. owner/name) for gated/hidden versions
    replicate_video_model: str = ""  # Replicate model id (e.g. owner/name) for gated/hidden versions
    replicate_image_input_json: str = ""  # optional JSON string
    replicate_video_input_json: str = ""  # optional JSON string
    replicate_image_queue_size: int = 8
    replicate_video_queue_size: int = 4
    replicate_image_workers: int = 1
    replicate_video_workers: int = 1
    replicate_min_request_gap_seconds: float = 1.5
    replicate_media_cooldown_seconds: int = 12
    # Groq
    groq_api_key:         str = ""
    groq_model:           str = "llama-3.3-70b-versatile"
    groq_base_url:        str = "https://api.groq.com/openai/v1"
    groq_whisper_model:   str = "whisper-large-v3-turbo"

    # Integrations (optional)
    gmail_client_id:      str = ""
    gmail_client_secret:  str = ""
    gmail_redirect_uri:   str = "http://127.0.0.1:8000/integrations/gmail/callback"
    gmail_poll_enabled:   bool = True
    gmail_poll_interval_seconds: int = 60
    gmail_poll_max_messages: int = 5
    gmail_poll_mark_read: bool = True
    meta_verify_token:    str = ""
    meta_app_secret:      str = ""  # opsional (untuk signature verify)
    meta_webhook_default_bot_id: str = ""  # optional fallback
    meta_api_version:     str = "v19.0"
    news_enabled:         bool = True
    news_max_items:       int = 6
    news_timeout_seconds: float = 8.0
    news_include_bodies:  bool = True
    news_max_body_chars:  int = 1400
    news_max_concurrency: int = 3
    news_rss_feeds:       str = ""  # comma-separated news source URLs: RSS/Atom/article links (optional)
    kb_embedding_dim:     int = 256
    pinecone_api_key:     str = ""
    pinecone_index:       str = "botnesia-chunks"
    jwt_algorithm:        str = "HS256"
    jwt_expire_hours:     int = 24 * 7
    storage_bucket:       str = "botnesia-docs"
    app_name:             str = "BotNesia"
    app_url:              str = "https://botnesia.id"

    class Config:
        env_file = ".env"
        extra = "ignore"

cfg = Settings()
_rate_limiter = RateLimiter()
logger = logging.getLogger("botnesia")

# ── Phase 2 platform callbacks (set by wiring block at bottom) ───────────────
# Pola ini menghindari circular import: Phase 2 modules tidak boleh import
# dari main.py, tapi main.py perlu panggil fungsi Phase 2 dari Phase 1 endpoints.
_platform_check_limit = None   # (pool, org_id, dimension) → (bool, dict)
_platform_enqueue_handoff = None  # (pool, org_id, conv_id, reason, priority) → dict|None
_platform_write_audit = None   # (pool, org_id, actor_user_id, actor_email, action, ...) → None

# Multi-agent supervisor singleton (cloud-only)
_supervisor_cloud: SupervisorAgent | None = None

# Background tasks
_gmail_poll_task: asyncio.Task | None = None
_gmail_poll_stop: asyncio.Event | None = None
_intelligence_learning_task: asyncio.Task | None = None
_intelligence_learning_stop: asyncio.Event | None = None


class QueueBusyError(RuntimeError):
    pass


class ReplicateJobQueue:
    def __init__(self, name: str, *, workers: int = 1, max_pending: int = 8, min_gap_s: float = 1.5):
        self.name = name
        self.workers = max(1, int(workers or 1))
        self.max_pending = max(1, int(max_pending or 1))
        self.min_gap_s = max(0.0, float(min_gap_s or 0.0))
        self._queue: asyncio.Queue[tuple[asyncio.Future, object]] = asyncio.Queue(maxsize=self.max_pending)
        self._tasks: list[asyncio.Task] = []
        self._last_started_at = 0.0
        self._start_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._tasks:
            return
        for idx in range(self.workers):
            self._tasks.append(asyncio.create_task(self._worker(idx + 1)))

    async def shutdown(self) -> None:
        tasks = list(self._tasks)
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except BaseException:
                pass

    async def submit(self, coro_factory):
        if self._queue.full():
            raise QueueBusyError(f"Queue {self.name} sedang penuh.")
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        await self._queue.put((fut, coro_factory))
        logger.debug("Queued Replicate %s job (pending=%s)", self.name, self._queue.qsize())
        return await fut

    async def _worker(self, worker_no: int) -> None:
        while True:
            fut, coro_factory = await self._queue.get()
            try:
                async with self._start_lock:
                    now = time.monotonic()
                    wait_s = max(0.0, self.min_gap_s - (now - self._last_started_at))
                    if wait_s > 0:
                        await asyncio.sleep(wait_s)
                    self._last_started_at = time.monotonic()
                logger.debug(
                    "Starting Replicate %s job on worker=%s (remaining=%s)",
                    self.name,
                    worker_no,
                    self._queue.qsize(),
                )
                result = await coro_factory()
                if not fut.done():
                    fut.set_result(result)
            except asyncio.CancelledError:
                if not fut.done():
                    fut.set_exception(RuntimeError(f"Queue {self.name} dihentikan."))
                raise
            except Exception as exc:
                logger.warning("Replicate %s job failed: %s", self.name, exc)
                if not fut.done():
                    fut.set_exception(exc)
            finally:
                self._queue.task_done()


_replicate_image_queue = ReplicateJobQueue(
    "image",
    workers=cfg.replicate_image_workers,
    max_pending=cfg.replicate_image_queue_size,
    min_gap_s=cfg.replicate_min_request_gap_seconds,
)
_replicate_video_queue = ReplicateJobQueue(
    "video",
    workers=cfg.replicate_video_workers,
    max_pending=cfg.replicate_video_queue_size,
    min_gap_s=max(cfg.replicate_min_request_gap_seconds, 2.0),
)
_media_user_cooldowns: dict[str, float] = {}


def should_use_cloud(plan: str, billing_status: str) -> bool:
    # Cloud-only: semua plan pakai Groq.
    return True


def get_supervisor(use_cloud: bool) -> SupervisorAgent:
    global _supervisor_cloud
    if not cfg.groq_api_key:
        raise RuntimeError("Cloud AI belum dikonfigurasi. Isi GROQ_API_KEY di .env lalu restart server.")

    if _supervisor_cloud is None:
        _supervisor_cloud = SupervisorAgent(
            api_key=cfg.groq_api_key,
            model=cfg.groq_model,
            base_url=(cfg.groq_base_url or "").strip() or None,
            app_url=cfg.app_url,
        )

    return _supervisor_cloud

# ─── APP ─────────────────────────────────────────────────────

app = FastAPI(
    title="BotNesia API",
    version="1.0.0",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Ganti dengan domain spesifik di production
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve dashboard static (biar FE dan BE satu origin, minim masalah CORS/mixed-content)
BASE_DIR = Path(__file__).resolve().parent
_FRONTEND_DIR = BASE_DIR / "frontend"
_DASHBOARD_PATH = _FRONTEND_DIR / "index.html"
_API_JS_PATH = BASE_DIR / "api.js"
_MULTIAGENT_INDEX_PATH = BASE_DIR / "MultiAgent_Index.html"
_MULTIAGENT_QUICK_PATH = BASE_DIR / "MultiAgent_Quick_Start.html"
_MULTIAGENT_FRAMEWORK_PATH = BASE_DIR / "MultiAgent_AI_Framework.html"
_MULTIAGENT_INTEGRATION_PATH = BASE_DIR / "MultiAgent_App_Integration.html"

@app.get("/", include_in_schema=False)
async def root():
    if _DASHBOARD_PATH.exists():
        return RedirectResponse(url="/dashboard")
    return {"status": "ok"}

@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    if not _DASHBOARD_PATH.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dashboard-connected.html tidak ditemukan")
    return FileResponse(
        _DASHBOARD_PATH,
        media_type="text/html",
        headers={"Cache-Control": "no-store"},
    )

@app.get("/ui/{asset_path:path}", include_in_schema=False)
async def frontend_asset(asset_path: str):
    requested = (_FRONTEND_DIR / asset_path).resolve()
    frontend_root = _FRONTEND_DIR.resolve()
    if frontend_root not in requested.parents or not requested.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset UI tidak ditemukan")
    media_types = {
        ".css": "text/css",
        ".js": "application/javascript",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    return FileResponse(
        requested,
        media_type=media_types.get(requested.suffix.lower(), "application/octet-stream"),
        headers={"Cache-Control": "no-cache"},
    )

@app.get("/api.js", include_in_schema=False)
async def api_client_js():
    if not _API_JS_PATH.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "api.js tidak ditemukan")
    return FileResponse(
        _API_JS_PATH,
        media_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )

@app.get("/multiagent", include_in_schema=False)
async def multiagent_index():
    if not _MULTIAGENT_INDEX_PATH.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "MultiAgent_Index.html tidak ditemukan")
    return FileResponse(
        _MULTIAGENT_INDEX_PATH,
        media_type="text/html",
        headers={"Cache-Control": "no-store"},
    )

@app.get("/multiagent/quick-start", include_in_schema=False)
async def multiagent_quick_start():
    if not _MULTIAGENT_QUICK_PATH.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "MultiAgent_Quick_Start.html tidak ditemukan")
    return FileResponse(
        _MULTIAGENT_QUICK_PATH,
        media_type="text/html",
        headers={"Cache-Control": "no-store"},
    )

@app.get("/multiagent/framework", include_in_schema=False)
async def multiagent_framework():
    if not _MULTIAGENT_FRAMEWORK_PATH.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "MultiAgent_AI_Framework.html tidak ditemukan")
    return FileResponse(
        _MULTIAGENT_FRAMEWORK_PATH,
        media_type="text/html",
        headers={"Cache-Control": "no-store"},
    )

@app.get("/multiagent/integration", include_in_schema=False)
async def multiagent_integration():
    if not _MULTIAGENT_INTEGRATION_PATH.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "MultiAgent_App_Integration.html tidak ditemukan")
    return FileResponse(
        _MULTIAGENT_INTEGRATION_PATH,
        media_type="text/html",
        headers={"Cache-Control": "no-store"},
    )

# ─── DB CONNECTION POOL ───────────────────────────────────────

_pool: asyncpg.Pool | None = None
_pool_loop: asyncio.AbstractEventLoop | None = None
_schema_ready: bool | None = None
_schema_lock = asyncio.Lock()

async def ensure_schema(pool: asyncpg.Pool) -> bool:
    """
    Pastikan tabel inti ada. Kalau belum, jalankan schema.sql sekali.
    Return True kalau schema siap, False kalau gagal.
    """
    global _schema_ready
    if _schema_ready is True:
        return True
    async with _schema_lock:
        if _schema_ready is True:
            return True
        try:
            async with pool.acquire() as conn:
                reg = await conn.fetchval("SELECT to_regclass('public.organizations')")
                if reg:
                    _schema_ready = True
                    return True

                schema_path = BASE_DIR / "schema.sql"
                if not schema_path.exists():
                    _schema_ready = False
                    return False

                sql = schema_path.read_text(encoding="utf-8")
                # asyncpg Connection.execute mendukung multiple statements
                await conn.execute(sql)
                _schema_ready = True
                print("[OK] Schema database diinisialisasi dari schema.sql")
                return True
        except Exception as e:
            _schema_ready = False
            print(f"[WARN] Gagal inisialisasi schema database: {e}")
            return False

async def get_pool() -> asyncpg.Pool:
    global _pool, _pool_loop
    loop = asyncio.get_running_loop()
    # Guard: pool tidak boleh dipakai lintas event loop (bisa kejadian saat reload/test)
    if _pool is not None:
        existing_loop = getattr(_pool, "_loop", _pool_loop)
        if existing_loop is not None and existing_loop is not loop:
            try:
                await _pool.close()
            except Exception:
                pass
            _pool = None
            _pool_loop = None

    if _pool is None:
        dsn = cfg.database_url.replace("+asyncpg", "")
        try:
            _pool = await asyncio.wait_for(
                asyncpg.create_pool(
                    dsn,
                    min_size=2,
                    max_size=20,
                ),
                timeout=cfg.db_connect_timeout_seconds,
            )
            _pool_loop = loop
        except Exception as e:
            # Untuk request handler: jangan 500 "misterius" kalau DB down
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Database belum terhubung: {e}",
            )
    return _pool

async def get_pool_safe(timeout: float | None = None) -> asyncpg.Pool | None:
    """Seperti get_pool tapi tidak raise — untuk health check/startup."""
    try:
        wait_timeout = timeout if timeout is not None else cfg.db_connect_timeout_seconds
        return await asyncio.wait_for(get_pool(), timeout=wait_timeout)
    except Exception:
        return None

@app.on_event("startup")
async def startup():
    global _gmail_poll_task, _gmail_poll_stop
    global _intelligence_learning_task, _intelligence_learning_stop
    try:
        await _replicate_image_queue.start()
        await _replicate_video_queue.start()
        logger.info(
            "Replicate queues aktif (image_workers=%s, video_workers=%s)",
            cfg.replicate_image_workers,
            cfg.replicate_video_workers,
        )
    except Exception as e:
        logger.warning("Gagal start Replicate queues: %s", e)
    try:
        # Jangan blok server start kalau DB belum siap
        startup_timeout = max(cfg.db_connect_timeout_seconds, 5.0)
        pool = await get_pool_safe(timeout=startup_timeout)
        if pool:
            await ensure_schema(pool)
            await ensure_optional_schema(pool)
            try:
                await _migrate_integrations_file_to_db(pool)
            except Exception:
                pass
            print("[OK] Database terhubung")
        else:
            print("[WARN] Database belum terhubung (timeout)")
            print("  App tetap berjalan - endpoint /health akan menunjukkan status DB")
    except Exception as e:
        print(f"[WARN] Database belum terhubung: {e}")
        print("  App tetap berjalan - endpoint /health akan menunjukkan status DB")

    # Gmail auto-poll scheduler (optional)
    try:
        if cfg.gmail_poll_enabled and _gmail_poll_task is None:
            _gmail_poll_stop = asyncio.Event()
            _gmail_poll_task = asyncio.create_task(_gmail_poll_loop())
            print(f"[OK] Gmail poller aktif (interval={cfg.gmail_poll_interval_seconds}s)")
    except Exception as e:
        print(f"[WARN] Gmail poller gagal start: {e}")

    try:
        from intelligence.pipeline import nightly_learning_loop

        if _intelligence_learning_task is None:
            _intelligence_learning_stop = asyncio.Event()
            _intelligence_learning_task = asyncio.create_task(
                nightly_learning_loop(_intelligence_learning_stop)
            )
            print("[OK] Intelligence nightly learning aktif")
    except Exception as e:
        print(f"[WARN] Intelligence nightly learning gagal start: {e}")

@app.on_event("shutdown")
async def shutdown():
    global _pool, _pool_loop, _gmail_poll_task, _gmail_poll_stop
    global _intelligence_learning_task, _intelligence_learning_stop
    try:
        if _gmail_poll_stop is not None:
            _gmail_poll_stop.set()
        if _gmail_poll_task is not None:
            try:
                await asyncio.wait_for(_gmail_poll_task, timeout=3.0)
            except BaseException:
                pass
    finally:
        _gmail_poll_task = None
        _gmail_poll_stop = None
    try:
        if _intelligence_learning_stop is not None:
            _intelligence_learning_stop.set()
        if _intelligence_learning_task is not None:
            try:
                await asyncio.wait_for(_intelligence_learning_task, timeout=3.0)
            except BaseException:
                _intelligence_learning_task.cancel()
    finally:
        _intelligence_learning_task = None
        _intelligence_learning_stop = None
    try:
        from intelligence.db import close_pool as close_intelligence_pool
        await close_intelligence_pool()
    except BaseException:
        pass
    try:
        await _replicate_image_queue.shutdown()
        await _replicate_video_queue.shutdown()
    except BaseException:
        pass
    if _pool:
        await _pool.close()
    _pool = None
    _pool_loop = None


async def _gmail_poll_loop() -> None:
    """
    Background loop: poll unread Gmail for each org that has gmail integration + bot_id.
    Tokens are stored encrypted in DB (org_integrations key='gmail').
    """
    while True:
        if _gmail_poll_stop is not None and _gmail_poll_stop.is_set():
            return
        pool = await get_pool_safe()
        if not pool:
            await asyncio.sleep(max(10, int(cfg.gmail_poll_interval_seconds or 60)))
            continue
        if not (cfg.gmail_client_id and cfg.gmail_client_secret):
            await asyncio.sleep(max(10, int(cfg.gmail_poll_interval_seconds or 60)))
            continue

        # Pull all Gmail integrations at once
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT org_id, data_enc FROM org_integrations WHERE key='gmail'"
                )
        except Exception:
            continue

        for r in rows:
            if _gmail_poll_stop is not None and _gmail_poll_stop.is_set():
                return
            org_id = str(r["org_id"])
            gmail = decrypt_dict(cfg.secret_key, r["data_enc"] or "")
            bot_id = (gmail.get("bot_id") or "").strip()
            if not bot_id:
                continue

            access_token = (gmail.get("access_token") or "").strip()
            refresh_token = (gmail.get("refresh_token") or "").strip()
            if not (access_token or refresh_token):
                continue

            try:
                # validate bot belongs to org
                ok = await pool.fetchval(
                    "SELECT 1 FROM bots WHERE id=$1 AND org_id=$2",
                    bot_id,
                    org_id,
                )
                if not ok:
                    continue
            except Exception:
                continue

            try:
                token = await _gmail_get_access_token(access_token, refresh_token)
                msgs = await _gmail_list_unread(token, max_results=max(1, min(20, int(cfg.gmail_poll_max_messages or 5))))
            except Exception:
                continue

            for mid in msgs:
                try:
                    m = await _gmail_get_message(token, mid)
                    snippet = (m.get("snippet") or "").strip()
                    headers = {h.get("name","").lower(): h.get("value","") for h in (m.get("payload", {}).get("headers") or [])}
                    subject = headers.get("subject","").strip()
                    from_h = headers.get("from","").strip()

                    text = "Email masuk:\n"
                    if subject:
                        text += f"Subjek: {subject}\n"
                    if from_h:
                        text += f"Dari: {from_h}\n"
                    if snippet:
                        text += f"Ringkas: {snippet}\n"

                    session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"gmail:{org_id}:{from_h}"))
                    req = ChatReq(
                        message=text.strip(),
                        session_id=session_id,
                        user_meta={"userId": f"gmail:{from_h}", "channel": "gmail", "gmail_message_id": mid},
                    )
                    await chat(bot_id=bot_id, body=req, pool=pool)

                    if bool(cfg.gmail_poll_mark_read):
                        try:
                            await _gmail_mark_read(token, mid)
                        except Exception:
                            pass
                except Exception:
                    continue

        await asyncio.sleep(max(10, int(cfg.gmail_poll_interval_seconds or 60)))


async def _migrate_integrations_file_to_db(pool: asyncpg.Pool) -> None:
    """
    One-time-ish migration helper:
    if data/integrations.json exists, upsert its content into org_integrations (encrypted).
    Safe to run multiple times.
    """
    p = Path("data/integrations.json")
    if not p.exists():
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8") or "{}")
    except Exception:
        return
    if not isinstance(data, dict) or not data:
        return

    for org_id, integ in data.items():
        if not isinstance(integ, dict):
            continue
        for k, v in integ.items():
            if not isinstance(k, str):
                continue
            if not isinstance(v, dict):
                continue
            try:
                await db_set_integration(pool, org_id=str(org_id), key=k, value=v, secret_key=cfg.secret_key)
            except Exception:
                pass
        # Also migrate meta_map into fast lookup table
        meta_map = integ.get("meta_map") if isinstance(integ, dict) else None
        if isinstance(meta_map, dict):
            for phone_id, bot_id in meta_map.items():
                if not phone_id or not bot_id:
                    continue
                try:
                    await db_set_meta_phone_mapping(
                        pool,
                        phone_number_id=str(phone_id).strip(),
                        org_id=str(org_id),
                        bot_id=str(bot_id),
                    )
                except Exception:
                    pass

    # housekeeping dedup table (keep last 7 days)
    try:
        await pool.execute("DELETE FROM meta_wa_message_dedup WHERE created_at < NOW() - INTERVAL '7 days'")
    except Exception:
        pass


async def ensure_optional_schema(pool: asyncpg.Pool) -> None:
    """
    Lightweight migrations untuk tabel tambahan yang tidak ada di schema awal.
    Aman dipanggil berulang (CREATE IF NOT EXISTS).
    """
    stmts = [
        """
        CREATE TABLE IF NOT EXISTS request_logs (
            id UUID PRIMARY KEY,
            org_id UUID,
            bot_id UUID,
            conversation_id UUID,
            route TEXT NOT NULL,
            model TEXT,
            latency_ms INT,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS doc_chunk_embeddings (
            chunk_id UUID PRIMARY KEY REFERENCES doc_chunks(id) ON DELETE CASCADE,
            org_id UUID NOT NULL,
            embedding JSONB NOT NULL,
            model TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_doc_chunk_embeddings_org ON doc_chunk_embeddings(org_id);",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'file';",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_url TEXT;",
        """
        CREATE TABLE IF NOT EXISTS org_integrations (
            org_id UUID NOT NULL,
            key TEXT NOT NULL,
            data_enc TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (org_id, key)
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_org_integrations_key ON org_integrations(key);",
        """
        CREATE TABLE IF NOT EXISTS oauth_states (
            provider TEXT NOT NULL,
            state TEXT NOT NULL,
            org_id UUID NOT NULL,
            redirect_uri TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (provider, state)
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_oauth_states_created ON oauth_states(created_at);",
        """
        CREATE TABLE IF NOT EXISTS meta_wa_phone_map (
            phone_number_id TEXT PRIMARY KEY,
            org_id UUID NOT NULL,
            bot_id UUID NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS meta_wa_message_dedup (
            message_id TEXT PRIMARY KEY,
            phone_number_id TEXT,
            from_number TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_meta_wa_message_dedup_created ON meta_wa_message_dedup(created_at);",
        "ALTER TABLE bots ADD COLUMN IF NOT EXISTS reasoning_mode TEXT NOT NULL DEFAULT 'standard';",
    ]
    async with pool.acquire() as conn:
        for sql in stmts:
            try:
                await conn.execute(sql)
            except Exception:
                # Jangan bikin server gagal start kalau optional schema gagal
                pass


# ─── AUTH ─────────────────────────────────────────────────────

# NOTE: gunakan skema yang tidak butuh backend native (lebih stabil di Windows)
# pbkdf2_sha256 tersedia di passlib tanpa dependency tambahan.
pwd_ctx = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
bearer  = HTTPBearer()


def hash_password(plain: str) -> str:
    return pwd_ctx.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)

def is_supported_password_hash(hashed: str) -> bool:
    try:
        pwd_ctx.identify(hashed)
        return True
    except UnknownHashError:
        return False

def create_token(user_id: str, org_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=cfg.jwt_expire_hours)
    return jwt.encode(
        {"sub": user_id, "org": org_id, "exp": expire},
        cfg.secret_key, algorithm=cfg.jwt_algorithm,
    )

async def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
    pool:  Annotated[asyncpg.Pool, Depends(get_pool)],
) -> dict:
    try:
        payload = jwt.decode(creds.credentials, cfg.secret_key,
                             algorithms=[cfg.jwt_algorithm])
        user_id: str = payload["sub"]
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token tidak valid")

    row = await pool.fetchrow(
        "SELECT id, org_id, email, role FROM users WHERE id=$1 AND is_active=TRUE",
        user_id,
    )
    if not row:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User tidak ditemukan")
    return dict(row)


# ─── PYDANTIC MODELS ──────────────────────────────────────────

class RegisterReq(BaseModel):
    org_name: str
    email:    str
    password: str = Field(min_length=8)
    full_name: str | None = None

class LoginReq(BaseModel):
    email:    str
    password: str

class BotCreateReq(BaseModel):
    name:          str
    primary_color: str = "#0066FF"
    greeting:      str = "Halo! Ada yang bisa saya bantu?"
    system_prompt: str | None = None
    language:      str = "id"
    status:        str = "active"

class BotUpdateReq(BaseModel):
    name:          str | None = None
    primary_color: str | None = None
    greeting:      str | None = None
    system_prompt: str | None = None
    language:      str | None = None
    status:        str | None = None
    reasoning_mode: str | None = None

class ChatReq(BaseModel):
    message:    str = Field(max_length=2000)
    session_id: str | None = None   # UUID conv yang sedang berjalan
    user_meta:  dict | None = None  # dari ChatbotWidget.identify()


# ─── ROUTE: AUTH ──────────────────────────────────────────────

@app.post("/auth/register", status_code=201)
async def register(body: RegisterReq, pool=Depends(get_pool)):
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
        # Biasanya: schema belum dibuat / permission CREATE EXTENSION / tabel belum ada
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Register gagal: {e}",
        )

    token = create_token(user_id, org_id)
    return {"token": token, "org_id": org_id, "trial_ends": trial_end.isoformat()}


@app.post("/auth/login")
async def login(body: LoginReq, pool=Depends(get_pool)):
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
            raise HTTPException(401, "Email atau password salah")

        if not is_supported_password_hash(row["hashed_password"]):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Akun ini dibuat sebelum update sistem. Silakan reset password (pakai reset_password.cmd) lalu login lagi.",
            )

        if not verify_password(body.password, row["hashed_password"]):
            raise HTTPException(401, "Email atau password salah")
        if not row["is_active"]:
            raise HTTPException(403, "Akun dinonaktifkan")

        await pool.execute(
            "UPDATE users SET last_login_at=NOW() WHERE id=$1", row["id"]
        )
        return {"token": create_token(str(row["id"]), str(row["org_id"]))}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login gagal: {e}",
        )


# ─── ROUTE: ORGANIZATION / SUBSCRIPTION ────────────────────────

_PLAN_LIMITS: dict[str, dict[str, int]] = {
    # Local AI (murah)
    "starter": {"bot_limit": 1, "conv_limit": 500, "doc_limit": 10},
    # Cloud AI (mahal)
    "growth": {"bot_limit": 3, "conv_limit": 2000, "doc_limit": 50},
    "scale": {"bot_limit": 10, "conv_limit": 10000, "doc_limit": 200},
}


@app.get("/org")
async def get_org(
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    org = await pool.fetchrow(
        """SELECT id, name, slug, plan, billing_status, trial_ends_at,
                  bot_limit, conv_limit, doc_limit
           FROM organizations WHERE id=$1""",
        user["org_id"],
    )
    if not org:
        raise HTTPException(404, "Organisasi tidak ditemukan")

    use_cloud = should_use_cloud(org["plan"], org["billing_status"])
    cloud_ready = bool(cfg.groq_api_key)
    provider = "groq" if cfg.groq_api_key else None
    cloud_model = cfg.groq_model if cfg.groq_api_key else None
    effective_mode = "cloud" if cloud_ready else "offline"

    return {
        "id": str(org["id"]),
        "name": org["name"],
        "slug": org["slug"],
        "plan": org["plan"],
        "billing_status": org["billing_status"],
        "trial_ends_at": org["trial_ends_at"].isoformat() if org["trial_ends_at"] else None,
        "limits": {
            "bot_limit": org["bot_limit"],
            "conv_limit": org["conv_limit"],
            "doc_limit": org["doc_limit"],
        },
        "ai": {
            "requested_mode": "cloud" if use_cloud else "local",
            "effective_mode": effective_mode,
            "cloud_ready": cloud_ready,
            "cloud_provider": provider,
            "cloud_model": cloud_model,
        },
    }


class OrgPlanUpdateReq(BaseModel):
    plan: str


@app.patch("/org/plan")
async def update_org_plan(
    body: OrgPlanUpdateReq,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    plan = (body.plan or "").strip().lower()
    if plan not in _PLAN_LIMITS:
        raise HTTPException(400, "Plan tidak valid (starter/growth/scale)")

    # Cegah downgrade kalau resource sekarang melebihi limit baru.
    active_bots = await pool.fetchval(
        "SELECT COUNT(*) FROM bots WHERE org_id=$1 AND status != 'inactive'",
        user["org_id"],
    )
    docs_count = await pool.fetchval(
        "SELECT COUNT(*) FROM documents WHERE org_id=$1",
        user["org_id"],
    )
    limits = _PLAN_LIMITS[plan]
    if active_bots > limits["bot_limit"]:
        raise HTTPException(
            409,
            f"Terlalu banyak bot aktif ({active_bots}). Hapus/nonaktifkan sampai ≤ {limits['bot_limit']} untuk downgrade.",
        )
    if docs_count > limits["doc_limit"]:
        raise HTTPException(
            409,
            f"Terlalu banyak dokumen ({docs_count}). Hapus sampai ≤ {limits['doc_limit']} untuk downgrade.",
        )

    await pool.execute(
        """UPDATE organizations
           SET plan=$2, bot_limit=$3, conv_limit=$4, doc_limit=$5, updated_at=NOW()
           WHERE id=$1""",
        user["org_id"],
        plan,
        limits["bot_limit"],
        limits["conv_limit"],
        limits["doc_limit"],
    )

    return {"message": "Plan diperbarui", "plan": plan, "limits": limits}


# ─── ROUTE: INTEGRATIONS (Gmail / Meta: WA, FB, IG) ────────────

def _mask_secret(s: str | None) -> str | None:
    if not s:
        return None
    if len(s) <= 8:
        return "*" * len(s)
    return s[:4] + ("*" * (len(s) - 8)) + s[-4:]


async def _get_integrations_auto(pool: asyncpg.Pool | None, org_id: str) -> dict:
    if pool:
        return await db_get_integrations(pool, org_id=org_id, secret_key=cfg.secret_key)
    return get_integrations(org_id)


async def _get_integration_auto(pool: asyncpg.Pool | None, org_id: str, key: str) -> dict:
    if pool:
        return await db_get_integration(pool, org_id=org_id, key=key, secret_key=cfg.secret_key)
    integ = get_integrations(org_id)
    return dict(integ.get(key) or {})


async def _set_integration_auto(pool: asyncpg.Pool | None, org_id: str, key: str, value: dict) -> None:
    if pool:
        await db_set_integration(pool, org_id=org_id, key=key, value=value, secret_key=cfg.secret_key)
    else:
        set_integration(org_id, key, value)


async def _clear_integration_auto(pool: asyncpg.Pool | None, org_id: str, key: str) -> None:
    if pool:
        await db_clear_integration(pool, org_id=org_id, key=key)
    else:
        clear_integration(org_id, key)


@app.get("/integrations")
async def integrations_status(
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    integ = await _get_integrations_auto(pool, str(user["org_id"]))
    gmail = integ.get("gmail") or {}
    meta = integ.get("meta") or {}
    return {
        "gmail": {
            "connected": bool(gmail.get("refresh_token") or gmail.get("access_token")),
            "email": gmail.get("email"),
            "bot_id": gmail.get("bot_id"),
        },
        "meta": {
            "connected": bool(meta.get("wa_token") or meta.get("page_token") or meta.get("ig_token")),
            "wa_phone_number_id": meta.get("wa_phone_number_id"),
        },
        "webhook": {
            "meta_url": "/webhooks/meta",
        },
    }


class MetaIntegrationReq(BaseModel):
    wa_token: str | None = None  # WhatsApp Cloud API token
    wa_phone_number_id: str | None = None
    page_token: str | None = None  # Facebook Page access token (optional)
    ig_token: str | None = None  # Instagram Graph token (optional)
    default_to_number: str | None = None  # nomor tujuan untuk test send (format internasional, contoh 62812...)
    wa_bot_id: str | None = None  # map phone_number_id -> bot_id (untuk inbound)


@app.post("/integrations/meta")
async def save_meta_integration(
    body: MetaIntegrationReq,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    # Simpan terenkripsi di DB (fallback: file JSON).
    meta = {
        "wa_token": body.wa_token or "",
        "wa_phone_number_id": body.wa_phone_number_id or "",
        "page_token": body.page_token or "",
        "ig_token": body.ig_token or "",
        "default_to_number": body.default_to_number or "",
        "wa_bot_id": body.wa_bot_id or "",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await _set_integration_auto(pool, str(user["org_id"]), "meta", meta)

    # Optional: kalau user sekalian isi wa_bot_id, simpan mapping untuk inbound routing.
    if meta["wa_phone_number_id"] and meta["wa_bot_id"]:
        try:
            await db_set_meta_phone_mapping(
                pool,
                phone_number_id=meta["wa_phone_number_id"].strip(),
                org_id=str(user["org_id"]),
                bot_id=meta["wa_bot_id"].strip(),
            )
        except Exception:
            pass
    return {
        "message": "Meta integration tersimpan",
        "meta": {
            "wa_phone_number_id": meta["wa_phone_number_id"] or None,
            "wa_token": _mask_secret(meta["wa_token"]),
            "page_token": _mask_secret(meta["page_token"]),
            "ig_token": _mask_secret(meta["ig_token"]),
            "default_to_number": meta["default_to_number"] or None,
            "wa_bot_id": meta["wa_bot_id"] or None,
        },
    }


class MetaMapBotReq(BaseModel):
    wa_phone_number_id: str
    bot_id: str


@app.post("/integrations/meta/map-bot")
async def meta_map_bot(
    body: MetaMapBotReq,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    # validate bot belongs to org
    bot = await pool.fetchrow(
        "SELECT id FROM bots WHERE id=$1 AND org_id=$2",
        body.bot_id, user["org_id"],
    )
    if not bot:
        raise HTTPException(404, "Bot tidak ditemukan untuk org ini")

    await db_set_meta_phone_mapping(
        pool,
        phone_number_id=body.wa_phone_number_id.strip(),
        org_id=str(user["org_id"]),
        bot_id=str(body.bot_id),
    )
    # keep a per-org map for UI/debug (encrypted)
    integ = await _get_integrations_auto(pool, str(user["org_id"]))
    meta_map = dict(integ.get("meta_map") or {})
    meta_map[body.wa_phone_number_id.strip()] = str(body.bot_id)
    await _set_integration_auto(pool, str(user["org_id"]), "meta_map", meta_map)
    return {"message": "Mapping tersimpan", "meta_map": meta_map}


class MetaSendTestReq(BaseModel):
    to_number: str
    text: str = "Halo! Ini test dari BotNesia."


@app.post("/integrations/meta/send-test")
async def meta_send_test(
    body: MetaSendTestReq,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    integ = await _get_integrations_auto(pool, str(user["org_id"]))
    meta = integ.get("meta") or {}
    token = (meta.get("wa_token") or "").strip()
    phone_id = (meta.get("wa_phone_number_id") or "").strip()
    if not token or not phone_id:
        raise HTTPException(400, "Meta WA token / phone number id belum diset")

    url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": body.to_number.strip(),
        "type": "text",
        "text": {"body": body.text},
    }
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code >= 400:
            raise HTTPException(400, f"Meta send gagal: {r.text[:300]}")
        return {"status": "ok", "response": r.json()}


class MetaSendTemplateReq(BaseModel):
    to_number: str
    template_name: str = "hello_world"
    language_code: str = "en_US"
    components: list[dict] | None = None  # optional advanced template params


@app.post("/integrations/meta/send-template")
async def meta_send_template(
    body: MetaSendTemplateReq,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    integ = await _get_integrations_auto(pool, str(user["org_id"]))
    meta = integ.get("meta") or {}
    token = (meta.get("wa_token") or "").strip()
    phone_id = (meta.get("wa_phone_number_id") or "").strip()
    if not token or not phone_id:
        raise HTTPException(400, "Meta WA token / phone number id belum diset")

    api_ver = (cfg.meta_api_version or "v19.0").strip() or "v19.0"
    url = f"https://graph.facebook.com/{api_ver}/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    tpl: dict = {
        "name": (body.template_name or "hello_world").strip(),
        "language": {"code": (body.language_code or "en_US").strip()},
    }
    if body.components:
        tpl["components"] = body.components

    payload = {
        "messaging_product": "whatsapp",
        "to": body.to_number.strip(),
        "type": "template",
        "template": tpl,
    }
    async with httpx.AsyncClient(timeout=25) as client:
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code >= 400:
            raise HTTPException(400, f"Meta template send gagal: {r.text[:800]}")
        return {"status": "ok", "response": r.json()}


# ─── ROUTE: MEDIA (Image / Video) ──────────────────────────────

_MEDIA_DIR = Path("data/media").resolve()
_MEDIA_DIR.mkdir(parents=True, exist_ok=True)


def _get_replicate_tokens() -> list[str]:
    toks: list[str] = []
    # Prefer multi-token env if provided
    raw = (cfg.replicate_api_tokens or "").strip()
    if raw:
        toks.extend([t.strip() for t in raw.split(",") if t.strip()])
    single = (cfg.replicate_api_token or "").strip()
    if single and single not in toks:
        toks.append(single)
    return toks


def _parse_json_dict(s: str) -> dict:
    try:
        obj = json.loads((s or "").strip() or "{}")
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _image_aspect_ratio_from_size(size: str) -> str:
    raw = (size or "1024x1024").lower().strip()
    mapping = {
        "1024x1024": "1:1",
        "1536x1024": "3:2",
        "1024x1536": "2:3",
    }
    return mapping.get(raw, "1:1")


def _replicate_image_overrides_for_model(
    model: str | None,
    size: str,
    quality: str,
    base_overrides: dict | None,
) -> dict:
    overrides = dict(base_overrides or {})
    model_name = (model or "").strip().lower()
    quality_name = (quality or "medium").strip().lower()

    if "black-forest-labs/flux-2-pro" in model_name:
        if "aspect_ratio" not in overrides:
            overrides["aspect_ratio"] = _image_aspect_ratio_from_size(size)
        if "resolution" not in overrides:
            overrides["resolution"] = "1 MP"
        if "output_format" not in overrides:
            overrides["output_format"] = "webp"
        if "output_quality" not in overrides:
            quality_map = {"low": 70, "medium": 80, "high": 90, "auto": 80}
            overrides["output_quality"] = quality_map.get(quality_name, 80)
        if "safety_tolerance" not in overrides:
            overrides["safety_tolerance"] = 2
        if "prompt_upsampling" not in overrides:
            overrides["prompt_upsampling"] = False
        overrides.pop("width", None)
        overrides.pop("height", None)
        return overrides

    if "width" not in overrides and "height" not in overrides:
        try:
            w_s, h_s = (size or "1024x1024").lower().split("x", 1)
            overrides["width"], overrides["height"] = int(w_s), int(h_s)
        except Exception:
            pass
    return overrides


def _replicate_video_overrides_for_model(
    model: str | None,
    seconds: int,
    fps: int,
    base_overrides: dict | None,
) -> dict:
    overrides = dict(base_overrides or {})
    model_name = (model or "").strip().lower()
    duration = max(5, min(int(seconds or 5), 10))

    if "bytedance/seedance-2.0" in model_name:
        if "duration" not in overrides:
            overrides["duration"] = duration
        if "resolution" not in overrides:
            overrides["resolution"] = "720p"
        if "aspect_ratio" not in overrides:
            overrides["aspect_ratio"] = "16:9"
        if "generate_audio" not in overrides:
            overrides["generate_audio"] = True
        return overrides

    if "alibaba/happyhorse-1.0" in model_name:
        if "duration" not in overrides:
            overrides["duration"] = duration
        if "resolution" not in overrides:
            overrides["resolution"] = "1080p"
        if "aspect_ratio" not in overrides:
            overrides["aspect_ratio"] = "16:9"
        return overrides

    if "duration" not in overrides:
        overrides["duration"] = duration
    if "fps" not in overrides and fps:
        overrides["fps"] = max(1, min(int(fps), 30))
    return overrides


def _check_media_cooldown(user_id: str, kind: str) -> int:
    cooldown_s = max(0, int(cfg.replicate_media_cooldown_seconds or 0))
    if cooldown_s <= 0:
        return 0
    now = time.monotonic()
    key = f"{kind}:{user_id}"
    until = _media_user_cooldowns.get(key, 0.0)
    if until > now:
        return int(until - now) + 1
    _media_user_cooldowns[key] = now + cooldown_s
    return 0


def _friendly_replicate_error(exc: Exception, kind: str) -> HTTPException:
    if isinstance(exc, QueueBusyError):
        retry_s = max(5, int(cfg.replicate_min_request_gap_seconds * 2))
        return HTTPException(
            429,
            f"Generate {kind} sedang ramai. Request kamu sudah terlalu banyak. Coba lagi {retry_s} detik lagi.",
            headers={"Retry-After": str(retry_s)},
        )
    if isinstance(exc, ReplicateRateLimitError):
        retry_s = max(3, int(exc.retry_after_s or cfg.replicate_min_request_gap_seconds or 3))
        return HTTPException(
            429,
            f"Layanan generate {kind} sedang kena batas request. Tenang, coba lagi {retry_s} detik lagi.",
            headers={"Retry-After": str(retry_s)},
        )
    return HTTPException(502, f"Replicate {kind} gagal: {exc}")


class MediaImageReq(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)
    size: str = "1024x1024"  # 1024x1024 | 1536x1024 | 1024x1536
    quality: str = "medium"  # low | medium | high | auto


class SpeakAudioReq(BaseModel):
    text: str = Field(..., min_length=1, max_length=1200)


@app.post("/audio/synthesize")
async def synthesize_audio(
    body: SpeakAudioReq,
    user=Depends(get_current_user),
):
    text = body.text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", ". ", text)
    text = re.sub(r"\n", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text).strip()
    if not text:
        raise HTTPException(400, "Teks suara kosong.")

    vendor_path = BASE_DIR / ".tts_vendor"
    if str(vendor_path) not in sys.path:
        sys.path.insert(0, str(vendor_path))
    try:
        import edge_tts

        audio = bytearray()
        communicator = edge_tts.Communicate(
            text,
            voice="id-ID-GadisNeural",
            rate="+4%",
            volume="+6%",
            pitch="-1Hz",
            boundary="SentenceBoundary",
        )
        async for chunk in communicator.stream():
            if chunk.get("type") == "audio":
                audio.extend(chunk.get("data") or b"")
        if not audio:
            raise RuntimeError("Provider tidak mengembalikan audio.")
        return Response(
            content=bytes(audio),
            media_type="audio/mpeg",
            headers={
                "Cache-Control": "no-store",
                "X-TTS-Voice": "id-ID-GadisNeural",
                "X-TTS-Rate": "+4%",
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Neural TTS failed user=%s: %s", user["id"], exc)
        raise HTTPException(502, "Suara neural sedang tidak tersedia.") from exc


@app.post("/audio/speak")
async def speak_audio(
    body: SpeakAudioReq,
    user=Depends(get_current_user),
):
    text = re.sub(r"\s+", " ", body.text).strip()
    if not text:
        raise HTTPException(400, "Teks suara kosong.")

    try:
        process = await asyncio.create_subprocess_exec(
            "spd-say",
            "--wait",
            "--output-module", "espeak-ng",
            "--language", "id",
            "--voice-type", "female1",
            "--rate", "-8",
            "--pitch", "2",
            "--volume", "35",
            "--punctuation-mode", "some",
            text,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        timeout = max(20.0, min(120.0, len(text) / 8.0))
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        if process.returncode != 0:
            detail = (stderr or b"").decode("utf-8", errors="ignore").strip()
            raise RuntimeError(detail or f"spd-say exit {process.returncode}")
        return {"status": "spoken", "characters": len(text)}
    except FileNotFoundError as exc:
        raise HTTPException(503, "Engine suara lokal tidak tersedia.") from exc
    except asyncio.TimeoutError as exc:
        try:
            process.kill()
        except Exception:
            pass
        raise HTTPException(504, "Pembacaan suara melewati batas waktu.") from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Local TTS failed user=%s: %s", user["id"], exc)
        raise HTTPException(502, "Engine suara lokal gagal membaca teks.") from exc


@app.post("/audio/stop")
async def stop_audio(user=Depends(get_current_user)):
    try:
        process = await asyncio.create_subprocess_exec(
            "spd-say", "--cancel",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(process.wait(), timeout=5)
    except Exception as exc:
        logger.debug("Stop local TTS failed user=%s: %s", user["id"], exc)
    return {"status": "stopped"}


@app.post("/audio/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    if not cfg.groq_api_key:
        raise HTTPException(503, "GROQ_API_KEY belum dikonfigurasi.")

    allowed_types = {
        "audio/webm", "audio/ogg", "audio/wav", "audio/x-wav",
        "audio/mpeg", "audio/mp4", "audio/x-m4a", "video/webm",
    }
    raw_content_type = (file.content_type or "").lower()
    content_type = raw_content_type.split(";", 1)[0].strip()
    if content_type and content_type not in allowed_types:
        raise HTTPException(415, f"Format audio tidak didukung: {content_type}")

    audio = await file.read(10 * 1024 * 1024 + 1)
    if not audio:
        raise HTTPException(400, "Rekaman audio kosong.")
    if len(audio) > 10 * 1024 * 1024:
        raise HTTPException(413, "Rekaman audio maksimal 10 MB.")

    filename = file.filename or "recording.webm"
    headers = {"Authorization": f"Bearer {cfg.groq_api_key}"}
    data = {
        "model": cfg.groq_whisper_model,
        "language": "id",
        "response_format": "json",
        "temperature": "0",
    }
    files = {"file": (filename, audio, content_type or "audio/webm")}
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                f"{cfg.groq_base_url.rstrip('/')}/audio/transcriptions",
                headers=headers,
                data=data,
                files=files,
            )
        if response.status_code == 401:
            raise HTTPException(503, "GROQ_API_KEY tidak valid.")
        if response.status_code == 429:
            raise HTTPException(429, "Layanan transkripsi sedang sibuk. Coba lagi sebentar.")
        response.raise_for_status()
        payload = response.json()
        text = str(payload.get("text") or "").strip()
        if not text:
            raise HTTPException(422, "Ucapan tidak terdeteksi. Coba bicara lebih jelas.")
        logger.info("Audio transcription success user=%s bytes=%s", user["id"], len(audio))
        return {"text": text, "model": cfg.groq_whisper_model}
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        logger.warning("Groq transcription rejected status=%s", exc.response.status_code)
        raise HTTPException(502, "Provider transkripsi menolak rekaman audio.") from exc
    except httpx.HTTPError as exc:
        logger.warning("Groq transcription connection failed: %s", exc)
        raise HTTPException(502, "Tidak dapat menghubungi layanan transkripsi.") from exc


@app.post("/media/image")
async def generate_image(
    body: MediaImageReq,
    user=Depends(get_current_user),
):
    retry_after = _check_media_cooldown(str(user["id"]), "image")
    if retry_after > 0:
        raise HTTPException(
            429,
            f"Tunggu {retry_after} detik sebelum generate gambar lagi.",
            headers={"Retry-After": str(retry_after)},
        )

    out_dir = _MEDIA_DIR / "generated"
    rep_toks = _get_replicate_tokens()
    rep_ver = (cfg.replicate_image_version or "").strip()
    rep_model = (cfg.replicate_image_model or "").strip()
    if not (rep_toks and (rep_ver or rep_model)):
        raise HTTPException(
            400,
            "Isi REPLICATE_API_TOKEN + (REPLICATE_IMAGE_VERSION atau REPLICATE_IMAGE_MODEL) untuk generate gambar.",
        )
    base_overrides = _parse_json_dict(cfg.replicate_image_input_json)
    models = [m.strip() for m in rep_model.split(",") if m.strip()] if rep_model else []

    async def _job():
        last_err: Exception | None = None
        path = None
        for tok_idx, tok in enumerate(rep_toks, start=1):
            for model_name in (models or [None]):
                try:
                    overrides = _replicate_image_overrides_for_model(
                        model_name,
                        body.size,
                        body.quality,
                        base_overrides,
                    )
                    if "num_outputs" not in overrides:
                        overrides["num_outputs"] = 1
                    logger.info(
                        "Replicate image request start user=%s token=%s model=%s",
                        user["id"],
                        tok_idx,
                        model_name or rep_ver or "version",
                    )
                    path = await generate_image_replicate(
                        tok,
                        version=(rep_ver or None),
                        model=model_name,
                        prompt=body.prompt,
                        out_dir=out_dir,
                        input_overrides=overrides,
                        timeout_s=140.0,
                    )
                    logger.info("Replicate image request success user=%s", user["id"])
                    return path
                except Exception as exc:
                    last_err = exc
                    logger.warning(
                        "Replicate image request failed user=%s token=%s model=%s error=%s",
                        user["id"],
                        tok_idx,
                        model_name or rep_ver or "version",
                        exc,
                    )
                    continue
        if last_err is not None:
            raise last_err
        raise RuntimeError("Replicate image gagal tanpa detail.")

    try:
        path = await _replicate_image_queue.submit(_job)
    except Exception as exc:
        raise _friendly_replicate_error(exc, "gambar")

    rel = path.relative_to(_MEDIA_DIR).as_posix()
    return {"type": "image", "url": f"/media/{rel}"}


class MediaVideoReq(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)
    seconds: int = 4
    fps: int = 4


@app.post("/media/video")
async def generate_video(
    body: MediaVideoReq,
    user=Depends(get_current_user),
):
    retry_after = _check_media_cooldown(str(user["id"]), "video")
    if retry_after > 0:
        raise HTTPException(
            429,
            f"Tunggu {retry_after} detik sebelum generate video lagi.",
            headers={"Retry-After": str(retry_after)},
        )

    rep_toks = _get_replicate_tokens()
    rep_ver = (cfg.replicate_video_version or "").strip()
    rep_model = (cfg.replicate_video_model or "").strip()
    if not (rep_toks and (rep_ver or rep_model)):
        raise HTTPException(
            400,
            "Isi REPLICATE_API_TOKEN + (REPLICATE_VIDEO_VERSION atau REPLICATE_VIDEO_MODEL) untuk generate video.",
        )

    models = [m.strip() for m in rep_model.split(",") if m.strip()] if rep_model else []
    base_overrides = _parse_json_dict(cfg.replicate_video_input_json)

    async def _job():
        last_err: Exception | None = None
        vid_path = None
        for tok_idx, tok in enumerate(rep_toks, start=1):
            for m in (models or [None]):
                try:
                    logger.info(
                        "Replicate video request start user=%s token=%s model=%s",
                        user["id"],
                        tok_idx,
                        m or rep_ver or "version",
                    )
                    vid_path = await generate_video_replicate(
                        tok,
                        version=(rep_ver or None),
                        model=m,
                        prompt=body.prompt,
                        out_dir=_MEDIA_DIR / "generated",
                        input_overrides=_replicate_video_overrides_for_model(
                            m,
                            body.seconds,
                            body.fps,
                            base_overrides,
                        ),
                        timeout_s=300.0,
                    )
                    logger.info("Replicate video request success user=%s", user["id"])
                    return vid_path
                except Exception as exc:
                    last_err = exc
                    logger.warning(
                        "Replicate video request failed user=%s token=%s model=%s error=%s",
                        user["id"],
                        tok_idx,
                        m or rep_ver or "version",
                        exc,
                    )
                    continue
        if last_err is not None:
            raise last_err
        raise RuntimeError("Replicate video gagal tanpa detail.")

    try:
        vid_path = await _replicate_video_queue.submit(_job)
    except Exception as exc:
        raise _friendly_replicate_error(exc, "video")

    rel = vid_path.relative_to(_MEDIA_DIR).as_posix()
    return {"type": "video", "url": f"/media/{rel}", "provider": "replicate"}


@app.get("/media/{path:path}", include_in_schema=False)
async def serve_media(path: str):
    p = (_MEDIA_DIR / path).resolve()
    if not str(p).startswith(str(_MEDIA_DIR)) or not p.exists() or not p.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(p)


@app.delete("/integrations/{key}")
async def delete_integration(
    key: str,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    if key not in {"gmail", "meta"}:
        raise HTTPException(400, "Integration key tidak valid")
    await _clear_integration_auto(pool, str(user["org_id"]), key)
    return {"message": "Integration dihapus", "key": key}


@app.post("/integrations/gmail/start")
async def gmail_start_oauth(
    request: Request,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    if not cfg.gmail_client_id or not cfg.gmail_client_secret:
        raise HTTPException(400, "GMAIL_CLIENT_ID/SECRET belum diisi di .env")

    state = secrets.token_urlsafe(24)

    # Redirect URI harus match persis dengan yang didaftarkan di Google Cloud OAuth Client.
    base = str(request.base_url).rstrip("/")
    dynamic_redirect_uri = base + "/integrations/gmail/callback"

    configured = (cfg.gmail_redirect_uri or "").strip()
    # Kalau redirect_uri di .env berbeda host/port dari origin yang dipakai user,
    # lebih aman pakai dynamic URI agar tidak mismatch (user cukup whitelist URI ini di Google Console).
    redirect_uri = configured if (configured and configured == dynamic_redirect_uri) else dynamic_redirect_uri

    # Simpan state di DB (tidak terenkripsi) supaya callback bisa cari org_id tanpa scan file.
    try:
        await db_set_oauth_state(
            pool,
            provider="gmail",
            state=state,
            org_id=str(user["org_id"]),
            redirect_uri=redirect_uri,
        )
    except Exception:
        # fallback lama: file store
        set_integration(
            str(user["org_id"]),
            "gmail_oauth",
            {
                "state": state,
                "redirect_uri": redirect_uri,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    params = {
        "client_id": cfg.gmail_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        # NOTE: gmail.modify memungkinkan membaca + mark-as-read. Untuk auto-reply perlu gmail.send (tidak diaktifkan default).
        "scope": "https://www.googleapis.com/auth/gmail.modify https://www.googleapis.com/auth/userinfo.email openid",
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return {
        "auth_url": url,
        "redirect_uri": redirect_uri,
        "note": "Pastikan redirect_uri ini di-whitelist persis di Google Cloud Console (OAuth Client)",
    }


@app.get("/integrations/gmail/callback", include_in_schema=False)
async def gmail_oauth_callback(
    code: str | None = None,
    state: str | None = None,
):
    if not code or not state:
        raise HTTPException(400, "Missing code/state")

    pool = await get_pool_safe()
    org_id: str | None = None
    redirect_uri: str | None = None

    # Prefer DB state store
    if pool:
        try:
            org_id, redirect_uri = await db_pop_oauth_state(pool, provider="gmail", state=state)
        except Exception:
            org_id, redirect_uri = None, None

    # Fallback lama: scan file integrations.json
    if not org_id:
        store_path = Path("data/integrations.json")
        data = {}
        try:
            if store_path.exists():
                data = json.loads(store_path.read_text(encoding="utf-8") or "{}")
        except Exception:
            data = {}
        for k, v in (data or {}).items():
            oauth = v.get("gmail_oauth") or {}
            if oauth.get("state") == state:
                org_id = k
                redirect_uri = oauth.get("redirect_uri")
                break

    if not org_id:
        raise HTTPException(400, "State tidak valid/expired")
    if not redirect_uri:
        redirect_uri = cfg.gmail_redirect_uri

    async with httpx.AsyncClient(timeout=15) as client:
        token_res = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": cfg.gmail_client_id,
                "client_secret": cfg.gmail_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_res.status_code >= 400:
            raise HTTPException(400, f"Gmail token exchange gagal: {token_res.text[:200]}")
        tok = token_res.json()

    gmail = {
        "access_token": tok.get("access_token", ""),
        "refresh_token": tok.get("refresh_token", ""),
        "expires_in": tok.get("expires_in"),
        "token_type": tok.get("token_type"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Try fetch connected email (optional, best-effort)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            u = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {gmail['access_token']}"},
            )
            if u.status_code < 400:
                gmail["email"] = (u.json() or {}).get("email")
    except Exception:
        pass
    # Store Gmail tokens encrypted in DB (fallback: file store)
    await _set_integration_auto(pool, org_id, "gmail", gmail)
    try:
        await _clear_integration_auto(pool, org_id, "gmail_oauth")
    except Exception:
        pass

    # Redirect balik ke dashboard settings
    return RedirectResponse(url="/dashboard#settings")


class GmailMapBotReq(BaseModel):
    bot_id: str


@app.post("/integrations/gmail/map-bot")
async def gmail_map_bot(
    body: GmailMapBotReq,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    bot = await pool.fetchrow(
        "SELECT id FROM bots WHERE id=$1 AND org_id=$2",
        body.bot_id, user["org_id"],
    )
    if not bot:
        raise HTTPException(404, "Bot tidak ditemukan untuk org ini")

    integ = await _get_integrations_auto(pool, str(user["org_id"]))
    gmail = dict(integ.get("gmail") or {})
    if not (gmail.get("refresh_token") or gmail.get("access_token")):
        raise HTTPException(400, "Gmail belum connected")

    gmail["bot_id"] = str(body.bot_id)
    gmail["updated_at"] = datetime.now(timezone.utc).isoformat()
    await _set_integration_auto(pool, str(user["org_id"]), "gmail", gmail)
    return {"message": "Mapping Gmail -> bot tersimpan", "bot_id": gmail["bot_id"]}


class GmailPollReq(BaseModel):
    max_messages: int = 5
    mark_read: bool = True


@app.post("/integrations/gmail/poll")
async def gmail_poll(
    body: GmailPollReq,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    integ = await _get_integrations_auto(pool, str(user["org_id"]))
    gmail = dict(integ.get("gmail") or {})
    bot_id = (gmail.get("bot_id") or "").strip()
    if not bot_id:
        raise HTTPException(400, "Gmail belum di-map ke bot. Set dulu via /integrations/gmail/map-bot.")

    # validate bot belongs to org
    bot = await pool.fetchrow("SELECT id FROM bots WHERE id=$1 AND org_id=$2", bot_id, user["org_id"])
    if not bot:
        raise HTTPException(404, "Bot mapping tidak valid")

    access_token = (gmail.get("access_token") or "").strip()
    refresh_token = (gmail.get("refresh_token") or "").strip()
    if not (access_token or refresh_token):
        raise HTTPException(400, "Gmail token tidak ada. Connect ulang Gmail.")

    token = await _gmail_get_access_token(access_token, refresh_token)
    msgs = await _gmail_list_unread(token, max_results=max(1, min(20, body.max_messages)))

    processed = 0
    for mid in msgs:
        m = await _gmail_get_message(token, mid)
        snippet = (m.get("snippet") or "").strip()
        headers = {h.get("name","").lower(): h.get("value","") for h in (m.get("payload", {}).get("headers") or [])}
        subject = headers.get("subject","").strip()
        from_h = headers.get("from","").strip()

        text = "Email masuk:\n"
        if subject:
            text += f"Subjek: {subject}\n"
        if from_h:
            text += f"Dari: {from_h}\n"
        if snippet:
            text += f"Ringkas: {snippet}\n"

        session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"gmail:{user['org_id']}:{from_h}"))
        req = ChatReq(
            message=text.strip(),
            session_id=session_id,
            user_meta={"userId": f"gmail:{from_h}", "channel": "gmail", "gmail_message_id": mid},
        )
        await chat(bot_id=bot_id, body=req, pool=pool)
        processed += 1

        if body.mark_read:
            try:
                await _gmail_mark_read(token, mid)
            except Exception:
                pass

    return {"processed": processed, "unread": len(msgs)}


@app.get("/integrations/gmail/poller")
async def gmail_poller_status(user=Depends(get_current_user)):
    return {
        "enabled": bool(cfg.gmail_poll_enabled),
        "interval_seconds": int(cfg.gmail_poll_interval_seconds or 60),
        "max_messages": int(cfg.gmail_poll_max_messages or 5),
        "mark_read": bool(cfg.gmail_poll_mark_read),
        "running": bool(_gmail_poll_task is not None and not _gmail_poll_task.done()),
    }


@app.post("/integrations/gmail/poller/run-once")
async def gmail_poller_run_once(
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    """
    Trigger sekali untuk org ini (mirip poll, tapi pakai config server).
    """
    integ = await _get_integrations_auto(pool, str(user["org_id"]))
    gmail = dict(integ.get("gmail") or {})
    bot_id = (gmail.get("bot_id") or "").strip()
    if not bot_id:
        raise HTTPException(400, "Gmail belum di-map ke bot.")

    access_token = (gmail.get("access_token") or "").strip()
    refresh_token = (gmail.get("refresh_token") or "").strip()
    if not (access_token or refresh_token):
        raise HTTPException(400, "Gmail token tidak ada. Connect ulang Gmail.")

    token = await _gmail_get_access_token(access_token, refresh_token)
    msgs = await _gmail_list_unread(token, max_results=max(1, min(20, int(cfg.gmail_poll_max_messages or 5))))

    processed = 0
    for mid in msgs:
        m = await _gmail_get_message(token, mid)
        snippet = (m.get("snippet") or "").strip()
        headers = {h.get("name","").lower(): h.get("value","") for h in (m.get("payload", {}).get("headers") or [])}
        subject = headers.get("subject","").strip()
        from_h = headers.get("from","").strip()

        text = "Email masuk:\n"
        if subject:
            text += f"Subjek: {subject}\n"
        if from_h:
            text += f"Dari: {from_h}\n"
        if snippet:
            text += f"Ringkas: {snippet}\n"

        session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"gmail:{user['org_id']}:{from_h}"))
        req = ChatReq(
            message=text.strip(),
            session_id=session_id,
            user_meta={"userId": f"gmail:{from_h}", "channel": "gmail", "gmail_message_id": mid},
        )
        await chat(bot_id=bot_id, body=req, pool=pool)
        processed += 1
        if bool(cfg.gmail_poll_mark_read):
            try:
                await _gmail_mark_read(token, mid)
            except Exception:
                pass

    return {"processed": processed, "unread": len(msgs)}


async def _gmail_get_access_token(access_token: str, refresh_token: str) -> str:
    # If access token exists, use it (best-effort). If refresh token exists, refresh each poll for stability.
    if refresh_token:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": cfg.gmail_client_id,
                    "client_secret": cfg.gmail_client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
            return (r.json() or {}).get("access_token") or access_token
    return access_token


async def _gmail_list_unread(token: str, max_results: int = 5) -> list[str]:
    url = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
    params = {"q": "is:unread", "maxResults": max_results}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        data = r.json() or {}
    return [m.get("id") for m in (data.get("messages") or []) if m.get("id")]


async def _gmail_get_message(token: str, message_id: str) -> dict:
    url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}"
    params = {"format": "metadata"}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        return r.json() or {}


async def _gmail_mark_read(token: str, message_id: str) -> None:
    url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/modify"
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={"removeLabelIds": ["UNREAD"]},
        )
        r.raise_for_status()


@app.get("/webhooks/meta", include_in_schema=False)
async def meta_webhook_verify(request: Request):
    # Meta verification: hub.mode, hub.verify_token, hub.challenge
    qp = request.query_params
    mode = qp.get("hub.mode")
    token = qp.get("hub.verify_token")
    challenge = qp.get("hub.challenge")
    if mode == "subscribe" and token and token == cfg.meta_verify_token:
        return int(challenge) if challenge is not None else 0
    raise HTTPException(403, "Verification failed")


@app.post("/webhooks/meta", include_in_schema=False)
async def meta_webhook_receive(request: Request):
    body_bytes = await request.body()
    try:
        payload = json.loads(body_bytes.decode("utf-8") or "{}")
    except Exception:
        payload = {}

    # Optional security: verify X-Hub-Signature-256 (HMAC-SHA256) if META_APP_SECRET is set.
    if (cfg.meta_app_secret or "").strip():
        sig = (request.headers.get("X-Hub-Signature-256") or "").strip()
        expected = "sha256=" + hmac.new(
            cfg.meta_app_secret.encode("utf-8"),
            body_bytes,
            hashlib.sha256,
        ).hexdigest()
        if not (sig and hmac.compare_digest(sig, expected)):
            raise HTTPException(403, "Invalid signature")
    # Best-effort log payload.
    try:
        p = Path("data/meta_webhooks.log")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text((p.read_text(encoding="utf-8") if p.exists() else "") + json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception:
        pass

    # Auto-reply WhatsApp inbound (basic):
    # - detect message text
    # - map phone_number_id -> bot_id
    # - call /chat pipeline and send response via WhatsApp Cloud API
    try:
        await _handle_meta_whatsapp_inbound(payload)
    except Exception:
        # jangan bikin webhook gagal
        pass

    return {"status": "ok"}


async def _handle_meta_whatsapp_inbound(payload: dict) -> None:
    # WhatsApp Cloud payload shape: entry[].changes[].value.messages[]
    entries = payload.get("entry") or []
    if not isinstance(entries, list) or not entries:
        return

    pool = await get_pool_safe()
    if not pool:
        return

    for entry in entries:
        changes = (entry or {}).get("changes") or []
        for ch in changes:
            val = (ch or {}).get("value") or {}
            messages = val.get("messages") or []
            metadata = val.get("metadata") or {}
            phone_number_id = (metadata.get("phone_number_id") or "").strip()
            if not phone_number_id or not isinstance(messages, list):
                continue

            # Only handle text messages for now.
            for m in messages:
                if (m or {}).get("type") != "text":
                    continue
                message_id = (m.get("id") or "").strip()
                text = ((m.get("text") or {}).get("body") or "").strip()
                from_number = (m.get("from") or "").strip()
                if not text or not from_number:
                    continue
                if message_id:
                    # Dedup: Meta bisa retry webhook; jangan balas 2x.
                    try:
                        inserted = await pool.fetchval(
                            """
                            INSERT INTO meta_wa_message_dedup(message_id, phone_number_id, from_number)
                            VALUES($1,$2,$3)
                            ON CONFLICT (message_id) DO NOTHING
                            RETURNING message_id
                            """,
                            message_id,
                            phone_number_id,
                            from_number,
                        )
                        if inserted is None:
                            continue
                    except Exception:
                        pass

                # Find org+bot mapping.
                await _meta_route_and_reply_whatsapp(
                    pool=pool,
                    phone_number_id=phone_number_id,
                    from_number=from_number,
                    text=text,
                )


async def _meta_route_and_reply_whatsapp(
    pool: asyncpg.Pool,
    phone_number_id: str,
    from_number: str,
    text: str,
) -> None:
    org_id, bot_id = await db_get_meta_phone_mapping(pool, phone_number_id=phone_number_id)
    wa_token = ""

    # Fallback lama: scan file (untuk migrasi)
    if not (org_id and bot_id):
        store_path = Path("data/integrations.json")
        try:
            data = json.loads(store_path.read_text(encoding="utf-8") or "{}") if store_path.exists() else {}
        except Exception:
            data = {}
        for oid, cfgx in (data or {}).items():
            meta_map = (cfgx.get("meta_map") or {})
            candidate_bot = meta_map.get(phone_number_id) or (cfgx.get("meta") or {}).get("wa_bot_id")
            if candidate_bot:
                org_id = oid
                bot_id = candidate_bot
                wa_token = (cfgx.get("meta") or {}).get("wa_token") or ""
                break

    # Fallback: env default bot id (single-tenant).
    if not bot_id and cfg.meta_webhook_default_bot_id:
        bot_id = cfg.meta_webhook_default_bot_id
        # try find org_id of that bot
        org_id = await pool.fetchval("SELECT org_id FROM bots WHERE id=$1", bot_id)
        if org_id:
            try:
                integ = await _get_integrations_auto(pool, str(org_id))
                wa_token = ((integ.get("meta") or {}).get("wa_token") or "").strip()
            except Exception:
                wa_token = ""

    if bot_id and org_id and not wa_token:
        try:
            integ = await _get_integrations_auto(pool, str(org_id))
            wa_token = ((integ.get("meta") or {}).get("wa_token") or "").strip()
        except Exception:
            wa_token = ""

    if not bot_id or not org_id or not wa_token:
        return

    # Use internal chat pipeline directly: create a pseudo request.
    # Build minimal conversation: session_id is derived from wa number.
    session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"wa:{phone_number_id}:{from_number}"))
    req = ChatReq(message=text, session_id=session_id, user_meta={"userId": f"wa:{from_number}", "channel": "whatsapp", "wa_from": from_number})
    resp = await chat(bot_id=bot_id, body=req, pool=pool)  # reuse handler
    answer = (resp.get("answer") if isinstance(resp, dict) else None) or ""
    answer = answer.strip()
    if not answer:
        return

    # Send reply via WhatsApp Cloud API
    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {wa_token}", "Content-Type": "application/json"}
    out = {
        "messaging_product": "whatsapp",
        "to": from_number,
        "type": "text",
        "text": {"body": answer[:3500]},
    }
    async with httpx.AsyncClient(timeout=20) as client:
        await client.post(url, headers=headers, json=out)


# ─── ROUTE: BOTS ──────────────────────────────────────────────

@app.get("/bots")
async def list_bots(
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    rows = await pool.fetch(
        """SELECT id, name, status, primary_color, greeting, language,
                  system_prompt, temperature, reasoning_mode, total_convs, total_msgs, created_at
           FROM bots WHERE org_id=$1 ORDER BY created_at DESC""",
        user["org_id"],
    )
    return [dict(r) for r in rows]


@app.post("/bots", status_code=201)
async def create_bot(
    body: BotCreateReq,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    # Cek limit plan (Phase 2: gunakan check_limit dari subscriptions/plans)
    if _platform_check_limit:
        ok, detail = await _platform_check_limit(pool, user["org_id"], "agents")
        if not ok:
            raise HTTPException(
                402,
                f"Limit jumlah AI agent paket '{detail['plan']}' tercapai "
                f"({detail['used']}/{detail['limit']}). Upgrade di /api/billing/checkout.",
            )
    else:
        # Fallback ke logika lama (jika Phase 2 belum dimuat)
        count = await pool.fetchval(
            "SELECT COUNT(*) FROM bots WHERE org_id=$1 AND status != 'inactive'", user["org_id"]
        )
        limit = await pool.fetchval(
            "SELECT bot_limit FROM organizations WHERE id=$1", user["org_id"]
        )
        if count >= limit:
            raise HTTPException(402, f"Paket kamu hanya boleh {limit} bot aktif. Upgrade untuk tambah lebih.")

    bot_id = str(uuid.uuid4())
    status_val = body.status if body.status in {"active", "training", "inactive"} else "active"
    await pool.execute(
        """INSERT INTO bots (id, org_id, name, status, primary_color, greeting, language, system_prompt)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
        bot_id, user["org_id"], body.name,
        status_val,
        body.primary_color, body.greeting,
        body.language, body.system_prompt,
    )
    # Audit log (Phase 2)
    if _platform_write_audit:
        try:
            await _platform_write_audit(
                pool, org_id=user["org_id"], actor_user_id=user["id"],
                actor_email=user.get("email"), action="create",
                resource_type="bot", resource_id=bot_id,
                metadata={"name": body.name, "status": status_val},
            )
        except Exception:
            pass
    return {"bot_id": bot_id, "status": status_val, "message": "Bot berhasil dibuat"}


@app.get("/bots/{bot_id}/config")
async def get_bot_config(bot_id: str, pool=Depends(get_pool)):
    """
    Public endpoint — dipanggil oleh widget.js dari browser klien.
    Tidak butuh auth, tapi hanya return config tampilan (bukan system prompt).
    """
    row = await pool.fetchrow(
        """SELECT id, name, primary_color, greeting, language, status
           FROM bots WHERE id=$1""",
        bot_id,
    )
    if not row or row["status"] == "inactive":
        raise HTTPException(404, "Bot tidak ditemukan atau tidak aktif")
    return dict(row)


@app.patch("/bots/{bot_id}")
async def update_bot(
    bot_id: str,
    body:   BotUpdateReq,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    row = await pool.fetchrow(
        "SELECT id FROM bots WHERE id=$1 AND org_id=$2", bot_id, user["org_id"]
    )
    if not row:
        raise HTTPException(404, "Bot tidak ditemukan")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if "status" in updates and updates["status"] not in {"active", "training", "inactive"}:
        raise HTTPException(400, "Status tidak valid")
    if "reasoning_mode" in updates and updates["reasoning_mode"] not in {"standard", "pro"}:
        raise HTTPException(400, "Reasoning mode tidak valid")
    if not updates:
        return {"message": "Tidak ada perubahan"}

    set_clause = ", ".join(f"{k}=${i+2}" for i, k in enumerate(updates))
    vals = list(updates.values())
    await pool.execute(
        f"UPDATE bots SET {set_clause}, updated_at=NOW() WHERE id=$1",
        bot_id, *vals,
    )
    return {"message": "Bot diperbarui"}


# ─── ROUTE: DOCUMENTS ─────────────────────────────────────────

@app.post("/bots/{bot_id}/documents", status_code=201)
async def upload_document(
    bot_id: str,
    file:   UploadFile = File(...),
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    """Upload dokumen untuk knowledge base bot."""
    # Validasi bot milik org
    bot = await pool.fetchrow(
        "SELECT id FROM bots WHERE id=$1 AND org_id=$2", bot_id, user["org_id"]
    )
    if not bot:
        raise HTTPException(404, "Bot tidak ditemukan")

    # Cek limit dokumen
    if _platform_check_limit:
        ok, detail = await _platform_check_limit(pool, user["org_id"], "knowledge")
        if not ok:
            raise HTTPException(
                402,
                f"Limit jumlah dokumen knowledge base paket '{detail['plan']}' tercapai "
                f"({detail['used']}/{detail['limit']}). Upgrade di /api/billing/checkout.",
            )
    else:
        doc_count = await pool.fetchval(
            "SELECT COUNT(*) FROM documents WHERE org_id=$1", user["org_id"]
        )
        doc_limit = await pool.fetchval(
            "SELECT doc_limit FROM organizations WHERE id=$1", user["org_id"]
        )
        if doc_count >= doc_limit:
            raise HTTPException(402, f"Batas dokumen ({doc_limit}) tercapai. Upgrade plan untuk upload lebih.")

    contents = await file.read()
    doc_id   = str(uuid.uuid4())

    # Simpan metadata ke DB
    await pool.execute(
        """INSERT INTO documents (id, org_id, bot_id, filename, file_size, mime_type, status, source_type, source_url)
           VALUES ($1,$2,$3,$4,$5,$6,'pending','file',NULL)""",
        doc_id, user["org_id"], bot_id,
        file.filename, len(contents), file.content_type,
    )

    # Di production: kirim ke queue (Celery/BullMQ) untuk proses async
    # Untuk sekarang: proses langsung (simplified)
    await _process_document_sync(pool, doc_id, contents=contents, mime=file.content_type or "", source_type="file")

    # Proses saat ini synchronous, jadi status sudah final (ready/failed)
    row = await pool.fetchrow("SELECT status, error_msg FROM documents WHERE id=$1", doc_id)
    return {"doc_id": doc_id, "status": row["status"], "error_msg": row["error_msg"]}


async def _process_document_sync(
    pool: asyncpg.Pool,
    doc_id: str,
    *,
    contents: bytes | None = None,
    mime: str = "",
    source_type: str = "file",
    source_url: str | None = None,
):
    """
    Simplified sync processing.
    Di production: jalankan di background worker (Celery + Redis).
    """
    try:
        text = ""
        source_type = (source_type or "file").lower().strip()
        mime_l = (mime or "").lower()

        if source_type == "url":
            text = await _fetch_website_text(source_url or "")
        else:
            raw = contents or b""
            if "pdf" in mime_l:
                try:
                    import io
                    from pypdf import PdfReader

                    reader = PdfReader(io.BytesIO(raw))
                    parts = []
                    for page in reader.pages:
                        parts.append(page.extract_text() or "")
                    text = "\n".join(parts)
                except Exception as e:
                    raise ValueError(f"Gagal ekstrak teks dari PDF: {e}")
            elif ("word" in mime_l) or ("docx" in mime_l):
                try:
                    import io
                    import zipfile
                    import xml.etree.ElementTree as ET

                    with zipfile.ZipFile(io.BytesIO(raw)) as z:
                        xml_bytes = z.read("word/document.xml")

                    root = ET.fromstring(xml_bytes)
                    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                    parts = []
                    for node in root.findall(".//w:t", ns):
                        if node.text:
                            parts.append(node.text)
                    text = "\n".join(parts)
                except Exception as e:
                    raise ValueError(f"Gagal ekstrak teks dari DOCX: {e}")
            else:
                text = raw.decode("utf-8", errors="ignore")

        if "\x00" in text:
            text = text.replace("\x00", "")
        text = "".join(ch for ch in text if (ch >= " " or ch in "\n\t"))
        text = text.strip()
        if not text:
            raise ValueError("Dokumen tidak menghasilkan teks yang bisa diproses.")

        chunks = _chunk_text(text, size=350)
        if not chunks:
            raise ValueError("Dokumen terlalu pendek untuk di-chunk.")

        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT org_id FROM documents WHERE id=$1", doc_id)
            org_id = str(row["org_id"])

            chunk_rows: list[tuple[str, str]] = []
            for i, chunk_text in enumerate(chunks):
                chunk_id = str(uuid.uuid4())
                await conn.execute(
                    """INSERT INTO doc_chunks (id, document_id, org_id, chunk_index, content, token_count)
                       VALUES ($1,$2,$3,$4,$5,$6)""",
                    chunk_id, doc_id, org_id, i, chunk_text, len(chunk_text.split()),
                )
                chunk_rows.append((chunk_id, chunk_text))

            await _store_chunk_embeddings(conn, org_id, chunk_rows)
            await conn.execute(
                """UPDATE documents
                   SET status='ready', chunk_count=$1, processed_at=NOW(),
                       source_type=$2, source_url=$3
                   WHERE id=$4""",
                len(chunks), source_type, source_url, doc_id,
            )
    except Exception as e:
        await pool.execute(
            "UPDATE documents SET status='failed', error_msg=$1 WHERE id=$2",
            str(e), doc_id,
        )


class KnowledgeBaseUrlReq(BaseModel):
    url: str
    title: str | None = None


@app.post("/bots/{bot_id}/documents/url", status_code=201)
async def upload_document_url(
    bot_id: str,
    body: KnowledgeBaseUrlReq,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    """Upload sumber URL ke knowledge base bot."""
    bot = await pool.fetchrow(
        "SELECT id FROM bots WHERE id=$1 AND org_id=$2", bot_id, user["org_id"]
    )
    if not bot:
        raise HTTPException(404, "Bot tidak ditemukan")

    url = (body.url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "URL harus diawali http:// atau https://")

    if _platform_check_limit:
        ok, detail = await _platform_check_limit(pool, user["org_id"], "knowledge")
        if not ok:
            raise HTTPException(
                402,
                f"Limit jumlah dokumen knowledge base paket '{detail['plan']}' tercapai "
                f"({detail['used']}/{detail['limit']}). Upgrade di /api/billing/checkout.",
            )
    else:
        doc_count = await pool.fetchval(
            "SELECT COUNT(*) FROM documents WHERE org_id=$1", user["org_id"]
        )
        doc_limit = await pool.fetchval(
            "SELECT doc_limit FROM organizations WHERE id=$1", user["org_id"]
        )
        if doc_count >= doc_limit:
            raise HTTPException(402, f"Batas dokumen ({doc_limit}) tercapai. Upgrade plan untuk upload lebih.")

    title = (body.title or _title_from_url(url)).strip() or _title_from_url(url)
    doc_id = str(uuid.uuid4())
    await pool.execute(
        """INSERT INTO documents (id, org_id, bot_id, filename, file_size, mime_type, status, source_type, source_url)
           VALUES ($1,$2,$3,$4,$5,$6,'pending','url',$7)""",
        doc_id, user["org_id"], bot_id,
        title, 0, "text/html", url,
    )

    await _process_document_sync(pool, doc_id, source_type="url", source_url=url)
    row = await pool.fetchrow("SELECT status, error_msg FROM documents WHERE id=$1", doc_id)
    return {"doc_id": doc_id, "status": row["status"], "error_msg": row["error_msg"]}


@app.get("/bots/{bot_id}/documents")
async def list_documents(
    bot_id: str,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    rows = await pool.fetch(
        """SELECT id, filename, file_size, status, chunk_count, error_msg, created_at, processed_at,
                  source_type, source_url
           FROM documents WHERE bot_id=$1 AND org_id=$2 ORDER BY created_at DESC""",
        bot_id, user["org_id"],
    )
    return [dict(r) for r in rows]


@app.delete("/bots/{bot_id}/documents/{doc_id}")
async def delete_document(
    bot_id: str,
    doc_id: str,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    # Pastikan dokumen milik org + bot yang sama
    doc = await pool.fetchrow(
        """SELECT id FROM documents
           WHERE id=$1 AND bot_id=$2 AND org_id=$3""",
        doc_id, bot_id, user["org_id"],
    )
    if not doc:
        raise HTTPException(404, "Dokumen tidak ditemukan")

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM doc_chunks WHERE document_id=$1", doc_id)
            await conn.execute("DELETE FROM documents WHERE id=$1", doc_id)

    return {"message": "Dokumen dihapus"}


class RagReindexReq(BaseModel):
    include_shared: bool = True
    limit_chunks: int = 2000


@app.post("/bots/{bot_id}/documents/reindex")
async def rag_reindex_embeddings(
    bot_id: str,
    body: RagReindexReq,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    raise HTTPException(410, "Reindex embedding sudah dihapus. Sistem sekarang memakai pencarian keyword internal.")


# ─── ROUTE: CHAT ──────────────────────────────────────────────

@app.post("/chat/{bot_id}")
async def chat(
    bot_id: str,
    body:   ChatReq,
    pool=Depends(get_pool),
):
    """
    Core chat endpoint — dipanggil oleh iframe widget.
    Public (tidak butuh user auth), tapi divalidasi via bot_id.
    """
    # 1. Load bot config
    bot = await pool.fetchrow(
        """SELECT b.id, b.org_id, b.system_prompt, b.language, b.temperature, b.reasoning_mode,
                  o.plan, o.billing_status, o.conv_limit
           FROM bots b
           JOIN organizations o ON o.id = b.org_id
           WHERE b.id=$1 AND b.status IN ('active','training')""",
        bot_id,
    )
    if not bot:
        raise HTTPException(404, "Bot tidak aktif")

    # Rate limit (endpoint public). Key: userId/email kalau ada, fallback anonymous.
    user_meta = body.user_meta or {}
    user_key = (
        user_meta.get("userId")
        or user_meta.get("email")
        or user_meta.get("name")
        or "anonymous"
    )
    try:
        rl = await _rate_limiter.check(
            user_id=str(user_key),
            bot_id=str(bot_id),
            org_id=str(bot["org_id"]),
            plan=str(bot["plan"] or "starter"),
            agent="supervisor",
        )
        if rl.status == LimitStatus.BLOCKED:
            raise HTTPException(
                status_code=429,
                detail=rl.message or "Terlalu banyak request. Coba lagi nanti.",
                headers={"Retry-After": str(rl.retry_after_s)},
            )
        if rl.status == LimitStatus.THROTTLED and rl.retry_after_s:
            await asyncio.sleep(min(2, rl.retry_after_s))
    except HTTPException:
        raise
    except Exception:
        # Jangan sampai rate limiter crash chat
        pass

    # 2. Cek quota percakapan bulan ini (Phase 2: gunakan check_limit dari subscriptions/plans)
    if _platform_check_limit:
        ok, detail = await _platform_check_limit(pool, bot["org_id"], "conversations")
        if not ok:
            raise HTTPException(
                429,
                f"Limit percakapan/bulan paket '{detail['plan']}' tercapai "
                f"({detail['used']}/{detail['limit']}). Upgrade di /api/billing/checkout.",
            )
    else:
        conv_this_month = await pool.fetchval(
            """SELECT COUNT(*) FROM conversations
               WHERE org_id=$1 AND started_at >= DATE_TRUNC('month', NOW())""",
            bot["org_id"],
        )
        if conv_this_month >= bot["conv_limit"]:
            raise HTTPException(429, "Batas percakapan bulan ini tercapai. Upgrade plan.")

    # 3. Ambil atau buat conversation
    conv_id = body.session_id
    if conv_id:
        conv = await pool.fetchrow(
            "SELECT id FROM conversations WHERE id=$1 AND bot_id=$2", conv_id, bot_id
        )
        if not conv:
            conv_id = None  # reset kalau tidak valid

    if not conv_id:
        conv_id = str(uuid.uuid4())
        user_meta = body.user_meta or {}
        await pool.execute(
            """INSERT INTO conversations
               (id, bot_id, org_id, end_user_id, end_user_name, end_user_email, end_user_meta)
               VALUES ($1,$2,$3,$4,$5,$6,$7)""",
            conv_id, bot_id, bot["org_id"],
            user_meta.get("userId"), user_meta.get("name"),
            user_meta.get("email"), json.dumps(user_meta),
        )

    # 4. Simpan pesan user
    user_msg_id = str(uuid.uuid4())
    await pool.execute(
        "INSERT INTO messages (id, conversation_id, role, content) VALUES ($1,$2,'user',$3)",
        user_msg_id, conv_id, body.message,
    )

    # 5. Ambil riwayat percakapan (max 10 pesan terakhir)
    history = await pool.fetch(
        """SELECT role, content FROM messages
           WHERE conversation_id=$1 ORDER BY created_at DESC LIMIT 10""",
        conv_id,
    )
    messages_for_claude = [
        {"role": r["role"], "content": r["content"]}
        for r in reversed(history)
    ]

    # 6. RAG: cari chunks relevan dari knowledge base
    relevant_chunks = await _retrieve_chunks(pool, bot["org_id"], body.message, bot_id=bot_id)

    # 7. Bangun system prompt
    system = _build_system_prompt(bot["system_prompt"], relevant_chunks, bot["language"])
    market_answer = ""
    if looks_like_market_price_query(body.message):
        try:
            crypto_quotes, stock_quotes = await asyncio.gather(
                fetch_crypto_quotes(body.message),
                fetch_stock_quotes(body.message),
            )
            market_answer = combine_market_answers(crypto_quotes, stock_quotes)
            market_blocks: list[str] = []
            crypto_ctx = build_crypto_market_context(crypto_quotes)
            stock_ctx = build_stock_market_context(stock_quotes)
            if stock_ctx:
                market_blocks.append(stock_ctx)
            if crypto_ctx:
                market_blocks.append(crypto_ctx)
            if market_blocks:
                system = (
                    system
                    + "\n\n## Data pasar finansial (real-time):\n"
                    + "\n\n".join(market_blocks)
                    + "\n\nInstruksi penting: Jika user bertanya harga/kurs/perubahan saham atau kripto, gunakan data pasar di atas sebagai jawaban utama. "
                      "Jangan bilang tidak punya akses real-time jika data pasar tersedia."
                )
        except Exception:
            market_answer = ""

    if cfg.news_enabled and _looks_like_news_query(body.message):
        try:
            rss_urls = [u.strip() for u in (cfg.news_rss_feeds or "").split(",") if u.strip()] or None
            news_needs_bodies = _news_needs_full_bodies(body.message)
            news_limit = max(1, min(10, int(cfg.news_max_items or 6)))
            if not news_needs_bodies:
                news_limit = min(news_limit, 3)
            news_timeout = float(cfg.news_timeout_seconds or 8.0)
            if not news_needs_bodies:
                news_timeout = min(news_timeout, 4.0)
            news_ctx = await asyncio.wait_for(
                build_news_context(
                    body.message,
                    limit=news_limit,
                    include_bodies=bool(cfg.news_include_bodies and news_needs_bodies),
                    fetch_timeout_s=news_timeout,
                    max_body_chars=max(200, min(6000, int(cfg.news_max_body_chars or 1400))),
                    max_concurrency=max(1, min(8, int(cfg.news_max_concurrency or 3))),
                    rss_urls=rss_urls,
                ),
                timeout=news_timeout,
            )
            if news_ctx:
                system = (
                    system
                    + "\n\n## Berita terkini (real-time):\n"
                    + news_ctx
                    + "\n\nInstruksi penting: Jawab berdasarkan data berita di atas dan jangan menambah fakta yang tidak tersedia. "
                      "Untuk setiap berita, cantumkan judul, media/feed, tanggal terbit jika ada, dan URL sumber. "
                      "Jika teks artikel tersedia, gunakan teks dan kutipan sebagai dasar utama. Jika hanya ringkasan RSS yang tersedia, "
                      "tetap rangkum informasi tersebut dan jelaskan singkat bahwa detail artikel penuh belum tersedia. "
                      "Jika user meminta solusi atau dampak bisnis, pisahkan dengan jelas antara fakta berita dan analisismu."
                )
        except Exception:
            pass

    # 7.5 Self-knowledge BotNesia: paket/usage/channel tenant + performa bisnis
    # (query DB ringan, tanpa LLM — selalu tersedia untuk semua mode/bot).
    try:
        from botnesia_knowledge import build_self_knowledge_context, build_business_context
        self_knowledge_context, business_context = await asyncio.gather(
            build_self_knowledge_context(pool, str(bot["org_id"]), bot_id, dict(bot)),
            build_business_context(pool, str(bot["org_id"]), bot_id),
        )
    except Exception:
        self_knowledge_context, business_context = "", ""
    if self_knowledge_context:
        system = system + "\n\n" + self_knowledge_context

    # 8. Panggil AI (Multi-Agent pipeline buatan kamu)
    t_start = time.monotonic()
    agent_meta: dict | None = None
    try:
        use_cloud = should_use_cloud(bot["plan"], bot["billing_status"])
        supervisor = get_supervisor(use_cloud)
        intelligence_context = {
            "bot_id": bot_id,
            "org_id": str(bot["org_id"]),
            "conversation_id": conv_id,
            "user_message": body.message,
            "messages": messages_for_claude,
            "knowledge_base_context": system,
            "resolved": False,
            "metadata": body.user_meta or {},
            "reasoning_mode": bot["reasoning_mode"],
            "self_knowledge_context": self_knowledge_context,
            "business_context": business_context,
        }
        result = await supervisor.process(intelligence_context)
        answer = result.final_answer
        # Shortcut data pasar mentah hanya untuk jalur cepat (standard). Mode Pro
        # sudah menganalisis data pasar via reasoning lens & sintesis jawaban —
        # jangan timpa dengan kutipan harga mentah.
        use_market_shortcut = bool(market_answer) and result.reasoning_mode_used != "pro"
        if use_market_shortcut:
            answer = market_answer
        if result.suggest_pro_mode:
            answer = (
                answer.rstrip()
                + "\n\nUntuk analisis lebih mendalam (alasan, konteks, dan kesimpulan) atas "
                  "pertanyaan seperti ini, aktifkan **Reasoning Mode: Pro** di pengaturan bot ini."
            )
        provider = "groq"
        model = cfg.groq_model
        model_used = "system:market-data" if use_market_shortcut else f"multi-agent:cloud:{provider}:{model}"
        input_tokens = 0
        output_tokens = 0
        latency_ms = result.total_latency_ms
        # Meta agent disimpan untuk logging internal, tidak dikirim ke frontend.
        agent_meta = {
            "confidence": result.confidence,
            "topics": result.topics,
            "suggested_followup": result.suggested_followup,
            "should_escalate": result.should_escalate,
            "escalation_urgency": result.escalation_urgency,
            "escalation_message": result.escalation_message,
            "recommended_team": result.recommended_team,
            "errors": result.errors,
            "reasoning_mode_used": result.reasoning_mode_used,
        }

        if result.should_escalate:
            await pool.execute(
                "UPDATE conversations SET handoff_needed=TRUE WHERE id=$1",
                conv_id,
            )
            # Phase 2: masukkan ke human queue secara otomatis
            if _platform_enqueue_handoff:
                urgency = (result.escalation_urgency or "medium").lower()
                valid_priorities = {"low", "medium", "high", "urgent"}
                priority = urgency if urgency in valid_priorities else "medium"
                try:
                    await _platform_enqueue_handoff(
                        pool,
                        org_id=bot["org_id"],
                        conversation_id=conv_id,
                        reason=result.escalation_message or "Confidence AI rendah — perlu bantuan manusia",
                        priority=priority,
                    )
                except Exception:
                    pass  # jangan crash chat karena handoff gagal
    except Exception as e:
        if market_answer:
            answer = market_answer
            model_used = "system:market-data"
            input_tokens = 0
            output_tokens = 0
            latency_ms = int((time.monotonic() - t_start) * 1000)
            agent_meta = {"errors": [str(e)], "fallback": "market-data"}
        else:
            raise HTTPException(503, f"AI service error: {str(e)}")

    # 9. Simpan respons bot
    bot_msg_id = str(uuid.uuid4())
    chunk_ids  = [c["id"] for c in relevant_chunks]
    await pool.execute(
        """INSERT INTO messages
           (id, conversation_id, role, content, model, input_tokens, output_tokens, latency_ms, source_chunks)
           VALUES ($1,$2,'assistant',$3,$4,$5,$6,$7,$8)""",
        bot_msg_id, conv_id, answer,
        model_used,
        input_tokens, output_tokens, latency_ms,
        chunk_ids,
    )

    # 10. Update stats
    await pool.execute(
        """UPDATE conversations SET msg_count=msg_count+2, last_msg_at=NOW() WHERE id=$1""",
        conv_id,
    )

    if agent_meta is not None:
        try:
            from intelligence.pipeline import persist_intelligence
            asyncio.create_task(
                persist_intelligence(
                    dict(intelligence_context),
                    result,
                    bot_response=answer,
                )
            )
        except Exception:
            logger.exception("Gagal menjadwalkan persistensi Intelligence")

    resp = {
        "answer":      answer,
        "session_id":  conv_id,
        "latency_ms":  latency_ms,
    }

    # Observability: log request (best-effort).
    try:
        await pool.execute(
            """INSERT INTO request_logs
               (id, org_id, bot_id, conversation_id, route, model, latency_ms, error)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
            str(uuid.uuid4()),
            bot["org_id"],
            bot_id,
            conv_id,
            "/chat/{bot_id}",
            model_used,
            latency_ms,
            json.dumps(agent_meta.get("errors")) if agent_meta else None,
        )
    except Exception:
        pass
    return resp


async def _retrieve_chunks(
    pool: asyncpg.Pool,
    org_id: str,
    query: str,
    *,
    bot_id: str | None = None,
    top_k: int = 5,
) -> list[dict]:
    """
    Hybrid retrieval: keyword + lokal vector embedding.
    Selalu dibatasi ke org yang sama; jika bot_id ada, prioritaskan dokumen bot itu + shared docs.
    """
    q = (query or "").strip()
    if not q:
        return []

    rows = await _fetch_kb_candidates(pool, str(org_id), bot_id=str(bot_id) if bot_id else None, limit=2000)
    if not rows:
        return []

    query_vec = _text_to_embedding(q)
    query_tokens = _tokenize_text(q)
    scored: list[tuple[float, dict]] = []
    for row in rows:
        score = _score_kb_candidate(query_tokens, query_vec, row.get("content") or "", row.get("embedding"))
        if score > 0:
            scored.append((score, row))

    scored.sort(key=lambda item: item[0], reverse=True)
    out = []
    for _, row in scored[:top_k]:
        out.append(
            {
                "id": row["id"],
                "content": row["content"],
                "document_id": row.get("document_id"),
                "chunk_index": row.get("chunk_index"),
                "filename": row.get("filename"),
                "source_type": row.get("source_type"),
                "source_url": row.get("source_url"),
            }
        )
    return out




KB_EMBED_DIM = 256


def _tokenize_text(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9_]+", (text or "").lower())
    return [t for t in tokens if len(t) >= 2]


def _chunk_text(text: str, size: int = 350) -> list[str]:
    words = (text or "").split()
    if not words:
        return []
    size = max(80, min(700, int(size)))
    return [" ".join(words[i:i + size]).strip() for i in range(0, len(words), size)]


def _text_to_embedding(text: str, dim: int | None = None) -> list[float]:
    dim = int(dim or cfg.kb_embedding_dim or KB_EMBED_DIM)
    dim = max(32, min(1024, dim))
    vec = np.zeros(dim, dtype=np.float32)
    tokens = _tokenize_text(text)
    if not tokens:
        return vec.tolist()
    for tok in tokens:
        h = int(hashlib.sha1(tok.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        vec[idx] += 1.0 + (len(tok) / 12.0)
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec /= norm
    return vec.astype(np.float32).tolist()


def _cosine_similarity(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b:
        return 0.0
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    if va.shape != vb.shape or not va.size:
        return 0.0
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom <= 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def _score_kb_candidate(query_tokens: list[str], query_vec: list[float], content: str, embedding: object) -> float:
    content_lower = (content or "").lower()
    keyword_hits = sum(1 for t in query_tokens if t in content_lower)
    kw_score = keyword_hits / max(1, len(query_tokens))
    emb_score = 0.0
    if isinstance(embedding, list):
        emb_score = _cosine_similarity(query_vec, embedding)
    return (emb_score * 0.78) + (kw_score * 0.22)


def _title_from_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc or "website"
        path = (parsed.path or "/").strip("/")
        slug = path.replace("/", " ").replace("-", " ")
        title = f"{host} {slug}".strip()
        return title[:160] if title else host[:160]
    except Exception:
        return url[:160]


_TAG_RE = re.compile(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>")


def _strip_html(text: str) -> str:
    t = html.unescape(text or "")
    t = re.sub(r"(?is)<[^>]+>", " ", t)
    t = re.sub(r"&nbsp;", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _extract_web_text(html_text: str, max_chars: int = 16000) -> str:
    if not html_text:
        return ""
    h = _TAG_RE.sub(" ", html_text)
    m = re.search(r"(?is)<article[^>]*>(.*?)</article>", h)
    if m:
        h = m.group(1)
    paragraphs = re.findall(r"(?is)<p[^>]*>(.*?)</p>", h)
    texts: list[str] = []
    for p in paragraphs:
        t = _strip_html(p)
        if len(t) >= 30:
            texts.append(t)
    if not texts:
        t = _strip_html(h)
        return t[:max_chars].strip()
    out = "\n".join(texts)
    return out[:max_chars].strip()


async def _fetch_website_text(url: str, timeout_s: float = 15.0) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    headers = {"User-Agent": "BotNesia/1.0 (+knowledge-base)"}
    async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True, headers=headers) as client:
        try:
            res = await client.get(url)
            res.raise_for_status()
            text = _extract_web_text(res.text, max_chars=16000)
            if len(text) >= 300:
                return text
        except Exception:
            pass
        try:
            proxy = await client.get("https://r.jina.ai/" + url)
            proxy.raise_for_status()
            text = _extract_web_text(proxy.text, max_chars=16000)
            if text:
                return text
        except Exception:
            pass
    return ""


async def _store_chunk_embeddings(
    conn: asyncpg.Connection,
    org_id: str,
    chunk_rows: list[tuple[str, str]],
) -> None:
    if not chunk_rows:
        return
    for chunk_id, chunk_text in chunk_rows:
        embedding = _text_to_embedding(chunk_text)
        await conn.execute(
            """INSERT INTO doc_chunk_embeddings (chunk_id, org_id, embedding, model)
               VALUES ($1,$2,$3,$4)
               ON CONFLICT (chunk_id) DO UPDATE
               SET org_id=EXCLUDED.org_id,
                   embedding=EXCLUDED.embedding,
                   model=EXCLUDED.model""",
            chunk_id,
            org_id,
            embedding,
            f"hash-emb-{cfg.kb_embedding_dim or KB_EMBED_DIM}",
        )


async def _fetch_kb_candidates(
    pool: asyncpg.Pool,
    org_id: str,
    *,
    bot_id: str | None = None,
    limit: int = 2000,
) -> list[dict]:
    params: list[object] = [org_id]
    where = ["c.org_id=$1"]
    if bot_id:
        params.append(bot_id)
        where.append("(d.bot_id=$2 OR d.bot_id IS NULL)")
    where_sql = " AND ".join(where)
    sql = f"""
        SELECT c.id, c.content, c.document_id, c.chunk_index, c.created_at,
               d.filename, d.source_type, d.source_url, e.embedding
        FROM doc_chunks c
        JOIN documents d ON d.id = c.document_id
        LEFT JOIN doc_chunk_embeddings e ON e.chunk_id = c.id
        WHERE {where_sql}
        ORDER BY c.created_at DESC
        LIMIT {int(limit)}
    """
    rows = await pool.fetch(sql, *params)
    out: list[dict] = []
    for row in rows:
        emb = row.get("embedding")
        if isinstance(emb, str):
            try:
                emb = json.loads(emb)
            except Exception:
                emb = None
        out.append({**dict(row), "embedding": emb})
    return out


def _build_system_prompt(
    custom_prompt: str | None,
    chunks: list[dict],
    language: str,
) -> str:
    lang_note = "Jawab selalu dalam Bahasa Indonesia." if language == "id" else ""

    context = ""
    if chunks:
        context = "\n\n## Konteks dari knowledge base:\n"
        context += "\n---\n".join(c["content"][:800] for c in chunks)

    base = custom_prompt or (
        "Kamu adalah asisten customer service yang helpful, sopan, dan profesional. "
        "Jawab berdasarkan informasi yang tersedia. Kalau tidak tahu, akui dengan jujur "
        "dan tawarkan untuk disambungkan ke tim manusia."
    )

    style_guide = (
        "## Gaya jawaban\n"
        "Tulis jawaban dengan gaya seperti asisten AI modern (mirip Claude/ChatGPT): jelas, ringkas, "
        "dan langsung ke inti, tapi tetap ramah dan natural - bukan kaku seperti robot.\n"
        "- Buka dengan jawaban atau inti informasi yang dicari user, baru tambahkan detail pendukung.\n"
        "- Gunakan paragraf pendek (1-3 kalimat). Pisahkan ide berbeda dengan baris baru.\n"
        "- Kalau menjelaskan beberapa poin, langkah, atau opsi, gunakan daftar bernomor atau bullet "
        "(`-`), jangan digabung jadi satu paragraf panjang.\n"
        "- Gunakan **teks tebal** untuk menyorot istilah, nama produk, harga, atau hal penting lainnya.\n"
        "- Hindari basa-basi berlebihan, pengulangan, dan kalimat pembuka generik seperti "
        '"Tentu, saya akan membantu...". Sapaan singkat di awal percakapan saja sudah cukup.\n'
        "- Sesuaikan panjang jawaban dengan kompleksitas pertanyaan: pertanyaan sederhana dijawab singkat, "
        "pertanyaan kompleks dijelaskan lebih lengkap dengan struktur yang rapi."
    )

    return f"{base}\n\n{style_guide}\n\n{lang_note}{context}"


def _looks_like_news_query(text: str) -> bool:
    t = (text or "").lower()
    keys = [
        "berita",
        "news",
        "terkini",
        "hari ini",
        "trending",
        "update",
        "headline",
        "artikel",
        "ringkas",
        "rangkum",
        "ringkasan",
        "summary",
    ]
    if "http://" in t or "https://" in t:
        return True
    return any(k in t for k in keys)


def _news_needs_full_bodies(text: str) -> bool:
    t = (text or "").lower()
    detail_keys = [
        "detail",
        "lengkap",
        "isi",
        "full",
        "selengkapnya",
        "kutipan",
        "quote",
        "analisis",
        "penjelasan",
        "breakdown",
    ]
    return any(k in t for k in detail_keys)


# ─── ROUTE: ANALYTICS ─────────────────────────────────────────

@app.get("/bots/{bot_id}/analytics")
async def get_analytics(
    bot_id: str,
    days:   int = 30,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    bot = await pool.fetchrow(
        "SELECT id FROM bots WHERE id=$1 AND org_id=$2", bot_id, user["org_id"]
    )
    if not bot:
        raise HTTPException(404, "Bot tidak ditemukan")

    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Summary
    summary = await pool.fetchrow(
        """SELECT
             COUNT(DISTINCT c.id)                    AS total_convs,
             COUNT(m.id)                             AS total_msgs,
             ROUND(AVG(c.rating) FILTER
               (WHERE c.rating IS NOT NULL), 2)      AS avg_rating,
             AVG(m.latency_ms) FILTER
               (WHERE m.role='assistant')            AS avg_latency_ms,
             COUNT(c.id) FILTER
               (WHERE c.handoff_needed)              AS handoff_count
           FROM conversations c
           LEFT JOIN messages m ON m.conversation_id = c.id
           WHERE c.bot_id=$1 AND c.started_at >= $2""",
        bot_id, since,
    )

    # Volume harian
    daily = await pool.fetch(
        """SELECT DATE(started_at) AS date, COUNT(*) AS convs
           FROM conversations WHERE bot_id=$1 AND started_at >= $2
           GROUP BY DATE(started_at) ORDER BY date""",
        bot_id, since,
    )

    # Top pertanyaan
    top_q = await pool.fetch(
        """SELECT m.content, COUNT(*) AS frequency
           FROM messages m
           JOIN conversations c ON c.id = m.conversation_id
           WHERE c.bot_id=$1 AND m.role='user' AND m.created_at >= $2
           GROUP BY m.content ORDER BY frequency DESC LIMIT 10""",
        bot_id, since,
    )

    return {
        "summary":       dict(summary),
        "daily_volume":  [dict(r) for r in daily],
        "top_questions": [dict(r) for r in top_q],
    }


# ─── ROUTE: CONVERSATIONS ─────────────────────────────────────

@app.get("/bots/{bot_id}/conversations")
async def list_conversations(
    bot_id: str,
    limit:  int = 20,
    offset: int = 0,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    rows = await pool.fetch(
        """SELECT id, end_user_name, end_user_email, msg_count,
                  resolved, handoff_needed, rating, started_at, last_msg_at
           FROM conversations WHERE bot_id=$1 AND org_id=$2
           ORDER BY last_msg_at DESC LIMIT $3 OFFSET $4""",
        bot_id, user["org_id"], limit, offset,
    )
    return [dict(r) for r in rows]


@app.get("/conversations/{conv_id}/messages")
async def get_messages(
    conv_id: str,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    # Verifikasi kepemilikan
    conv = await pool.fetchrow(
        "SELECT id FROM conversations WHERE id=$1 AND org_id=$2",
        conv_id, user["org_id"],
    )
    if not conv:
        raise HTTPException(404, "Conversation tidak ditemukan")

    rows = await pool.fetch(
        "SELECT id, role, content, latency_ms, created_at, source_chunks FROM messages "
        "WHERE conversation_id=$1 ORDER BY created_at",
        conv_id,
    )
    return [dict(r) for r in rows]


@app.get("/messages/{message_id}/sources")
async def get_message_sources(
    message_id: str,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    msg = await pool.fetchrow(
        """
        SELECT m.id, m.source_chunks, c.org_id
        FROM messages m
        JOIN conversations c ON c.id = m.conversation_id
        WHERE m.id=$1 AND c.org_id=$2
        """,
        message_id,
        user["org_id"],
    )
    if not msg:
        raise HTTPException(404, "Message tidak ditemukan")

    chunk_ids = msg["source_chunks"] or []
    if not chunk_ids:
        return []

    rows = await pool.fetch(
        """
        SELECT id, content, document_id, chunk_index, created_at
        FROM doc_chunks
        WHERE org_id=$1 AND id = ANY($2::uuid[])
        ORDER BY chunk_index ASC
        """,
        user["org_id"],
        chunk_ids,
    )
    # Attach filename
    doc_ids = list({str(r["document_id"]) for r in rows if r.get("document_id")})
    name_map = {}
    if doc_ids:
        docs = await pool.fetch(
            "SELECT id, filename FROM documents WHERE org_id=$1 AND id = ANY($2::uuid[])",
            user["org_id"],
            doc_ids,
        )
        name_map = {str(d["id"]): d["filename"] for d in docs}

    out = []
    for r in rows:
        d_id = str(r["document_id"])
        out.append(
            {
                "chunk_id": str(r["id"]),
                "document_id": d_id,
                "filename": name_map.get(d_id),
                "chunk_index": int(r["chunk_index"]),
                "content": (r["content"] or "")[:1200],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
        )
    return out


# ─── ROUTE: WEBHOOKS ──────────────────────────────────────────

@app.post("/webhooks", status_code=201)
async def create_webhook(
    body: dict,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    wh_id  = str(uuid.uuid4())
    secret = os.urandom(24).hex()
    await pool.execute(
        """INSERT INTO webhook_configs (id, org_id, url, secret, events)
           VALUES ($1,$2,$3,$4,$5)""",
        wh_id, user["org_id"],
        body["url"], secret, body.get("events", []),
    )
    return {"webhook_id": wh_id, "secret": secret,
            "note": "Simpan secret ini — tidak akan ditampilkan lagi."}


async def dispatch_webhook(org_id: str, event: str, payload: dict, pool: asyncpg.Pool):
    """Kirim event ke semua webhook aktif milik org."""
    hooks = await pool.fetch(
        """SELECT url, secret FROM webhook_configs
           WHERE org_id=$1 AND is_active=TRUE AND $2 = ANY(events)""",
        org_id, event,
    )
    for hook in hooks:
        body_str = str(payload).encode()
        sig = hmac.new(
            hook["secret"].encode(),
            body_str,
            hashlib.sha256,
        ).hexdigest()
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    hook["url"],
                    json={"event": event, "payload": payload},
                    headers={"X-BotNesia-Signature": sig},
                )
        except Exception:
            pass  # Gagal kirim webhook tidak boleh crash request utama


# ─── ROUTE: API KEYS (Scale tier) ─────────────────────────────

@app.post("/api-keys", status_code=201)
async def create_api_key(
    body: dict,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    # Cek plan
    plan = await pool.fetchval(
        "SELECT plan FROM organizations WHERE id=$1", user["org_id"]
    )
    if plan != "scale":
        raise HTTPException(402, "API key hanya tersedia untuk Scale tier")

    raw_key = f"bn_live_{os.urandom(20).hex()}"
    prefix  = raw_key[:14]

    await pool.execute(
        """INSERT INTO api_keys (id, org_id, name, key_hash, key_prefix)
           VALUES ($1,$2,$3,$4,$5)""",
        str(uuid.uuid4()), user["org_id"],
        body.get("name", "API Key"),
        hash_password(raw_key), prefix,
    )

    return {
        "key":  raw_key,
        "note": "Simpan key ini — hanya ditampilkan sekali.",
    }


# ─── HEALTH CHECK ─────────────────────────────────────────────

@app.get("/health")
async def health():
    pool = await get_pool_safe()
    db_ok = False
    schema_ok = False
    if pool:
        try:
            await pool.fetchval("SELECT 1")
            db_ok = True
            schema_ok = await ensure_schema(pool)
        except Exception:
            pass
    return {
        "status":  "ok" if db_ok and schema_ok and bool(cfg.groq_api_key) else "degraded",
        "db":      db_ok,
        "schema":  schema_ok if db_ok else False,
        "ai": {
            "configured": bool(cfg.groq_api_key),
            "provider": "groq" if cfg.groq_api_key else None,
            "model": cfg.groq_model if cfg.groq_api_key else None,
        },
        "model":   f"groq:{cfg.groq_model}",
        "version": "1.0.0",
    }


# ═══════════════════════════════════════════════════════════════════════
# PHASE 2 — BUSINESS PLATFORM (bn_platform) WIRING
#
# CATATAN POLA: factory function menerima `get_pool`/`get_current_user`/
# `require_permission`/... sebagai parameter (dependency injection) agar
# modul bn_platform TIDAK perlu `from main import ...` di top-level
# (yang akan menyebabkan circular import karena main.py sangat besar).
# Semua dependency dioper secara eksplisit di sini setelah terdefinisi.
# ═══════════════════════════════════════════════════════════════════════
try:
    from bn_platform.rbac import make_permission_checker, build_rbac_router
    from bn_platform.billing import build_billing_router, check_limit
    from bn_platform.handoff import build_handoff_router, enqueue_handoff
    from bn_platform.omnichannel import build_omnichannel_router
    from bn_platform.lead_engine import build_lead_router
    from bn_platform.marketplace import build_marketplace_router
    from bn_platform.revenue_intel import build_revenue_router
    from bn_platform.security import build_security_router, write_audit_log as _platform_audit_log_fn
    from bn_platform.observability import instrument_app, record_db_pool_stats

    # ── 0. Set platform callbacks untuk Phase 1 endpoints ───────
    # (variabel sudah dideklarasikan di level modul — tidak perlu global keyword)
    _platform_check_limit = check_limit
    _platform_enqueue_handoff = enqueue_handoff
    _platform_write_audit = _platform_audit_log_fn

    # ── 1. Prometheus middleware + GET /metrics ──────────────────
    instrument_app(app)

    # ── 2. RBAC require_permission dependency factory ────────────
    require_permission = make_permission_checker(
        get_current_user=get_current_user, get_pool=get_pool,
    )

    # ── 3. Adapter: pesan masuk Telegram → pipeline chat existing ─
    async def _route_inbound_platform_message(
        *, org_id: str, bot_id: str, channel: str,
        external_user_id: str, text: str, display_name: str,
    ) -> str:
        """Teruskan pesan masuk omnichannel (Telegram/dst) ke pipeline chat existing.
        Pola identik dengan `_meta_route_and_reply_whatsapp` — session_id deterministik
        per (channel, external_user_id) supaya percakapan tetap satu thread."""
        pool = await get_pool_safe()
        if not pool:
            return "Maaf, sistem sedang tidak tersedia. Coba lagi sebentar."
        session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{channel}:{external_user_id}"))
        user_meta = {"userId": external_user_id, "channel": channel, "display_name": display_name}
        req = ChatReq(message=text, session_id=session_id, user_meta=user_meta)
        try:
            resp = await chat(bot_id=bot_id, body=req, pool=pool)
            return (resp.get("answer") if isinstance(resp, dict) else None) or ""
        except Exception:
            logger.exception("Route inbound platform message failed (org=%s bot=%s channel=%s)", org_id, bot_id, channel)
            return "Maaf, terjadi kesalahan. Tim kami sudah diberitahu."

    # ── 4. Daftarkan semua router Phase 2 ───────────────────────
    #    prefix="/api" konsisten dengan endpoint existing di main.py
    #    Catatan webhook: URL yang didaftarkan ke Midtrans/Xendit/Telegram
    #    harus menyertakan "/api" prefix ini (mis. {APP_URL}/api/billing/webhooks/midtrans)
    app.include_router(
        build_rbac_router(get_pool=get_pool, get_current_user=get_current_user, hash_password=hash_password, check_limit=check_limit),
        prefix="/api",
    )
    app.include_router(
        build_billing_router(
            get_pool=get_pool, get_current_user=get_current_user,
            require_permission=require_permission,
            dispatch_webhook=dispatch_webhook,
        ),
        prefix="/api",
    )
    app.include_router(
        build_handoff_router(
            get_pool=get_pool, get_current_user=get_current_user,
            require_permission=require_permission,
            dispatch_webhook=dispatch_webhook,
        ),
        prefix="/api",
    )
    app.include_router(
        build_omnichannel_router(
            get_pool=get_pool, get_current_user=get_current_user,
            require_permission=require_permission,
            app_url=cfg.app_url,
            route_inbound_message=_route_inbound_platform_message,
            check_limit=check_limit,
        ),
        prefix="/api",
    )
    app.include_router(
        build_lead_router(
            get_pool=get_pool, get_current_user=get_current_user,
            require_permission=require_permission,
        ),
        prefix="/api",
    )
    app.include_router(
        build_marketplace_router(
            get_pool=get_pool, get_current_user=get_current_user,
            require_permission=require_permission,
            check_limit=check_limit,
        ),
        prefix="/api",
    )
    app.include_router(
        build_revenue_router(get_pool=get_pool, get_current_user=get_current_user),
        prefix="/api",
    )
    app.include_router(
        build_security_router(
            get_pool=get_pool, get_current_user=get_current_user,
            require_permission=require_permission,
        ),
        prefix="/api",
    )

    # ── 5. Admin Dashboard & Customer 360 — agregasi ringan ─────
    from bn_platform.lead_engine import lead_funnel_summary
    from bn_platform.omnichannel import inbox_summary as _inbox_summary

    @app.get("/api/dashboard/overview")
    async def dashboard_overview(
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        """Admin Dashboard: metrik harian/mingguan tenant ini."""
        org_id = user["org_id"]
        # Total conversation & message count
        conv_row = await pool.fetchrow(
            """SELECT COUNT(*) AS total_convs,
                      COUNT(*) FILTER (WHERE started_at >= NOW() - INTERVAL '30 days') AS convs_30d
               FROM conversations WHERE org_id=$1""",
            org_id,
        )
        # Active users (unique end_user_id last 30 days)
        active_users = await pool.fetchval(
            "SELECT COUNT(DISTINCT end_user_id) FROM conversations WHERE org_id=$1 AND started_at >= NOW() - INTERVAL '30 days'",
            org_id,
        )
        # Conversion rate (resulted_in_purchase signals)
        conv_rate_row = await pool.fetchrow(
            """SELECT COUNT(*) AS total_signals,
                      COUNT(*) FILTER (WHERE resulted_in_purchase) AS converted
               FROM sales_signals ss
               JOIN conversations c ON c.id = ss.conversation_id
               WHERE c.org_id=$1 AND ss.created_at >= NOW() - INTERVAL '30 days'""",
            org_id,
        )
        conversion_rate = 0.0
        if conv_rate_row and conv_rate_row["total_signals"]:
            conversion_rate = round(conv_rate_row["converted"] / conv_rate_row["total_signals"], 4)
        # FAQ growth (new entries published last 30 days)
        faq_growth = await pool.fetchval(
            "SELECT COUNT(*) FROM faq_entries WHERE org_id=$1 AND status='published' AND created_at >= NOW() - INTERVAL '30 days'",
            org_id,
        )
        # Lead funnel
        funnel = await lead_funnel_summary(pool, org_id=org_id)
        # Inbox summary
        inbox = await _inbox_summary(pool, org_id=org_id)
        return {
            "total_conversations": conv_row["total_convs"],
            "conversations_30d": conv_row["convs_30d"],
            "active_users_30d": active_users,
            "conversion_rate_30d": conversion_rate,
            "faq_entries_published_30d": faq_growth,
            "lead_funnel": funnel,
            "inbox": inbox,
        }

    @app.get("/api/customers/{end_user_id}/360")
    async def customer_360(
        end_user_id: str,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
        bot_id: str | None = None,
    ):
        """Customer 360: profil lengkap, riwayat chat, pembelian, komplain, lead score."""
        org_id = user["org_id"]
        # Profil dari Phase 1 Intelligence
        profile = await pool.fetchrow(
            """SELECT * FROM customer_profiles WHERE org_id=$1 AND end_user_id=$2
               ORDER BY updated_at DESC LIMIT 1""",
            org_id, end_user_id,
        ) if not bot_id else await pool.fetchrow(
            "SELECT * FROM customer_profiles WHERE org_id=$1 AND bot_id=$2 AND end_user_id=$3",
            org_id, bot_id, end_user_id,
        )
        # Riwayat percakapan (10 terakhir)
        conversations = await pool.fetch(
            """SELECT id, started_at, msg_count, channel, channel_account_id, assigned_agent_id, closed_at
               FROM conversations WHERE org_id=$1 AND end_user_id=$2
               ORDER BY started_at DESC LIMIT 10""",
            org_id, end_user_id,
        )
        # Sinyal penjualan & keluhan (60 hari terakhir)
        signals = await pool.fetch(
            """SELECT ss.signal_type, ss.created_at, ss.resulted_in_purchase, c.id AS conv_id
               FROM sales_signals ss
               JOIN conversations c ON c.id = ss.conversation_id
               WHERE c.org_id=$1 AND c.end_user_id=$2 AND ss.created_at >= NOW() - INTERVAL '60 days'
               ORDER BY ss.created_at DESC LIMIT 30""",
            org_id, end_user_id,
        )
        # Skor lead terbaru
        lead = await pool.fetchrow(
            """SELECT score, category, signals, recommended_action, computed_at
               FROM lead_scores WHERE org_id=$1 AND end_user_id=$2
               ORDER BY computed_at DESC LIMIT 1""",
            org_id, end_user_id,
        )
        return {
            "profile": dict(profile) if profile else None,
            "recent_conversations": [dict(r) for r in conversations],
            "recent_signals": [dict(r) for r in signals],
            "lead": dict(lead) if lead else None,
        }

    logger.info("bn_platform Phase 2 berhasil di-mount: RBAC, Billing, Handoff, Omnichannel, "
                "Leads, Marketplace, Revenue, Security, Observability (/metrics), Dashboard, Customer 360")

except ImportError as _bn_err:
    logger.warning("bn_platform belum ter-install atau dependency kurang (%s) — Phase 2 dilewati. "
                   "Jalankan: pip install cryptography prometheus-client", _bn_err)


# Intelligence endpoints share the main process in local/single-service mode.
try:
    from intelligence.routes_intelligence import intel_router
    app.include_router(intel_router)
    logger.info("Intelligence routes mounted at /intel")
except ImportError as _intel_err:
    logger.warning("Intelligence routes tidak tersedia: %s", _intel_err)
