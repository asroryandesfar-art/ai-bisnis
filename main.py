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

import csv
import hashlib
import hmac
import html
import io
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
import executive_agent as exec_agent_module
from knowledge_builder_agent import KnowledgeBuilderAgent
import knowledge_seeder
import tool_registry
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
    db_clear_meta_phone_mapping,
    db_set_whatsapp_account,
    db_get_whatsapp_account,
    db_get_whatsapp_accounts,
    db_clear_whatsapp_account,
    decrypt_dict,
)
from whatsapp_embedded_signup import (
    exchange_code_for_token as wa_exchange_code_for_token,
    register_phone_number as wa_register_phone_number,
    subscribe_app_to_waba as wa_subscribe_app_to_waba,
    unsubscribe_app_from_waba as wa_unsubscribe_app_from_waba,
)
from media_gen import (
    ReplicateRateLimitError,
    generate_image_replicate,
)
import image_providers
import vision_engine
import document_generator
import storage_backend
import kb_embeddings
import computer_agent
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
import language_middleware


# ─── CONFIG ──────────────────────────────────────────────────

class Settings(BaseSettings):
    database_url:         str = "postgresql+asyncpg://user:pass@localhost/botnesia"
    db_connect_timeout_seconds: float = 2.5
    secret_key:           str = "change-me-in-production"
    replicate_api_token:  str = ""
    replicate_api_tokens: str = ""  # optional: comma-separated Replicate tokens
    replicate_image_version: str = ""  # Replicate model version id for image generation
    replicate_image_model: str = ""  # Replicate model id (e.g. owner/name) for gated/hidden versions
    replicate_image_input_json: str = ""  # optional JSON string
    replicate_image_queue_size: int = 8
    replicate_image_workers: int = 1
    replicate_min_request_gap_seconds: float = 1.5
    replicate_media_cooldown_seconds: int = 12
    # Phase 3 Multimodal — image provider abstraction (graceful-degrade per provider key)
    image_provider:       str = "replicate"  # replicate | openai | google_imagen | stability | fal
    image_provider_fallback_order: str = "google_imagen,replicate"  # dipakai saat caller TIDAK minta provider spesifik
    openai_api_key:       str = ""
    google_api_key:       str = ""       # legacy name, still read from GOOGLE_API_KEY
    gemini_api_key:       str = ""       # preferred: GEMINI_API_KEY
    gemini_model:         str = "gemini-2.5-flash"
    gemini_pro_model:     str = "gemini-2.5-pro"
    gemini_timeout:       int = 30
    gemini_max_retry:     int = 3
    stability_api_key:    str = ""
    fal_api_key:          str = ""
    image_moderation_enabled: bool = True
    # Groq
    groq_api_key:         str = ""
    groq_model:           str = "meta-llama/llama-4-scout-17b-16e-instruct"
    groq_cheap_model:     str = "llama-3.1-8b-instant"
    groq_base_url:        str = "https://api.groq.com/openai/v1"
    groq_whisper_model:   str = "whisper-large-v3-turbo"

    @property
    def effective_gemini_api_key(self) -> str:
        """GEMINI_API_KEY takes priority over legacy GOOGLE_API_KEY."""
        return self.gemini_api_key or self.google_api_key

    # Integrations (optional)
    gmail_client_id:      str = ""
    gmail_client_secret:  str = ""
    gmail_redirect_uri:   str = "http://127.0.0.1:8000/integrations/gmail/callback"
    gmail_poll_enabled:   bool = True
    gmail_poll_interval_seconds: int = 60
    gmail_poll_max_messages: int = 5
    gmail_poll_mark_read: bool = True
    meta_verify_token:    str = ""
    meta_app_secret:      str = ""  # opsional (untuk signature verify, dan client_secret OAuth)
    meta_webhook_default_bot_id: str = ""  # optional fallback
    meta_api_version:     str = "v19.0"
    # WhatsApp Embedded Signup (Meta App Dashboard > WhatsApp > Embedded Signup)
    meta_app_id:          str = ""  # App ID (client_id untuk FB.login() & tukar code)
    meta_embedded_signup_config_id: str = ""  # Configuration ID Embedded Signup
    meta_register_pin:    str = "112233"  # PIN two-step verification saat register nomor
    news_enabled:         bool = True
    news_max_items:       int = 6
    news_timeout_seconds: float = 8.0
    news_include_bodies:  bool = True
    news_max_body_chars:  int = 1400
    news_max_concurrency: int = 3
    news_rss_feeds:       str = ""  # comma-separated news source URLs: RSS/Atom/article links (optional)
    # Real-Time Knowledge Layer — general web search (WebSearchAgent)
    # Urutan provider: SearXNG dulu (gratis, self-hosted, tanpa API key),
    # Tavily sebagai cadangan otomatis kalau SearXNG tidak terkonfigurasi/gagal.
    searxng_url:          str = ""  # contoh: http://localhost:8080 (base URL instance SearXNG)
    search_api_key:       str = ""  # optional, cadangan: Tavily API key (https://tavily.com)
    kb_embedding_dim:     int = 256
    pinecone_api_key:     str = ""
    pinecone_index:       str = "botnesia-chunks"
    jwt_algorithm:        str = "HS256"
    jwt_expire_hours:     int = 24 * 7
    storage_bucket:       str = "botnesia-docs"
    app_name:             str = "BotNesia"
    app_url:              str = "https://botnesia.id"
    cors_allowed_origins: str = "*"  # comma-separated, "*" = allow semua (default lama)

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
_platform_evaluate_handoff = None  # deterministic trigger evaluation
_platform_write_audit = None   # (pool, org_id, actor_user_id, actor_email, action, ...) → None
_platform_create_session = None  # (pool, user_id, org_id, ip_address, user_agent, expires_at) → {"id","is_suspicious"}
_platform_touch_session = None   # (pool, session_id) → bool (False jika revoked/expired)
_platform_revoke_session = None  # (pool, session_id, org_id, reason) → dict|None
_platform_check_rate_limit = None  # (key, max_req) → None, raises HTTPException(429)
_platform_require_permission = None  # (permission_key) → async checker(user=, pool=) -> dict, raises 403

# Multi-agent supervisor singleton (cloud-only)
_supervisor_cloud: SupervisorAgent | None = None
_knowledge_builder_agent: KnowledgeBuilderAgent | None = None

# Background tasks
_gmail_poll_task: asyncio.Task | None = None
_gmail_poll_stop: asyncio.Event | None = None
_intelligence_learning_task: asyncio.Task | None = None
_intelligence_learning_stop: asyncio.Event | None = None
_meta_refresh_task: asyncio.Task | None = None
_meta_refresh_stop: asyncio.Event | None = None
_platform_route_inbound = None


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
_media_user_cooldowns: dict[str, float] = {}


def should_use_cloud(plan: str, billing_status: str) -> bool:
    # Cloud-only: semua plan pakai Groq.
    return True


def get_supervisor(use_cloud: bool) -> SupervisorAgent:
    global _supervisor_cloud
    if not cfg.effective_gemini_api_key and not cfg.groq_api_key:
        raise RuntimeError(
            "Cloud AI belum dikonfigurasi. "
            "Isi GEMINI_API_KEY (atau GOOGLE_API_KEY) atau GROQ_API_KEY di .env lalu restart server."
        )

    if _supervisor_cloud is None:
        _supervisor_cloud = SupervisorAgent(
            api_key=cfg.groq_api_key,
            model=cfg.groq_model,
            base_url=(cfg.groq_base_url or "").strip() or None,
            app_url=cfg.app_url,
            gemini_api_key=cfg.effective_gemini_api_key,
            gemini_model=cfg.gemini_model,
            gemini_pro_model=cfg.gemini_pro_model,
            gemini_timeout=cfg.gemini_timeout,
            gemini_max_retry=cfg.gemini_max_retry,
        )

    return _supervisor_cloud


def get_knowledge_builder_agent() -> KnowledgeBuilderAgent:
    global _knowledge_builder_agent
    if _knowledge_builder_agent is None:
        _knowledge_builder_agent = KnowledgeBuilderAgent(
            api_key=cfg.groq_api_key,
            model=cfg.groq_cheap_model or cfg.groq_model,
            base_url=(cfg.groq_base_url or "").strip() or None,
            app_url=cfg.app_url,
            gemini_api_key=cfg.effective_gemini_api_key,
            gemini_model=cfg.gemini_model,
            gemini_pro_model=cfg.gemini_pro_model,
            gemini_timeout=cfg.gemini_timeout,
            gemini_max_retry=cfg.gemini_max_retry,
        )
    return _knowledge_builder_agent

# ─── APP ─────────────────────────────────────────────────────

app = FastAPI(
    title="BotNesia API",
    version="1.0.0",
    docs_url="/docs",
)

_cors_origins_raw = (cfg.cors_allowed_origins or "*").strip()
_cors_origins = ["*"] if _cors_origins_raw == "*" else [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve dashboard static (biar FE dan BE satu origin, minim masalah CORS/mixed-content)
BASE_DIR = Path(__file__).resolve().parent
_FRONTEND_DIR = BASE_DIR / "frontend"
_PUBLIC_DIR = _FRONTEND_DIR / "public"
_DASHBOARD_PATH = _FRONTEND_DIR / "index.html"
_PUBLIC_DEMO_PATH = _FRONTEND_DIR / "demo.html"
_LANDING_PATH = _FRONTEND_DIR / "landing.html"
_API_JS_PATH = BASE_DIR / "api.js"
_MULTIAGENT_INDEX_PATH = BASE_DIR / "MultiAgent_Index.html"
_MULTIAGENT_QUICK_PATH = BASE_DIR / "MultiAgent_Quick_Start.html"
_MULTIAGENT_FRAMEWORK_PATH = BASE_DIR / "MultiAgent_AI_Framework.html"
_MULTIAGENT_INTEGRATION_PATH = BASE_DIR / "MultiAgent_App_Integration.html"

@app.get("/", include_in_schema=False)
async def root():
    if _LANDING_PATH.exists():
        return FileResponse(
            _LANDING_PATH,
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )
    if _DASHBOARD_PATH.exists():
        return RedirectResponse(url="/dashboard")
    return {"status": "ok"}

@app.get("/casper", include_in_schema=False)
async def casper_agentic_page():
    """Redirect to the Casper Agentic Workflow dashboard tab (Buildathon 2026)."""
    return RedirectResponse(url="/dashboard#casper-agentic-workflow", status_code=302)

@app.get("/demo", include_in_schema=False)
async def public_demo_page():
    if not _PUBLIC_DEMO_PATH.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "demo.html tidak ditemukan")
    return FileResponse(
        _PUBLIC_DEMO_PATH,
        media_type="text/html",
        headers={"Cache-Control": "no-store"},
    )

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
        ".ico": "image/x-icon",
    }
    return FileResponse(
        requested,
        media_type=media_types.get(requested.suffix.lower(), "application/octet-stream"),
        headers={"Cache-Control": "no-store"},
    )

@app.get("/assets/{asset_path:path}", include_in_schema=False)
async def public_asset(asset_path: str):
    requested = (_PUBLIC_DIR / "assets" / asset_path).resolve()
    public_assets_root = (_PUBLIC_DIR / "assets").resolve()
    if public_assets_root not in requested.parents or not requested.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset publik tidak ditemukan")
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
        ".ico": "image/x-icon",
    }
    return FileResponse(
        requested,
        media_type=media_types.get(requested.suffix.lower(), "application/octet-stream"),
        headers={"Cache-Control": "public, max-age=86400"},
    )

OFFICIAL_LOGO_PATH = _PUBLIC_DIR / "assets" / "brand" / "botnesia-clean-logo.png"

@app.get("/favicon.ico", include_in_schema=False)
async def favicon_ico():
    if not OFFICIAL_LOGO_PATH.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "logo resmi BotNesia tidak ditemukan")
    return FileResponse(OFFICIAL_LOGO_PATH, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})

@app.get("/apple-touch-icon.png", include_in_schema=False)
async def apple_touch_icon():
    if not OFFICIAL_LOGO_PATH.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "logo resmi BotNesia tidak ditemukan")
    return FileResponse(OFFICIAL_LOGO_PATH, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})

@app.get("/botnesia-widget.js", include_in_schema=False)
async def botnesia_widget_js():
    widget_path = _FRONTEND_DIR / "botnesia-widget.js"
    if not widget_path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "BotNesia widget tidak ditemukan")
    return FileResponse(widget_path, media_type="application/javascript", headers={"Cache-Control": "public, max-age=300"})

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
    global _meta_refresh_task, _meta_refresh_stop

    if cfg.meta_app_id and not (cfg.meta_app_secret or "").strip():
        print("[WARN] META_APP_ID terisi tapi META_APP_SECRET kosong -- "
              "webhook /webhooks/meta akan menolak SEMUA request (fail-closed) "
              "sampai META_APP_SECRET diisi di .env")

    try:
        await _replicate_image_queue.start()
        logger.info("Replicate image queue aktif (workers=%s)", cfg.replicate_image_workers)
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

    try:
        from bn_platform.meta_oauth import meta_refresh_loop
        if _meta_refresh_task is None:
            _meta_refresh_stop = asyncio.Event()
            _meta_refresh_task = asyncio.create_task(meta_refresh_loop(_meta_refresh_stop, get_pool))
            print("[OK] Meta OAuth token refresh aktif")
    except Exception as e:
        print(f"[WARN] Meta OAuth refresh gagal start: {e}")

@app.on_event("shutdown")
async def shutdown():
    global _pool, _pool_loop, _gmail_poll_task, _gmail_poll_stop
    global _intelligence_learning_task, _intelligence_learning_stop
    global _meta_refresh_task, _meta_refresh_stop
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
        if _meta_refresh_stop is not None:
            _meta_refresh_stop.set()
        if _meta_refresh_task is not None:
            try:
                await asyncio.wait_for(_meta_refresh_task, timeout=3.0)
            except BaseException:
                _meta_refresh_task.cancel()
    finally:
        _meta_refresh_task = None
        _meta_refresh_stop = None
    try:
        from intelligence.db import close_pool as close_intelligence_pool
        await close_intelligence_pool()
    except BaseException:
        pass
    try:
        await _replicate_image_queue.shutdown()
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
        CREATE TABLE IF NOT EXISTS knowledge_sources (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            bot_id UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
            tenant_id UUID,
            agent_id UUID,
            category TEXT,
            url TEXT NOT NULL,
            title TEXT,
            agent_type TEXT,
            priority TEXT NOT NULL DEFAULT 'normal',
            language TEXT NOT NULL DEFAULT 'id',
            trusted BOOLEAN NOT NULL DEFAULT FALSE,
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','crawling','indexed','failed','skipped')),
            error_message TEXT,
            retry_count INT NOT NULL DEFAULT 0,
            document_id UUID REFERENCES documents(id) ON DELETE SET NULL,
            last_crawled_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (bot_id, url)
        );
        """,
        "ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS tenant_id UUID;",
        "ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS agent_id UUID;",
        "ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS agent_type TEXT;",
        "ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS priority TEXT NOT NULL DEFAULT 'normal';",
        "ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS language TEXT NOT NULL DEFAULT 'id';",
        "ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS trusted BOOLEAN NOT NULL DEFAULT FALSE;",
        "ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS retry_count INT NOT NULL DEFAULT 0;",
        "ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS document_id UUID REFERENCES documents(id) ON DELETE SET NULL;",
        "CREATE INDEX IF NOT EXISTS idx_knowledge_sources_org_bot_status ON knowledge_sources(org_id, bot_id, status);",
        "CREATE INDEX IF NOT EXISTS idx_knowledge_sources_category ON knowledge_sources(org_id, category);",
        """
        CREATE TABLE IF NOT EXISTS knowledge_chunks (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            bot_id UUID REFERENCES bots(id) ON DELETE CASCADE,
            tenant_id UUID,
            agent_id UUID,
            source_id UUID REFERENCES knowledge_sources(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            embedding JSONB,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_source ON knowledge_chunks(source_id);",
        "CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_org_bot ON knowledge_chunks(org_id, bot_id);",
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
        CREATE TABLE IF NOT EXISTS meta_asset_routes (
            channel_type TEXT NOT NULL,
            external_id TEXT NOT NULL,
            org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            bot_id UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
            connection_id UUID,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (channel_type, external_id)
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
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS assigned_agent_id UUID REFERENCES users(id) ON DELETE SET NULL;",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ;",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS language TEXT NOT NULL DEFAULT 'id';",
        """
        CREATE TABLE IF NOT EXISTS human_queue (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE UNIQUE,
            reason TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'medium',
            status TEXT NOT NULL DEFAULT 'waiting',
            assigned_agent_id UUID REFERENCES users(id) ON DELETE SET NULL,
            assigned_at TIMESTAMPTZ, resolved_at TIMESTAMPTZ,
            resolution_note TEXT, sla_due_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_handoff_org ON human_queue(org_id, status);",
        "CREATE INDEX IF NOT EXISTS idx_handoff_assignee ON human_queue(assigned_agent_id) WHERE status = 'assigned';",
        """CREATE OR REPLACE VIEW handoffs AS
            SELECT id, org_id AS tenant_id, conversation_id, reason,
                   CASE WHEN status::text='waiting' THEN 'pending' ELSE status::text END AS status,
                   assigned_agent_id AS assigned_to, created_at
            FROM human_queue;""",
        """
        CREATE TABLE IF NOT EXISTS marketplace_templates (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            key TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            preview_image TEXT,
            system_prompt TEXT NOT NULL,
            greeting TEXT NOT NULL,
            primary_color TEXT NOT NULL DEFAULT '#0066FF',
            sample_faqs JSONB NOT NULL DEFAULT '[]'::jsonb,
            install_count INT NOT NULL DEFAULT 0,
            version TEXT NOT NULL DEFAULT '1.0.0',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        """CREATE TABLE IF NOT EXISTS tenant_template_installs (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            template_id UUID NOT NULL REFERENCES marketplace_templates(id),
            bot_id UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
            installed_by UUID REFERENCES users(id) ON DELETE SET NULL,
            installed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_installs_org ON tenant_template_installs(org_id);",
        "ALTER TABLE marketplace_templates ADD COLUMN IF NOT EXISTS icon TEXT NOT NULL DEFAULT 'agents';",
        "ALTER TABLE marketplace_templates ADD COLUMN IF NOT EXISTS tools JSONB NOT NULL DEFAULT '[]'::jsonb;",
        "ALTER TABLE marketplace_templates ADD COLUMN IF NOT EXISTS knowledge_sources JSONB NOT NULL DEFAULT '[]'::jsonb;",
        "ALTER TABLE marketplace_templates ADD COLUMN IF NOT EXISTS starter_questions JSONB NOT NULL DEFAULT '[]'::jsonb;",
        "ALTER TABLE marketplace_templates ADD COLUMN IF NOT EXISTS visibility JSONB NOT NULL DEFAULT '{\"public\":true,\"featured\":false,\"recommended\":true}'::jsonb;",
        "ALTER TABLE marketplace_templates ADD COLUMN IF NOT EXISTS rating NUMERIC(3,2) NOT NULL DEFAULT 4.80;",
        "ALTER TABLE marketplace_templates ADD COLUMN IF NOT EXISTS popularity_score INT NOT NULL DEFAULT 0;",
        "ALTER TABLE marketplace_templates ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();",
        """CREATE TABLE IF NOT EXISTS agent_categories (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '', icon TEXT NOT NULL DEFAULT 'agents',
            color TEXT NOT NULL DEFAULT '#2563EB', sort_order INT NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );""",
        """CREATE TABLE IF NOT EXISTS agents (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), template_id UUID REFERENCES marketplace_templates(id) ON DELETE SET NULL,
            agent_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', category TEXT NOT NULL,
            icon TEXT NOT NULL DEFAULT 'agents', color TEXT NOT NULL DEFAULT '#2563EB', visibility JSONB NOT NULL DEFAULT '{\"public\":true}'::jsonb,
            is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );""",
        """CREATE TABLE IF NOT EXISTS agent_versions (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            version TEXT NOT NULL, prompt TEXT NOT NULL, tools JSONB NOT NULL DEFAULT '[]'::jsonb,
            starter_questions JSONB NOT NULL DEFAULT '[]'::jsonb, changelog TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(agent_id, version)
        );""",
        """CREATE TABLE IF NOT EXISTS agent_installs (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            agent_id UUID REFERENCES agents(id) ON DELETE SET NULL, template_id UUID REFERENCES marketplace_templates(id) ON DELETE SET NULL,
            bot_id UUID REFERENCES bots(id) ON DELETE CASCADE, installed_by UUID REFERENCES users(id) ON DELETE SET NULL,
            status TEXT NOT NULL DEFAULT 'active', installed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );""",
        """CREATE TABLE IF NOT EXISTS agent_ratings (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            agent_id UUID REFERENCES agents(id) ON DELETE CASCADE, template_id UUID REFERENCES marketplace_templates(id) ON DELETE CASCADE,
            rating INT NOT NULL CHECK (rating BETWEEN 1 AND 5), review TEXT, created_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(org_id, template_id)
        );""",
        """CREATE TABLE IF NOT EXISTS agent_knowledge_sources (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), agent_id UUID REFERENCES agents(id) ON DELETE CASCADE,
            template_id UUID REFERENCES marketplace_templates(id) ON DELETE CASCADE, source_type TEXT NOT NULL DEFAULT 'url', url TEXT,
            category TEXT, priority TEXT NOT NULL DEFAULT 'normal', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );""",
        "CREATE INDEX IF NOT EXISTS idx_marketplace_templates_category ON marketplace_templates(category);",
        "CREATE INDEX IF NOT EXISTS idx_marketplace_templates_featured ON marketplace_templates(((visibility->>'featured')));",
        "CREATE INDEX IF NOT EXISTS idx_agent_installs_org ON agent_installs(org_id, status);",
        "CREATE INDEX IF NOT EXISTS idx_agent_ratings_template ON agent_ratings(template_id);",
        "DROP VIEW IF EXISTS agent_templates;",
        """CREATE VIEW agent_templates AS
            SELECT id, key AS agent_id, key, name, description, category, version, icon, primary_color AS color,
                   tools, knowledge_sources, starter_questions, visibility, rating, popularity_score, install_count,
                   CASE WHEN is_active THEN 'active' ELSE 'inactive' END AS status
              FROM marketplace_templates;""",
        """INSERT INTO marketplace_templates (key, category, name, description, system_prompt, greeting, primary_color, sample_faqs, version)
           VALUES
            ('customer-service', 'Customer Service', 'Customer Service Agent',
             'Agent layanan pelanggan untuk menjawab pertanyaan umum, komplain, dan status permintaan.',
             'Kamu adalah customer service agent yang sopan, cepat, dan solutif. Jawab pertanyaan umum, bantu komplain, jelaskan status layanan, dan selalu arahkan ke langkah berikutnya yang jelas.',
             'Halo! Saya siap membantu pertanyaan atau kendala pelanggan Anda.', '#2563EB',
             '[{"question":"Bagaimana cara menghubungi support?","answer":"Anda bisa menghubungi support melalui chat ini dan menyertakan nomor pesanan atau detail akun agar kami bisa membantu lebih cepat."},
               {"question":"Berapa lama proses balasan?","answer":"Balasan awal biasanya kami kirim secepat mungkin, lalu kami lanjutkan sesuai kompleksitas kasusnya."},
               {"question":"Apa yang harus disiapkan saat komplain?","answer":"Sertakan nomor pesanan, kronologi singkat, dan foto atau tangkapan layar jika relevan."}]', '1.0.0'),
            ('sales', 'Sales & Marketing', 'Sales Agent',
             'Agent penjualan untuk menangkap prospek, menjelaskan manfaat produk, dan mendorong konversi.',
             'Kamu adalah sales agent yang persuasif namun tidak memaksa. Pahami kebutuhan prospek, cocokkan solusi, dan arahkan ke tindakan pembelian atau follow-up yang jelas.',
             'Halo! Saya bisa bantu cari solusi yang paling cocok untuk kebutuhan Anda.', '#7C3AED',
             '[{"question":"Apa keunggulan produk ini?","answer":"Keunggulan utamanya ada pada kemudahan penggunaan, dukungan tim, dan hasil yang cepat terlihat untuk bisnis."},
               {"question":"Apakah ada demo?","answer":"Ya, kami bisa jadwalkan demo singkat agar Anda bisa melihat alur kerja dan fiturnya secara langsung."},
               {"question":"Bagaimana proses pembeliannya?","answer":"Setelah kebutuhan Anda jelas, kami bantu pilih paket yang sesuai lalu lanjut ke pembayaran dan aktivasi."}]', '1.0.0'),
            ('faq', 'Customer Service', 'FAQ Agent',
             'Agent tanya jawab generik untuk basis pertanyaan yang paling sering muncul.',
             'Kamu adalah FAQ agent yang ringkas, akurat, dan to the point. Jawab hanya berdasarkan informasi yang tersedia, dan jika belum yakin, minta klarifikasi atau arahkan ke human handoff.',
             'Halo! Kirim pertanyaan Anda, saya bantu jawab sejelas mungkin.', '#0F766E',
             '[{"question":"Apa jam layanan?","answer":"Jam layanan mengikuti konfigurasi tenant. Jika belum ditentukan, silakan cek pengumuman resmi atau hubungi support."},
               {"question":"Di mana saya bisa membaca panduan?","answer":"Panduan biasanya tersedia di knowledge base atau pusat bantuan tenant."},
               {"question":"Bagaimana jika jawabannya belum ada?","answer":"Saya akan meneruskan ke tim terkait atau meminta manusia membantu jika konteksnya belum lengkap."}]', '1.0.0'),
            ('school', 'Education', 'School Agent',
             'Agent sekolah untuk pendaftaran siswa, informasi akademik, dan komunikasi orang tua.',
             'Kamu adalah admin sekolah yang ramah dan informatif. Jelaskan program, pendaftaran, biaya, jadwal akademik, dan bantu orang tua atau siswa mendapatkan informasi yang mereka butuhkan.',
             'Halo! Ada informasi sekolah yang bisa saya bantu?', '#D97706',
             '[{"question":"Bagaimana cara mendaftar?","answer":"Silakan siapkan data siswa, dokumen pendukung, dan jenjang yang dituju. Kami bantu proses pendaftarannya."},
               {"question":"Apakah ada info biaya?","answer":"Biaya tergantung jenjang dan program. Sebutkan kebutuhan Anda agar kami berikan rincian yang sesuai."},
               {"question":"Kapan jadwal kegiatan sekolah?","answer":"Jadwal kegiatan akan kami informasikan sesuai kalender akademik yang berlaku."}]', '1.0.0'),
            ('clinic', 'Healthcare', 'Clinic Agent',
             'Agent klinik untuk jadwal dokter, booking janji temu, dan pertanyaan layanan kesehatan non-darurat.',
             'Kamu adalah asisten klinik yang sopan dan empatik. Bantu pasien menjadwalkan janji temu, menjelaskan layanan, dan mengarahkan kasus serius ke penanganan medis yang sesuai.',
             'Halo! Saya bantu untuk jadwal dan layanan klinik.', '#10B981',
             '[{"question":"Bagaimana booking dokter?","answer":"Sebutkan poli atau dokter yang dituju serta tanggal yang diinginkan agar kami cek jadwalnya."},
               {"question":"Apakah menerima asuransi?","answer":"Ketersediaan asuransi tergantung kebijakan klinik. Silakan sebutkan provider yang Anda gunakan."},
               {"question":"Apa layanan yang tersedia?","answer":"Layanan yang tersedia mengikuti cabang atau unit klinik yang terdaftar."}]', '1.0.0'),
            ('travel', 'Travel', 'Travel Agent',
             'Agent travel untuk rekomendasi paket wisata, itinerary, dan proses booking.',
             'Kamu adalah konsultan perjalanan yang membantu pelanggan memilih paket wisata, menjelaskan itinerary, harga, dan ketersediaan tanggal secara antusias dan jelas.',
             'Halo traveler! Mau liburan ke mana?', '#0EA5E9',
             '[{"question":"Apa saja paket yang tersedia?","answer":"Kami punya paket domestik dan internasional. Sebutkan destinasi atau budget Anda agar kami rekomendasikan opsi terbaik."},
               {"question":"Apakah harga sudah termasuk tiket?","answer":"Tergantung paketnya. Ada opsi land-only dan ada juga paket all-in."},
               {"question":"Bagaimana cara booking?","answer":"Setelah memilih paket, kami bantu lanjut ke data peserta dan pembayaran DP untuk mengunci tanggal."}]', '1.0.0'),
            ('property', 'Real Estate', 'Property Agent',
             'Agent properti untuk listing, jadwal survei, dan simulasi pembelian atau sewa.',
             'Kamu adalah agen properti yang profesional dan persuasif. Bantu calon pembeli atau penyewa menemukan unit sesuai budget, lokasi, dan kebutuhan mereka.',
             'Halo! Sedang mencari rumah, apartemen, atau ruko?', '#F59E0B',
             '[{"question":"Apakah bisa KPR?","answer":"Bisa, kami bisa bantu simulasi KPR berdasarkan budget dan penghasilan Anda."},
               {"question":"Bagaimana jadwal survei?","answer":"Silakan beri tahu waktu luang dan lokasi yang diminati, kami bantu atur jadwal survei."},
               {"question":"Apakah harga bisa nego?","answer":"Untuk beberapa unit harga masih dapat dinegosiasikan sesuai persetujuan pemilik."}]', '1.0.0'),
            ('e-commerce', 'Ecommerce', 'E-commerce Agent',
             'Agent e-commerce untuk pertanyaan produk, stok, ongkir, dan status pesanan.',
             'Kamu adalah asisten e-commerce yang ramah, cepat, dan persuasif. Bantu pelanggan menemukan produk, menjelaskan ongkir, metode pembayaran, dan status pesanan.',
             'Halo! Cari produk apa hari ini?', '#FF6B35',
             '[{"question":"Berapa lama pengiriman?","answer":"Pengiriman reguler biasanya 2-4 hari kerja dan ekspres 1-2 hari kerja tergantung lokasi."},
               {"question":"Apakah bisa COD?","answer":"Bisa untuk wilayah yang didukung kurir kami."},
               {"question":"Bagaimana cara retur barang?","answer":"Hubungi kami maksimal 2x24 jam setelah barang diterima dengan foto produk dan nomor pesanan."}]', '1.0.0')
         ON CONFLICT (key) DO UPDATE SET
             category = EXCLUDED.category,
             name = EXCLUDED.name,
             description = EXCLUDED.description,
             system_prompt = EXCLUDED.system_prompt,
             greeting = EXCLUDED.greeting,
             primary_color = EXCLUDED.primary_color,
             sample_faqs = EXCLUDED.sample_faqs,
             version = EXCLUDED.version,
             is_active = TRUE;""",
        """
        CREATE TABLE IF NOT EXISTS ai_traces (
            id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            user_question TEXT NOT NULL, final_answer TEXT, status TEXT NOT NULL DEFAULT 'running',
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), ended_at TIMESTAMPTZ, duration_ms INT,
            prompt_tokens INT NOT NULL DEFAULT 0, completion_tokens INT NOT NULL DEFAULT 0,
            total_tokens INT NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_executions (
            id UUID PRIMARY KEY, trace_id UUID NOT NULL REFERENCES ai_traces(id) ON DELETE CASCADE,
            parent_execution_id UUID REFERENCES agent_executions(id) ON DELETE SET NULL,
            tenant_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            agent_name TEXT NOT NULL, sequence_no INT NOT NULL DEFAULT 0,
            execution_start TIMESTAMPTZ NOT NULL DEFAULT NOW(), execution_end TIMESTAMPTZ,
            duration_ms INT, status TEXT NOT NULL DEFAULT 'running', error_message TEXT,
            confidence_score NUMERIC(7,3), prompt_tokens INT NOT NULL DEFAULT 0,
            completion_tokens INT NOT NULL DEFAULT 0, total_tokens INT NOT NULL DEFAULT 0,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_ai_traces_tenant_created ON ai_traces(tenant_id, created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_ai_traces_conversation ON ai_traces(conversation_id, created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_agent_exec_trace_sequence ON agent_executions(trace_id, sequence_no);",
        "CREATE INDEX IF NOT EXISTS idx_agent_exec_tenant_created ON agent_executions(tenant_id, created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_agent_exec_agent_status ON agent_executions(agent_name, status, created_at DESC);",
        "ALTER TABLE ai_traces ADD COLUMN IF NOT EXISTS routed_model TEXT;",
        "ALTER TABLE ai_traces ADD COLUMN IF NOT EXISTS task_complexity TEXT;",
        "ALTER TABLE ai_traces ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'widget';",
        """
        CREATE TABLE IF NOT EXISTS cost_records (
            id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
            trace_id UUID REFERENCES ai_traces(id) ON DELETE SET NULL,
            execution_id UUID REFERENCES agent_executions(id) ON DELETE SET NULL,
            model_name TEXT NOT NULL, agent_name TEXT NOT NULL,
            prompt_tokens INT NOT NULL DEFAULT 0, completion_tokens INT NOT NULL DEFAULT 0,
            token_count INT NOT NULL DEFAULT 0, estimated_cost NUMERIC(18,8) NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT 'USD', channel TEXT NOT NULL DEFAULT 'widget',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS tenant_cost_budgets (
            tenant_id UUID PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
            monthly_budget_usd NUMERIC(18,2) NOT NULL DEFAULT 0,
            updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_cost_records_tenant_created ON cost_records(tenant_id, created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_cost_records_conversation ON cost_records(conversation_id, created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_cost_records_agent ON cost_records(tenant_id, agent_name, created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_cost_records_model ON cost_records(tenant_id, model_name, created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_cost_records_channel ON cost_records(tenant_id, channel, created_at DESC);",
        "ALTER TABLE bots ADD COLUMN IF NOT EXISTS reasoning_mode TEXT NOT NULL DEFAULT 'standard';",
        "ALTER TABLE bots ADD COLUMN IF NOT EXISTS handoff_confidence_threshold FLOAT;",
        "ALTER TABLE bots ADD COLUMN IF NOT EXISTS computer_agent_enabled BOOLEAN NOT NULL DEFAULT FALSE;",
        """
        CREATE TABLE IF NOT EXISTS feedback_records (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE UNIQUE,
            bot_id UUID REFERENCES bots(id) ON DELETE SET NULL,
            rating TEXT NOT NULL CHECK (rating IN ('helpful','not_helpful')),
            comment TEXT, question TEXT NOT NULL DEFAULT '', answer TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS feedback_learning_queue (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            bot_id UUID REFERENCES bots(id) ON DELETE SET NULL,
            conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE UNIQUE,
            feedback_id UUID REFERENCES feedback_records(id) ON DELETE SET NULL,
            question TEXT NOT NULL, answer TEXT NOT NULL DEFAULT '', failure_reason TEXT,
            action_type TEXT NOT NULL CHECK (action_type IN ('knowledge','prompt','workflow')),
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','in_progress','resolved','dismissed')),
            occurrence_count INT NOT NULL DEFAULT 1, resolution_note TEXT, resolved_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_feedback_tenant_created ON feedback_records(tenant_id, created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_feedback_rating ON feedback_records(tenant_id, rating, created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_feedback_queue_status ON feedback_learning_queue(tenant_id, status, updated_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_feedback_queue_action ON feedback_learning_queue(tenant_id, action_type, occurrence_count DESC);",
        # ── Auto Knowledge Builder ──────────────────────────────
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS summary TEXT;",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS categories JSONB NOT NULL DEFAULT '[]'::jsonb;",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]'::jsonb;",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS suggested_intents JSONB NOT NULL DEFAULT '[]'::jsonb;",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS kb_status TEXT NOT NULL DEFAULT 'pending';",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS kb_error TEXT;",
        """
        CREATE TABLE IF NOT EXISTS kb_generated_faqs (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            bot_id UUID REFERENCES bots(id) ON DELETE SET NULL,
            document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            category TEXT,
            source TEXT NOT NULL DEFAULT 'ai',
            status TEXT NOT NULL DEFAULT 'suggested' CHECK (status IN ('suggested','approved','rejected')),
            chunk_id UUID REFERENCES doc_chunks(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS kb_generated_sops (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            bot_id UUID REFERENCES bots(id) ON DELETE SET NULL,
            document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            steps JSONB NOT NULL DEFAULT '[]'::jsonb,
            category TEXT,
            status TEXT NOT NULL DEFAULT 'suggested' CHECK (status IN ('suggested','approved','rejected')),
            chunk_id UUID REFERENCES doc_chunks(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS kb_quality_reports (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            bot_id UUID REFERENCES bots(id) ON DELETE SET NULL,
            document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
            completeness_score INT NOT NULL DEFAULT 0,
            redundancy_score INT NOT NULL DEFAULT 0,
            coverage_score INT NOT NULL DEFAULT 0,
            overall_score INT NOT NULL DEFAULT 0,
            missing_topics JSONB NOT NULL DEFAULT '[]'::jsonb,
            duplicate_groups JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_kb_faqs_org ON kb_generated_faqs(org_id, bot_id, status);",
        "CREATE INDEX IF NOT EXISTS idx_kb_faqs_document ON kb_generated_faqs(document_id);",
        "CREATE INDEX IF NOT EXISTS idx_kb_sops_org ON kb_generated_sops(org_id, bot_id, status);",
        "CREATE INDEX IF NOT EXISTS idx_kb_sops_document ON kb_generated_sops(document_id);",
        "CREATE INDEX IF NOT EXISTS idx_kb_quality_org ON kb_quality_reports(org_id, bot_id, created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_kb_quality_document ON kb_quality_reports(document_id, created_at DESC);",
        # ── AI Workflow Builder ──────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS workflows (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            bot_id UUID REFERENCES bots(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','disabled')),
            trigger_type TEXT NOT NULL DEFAULT 'manual_trigger',
            nodes JSONB NOT NULL DEFAULT '[]'::jsonb,
            edges JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            published_at TIMESTAMPTZ
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS workflow_executions (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            bot_id UUID REFERENCES bots(id) ON DELETE SET NULL,
            trigger_type TEXT NOT NULL,
            trigger_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','success','failed')),
            error TEXT,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at TIMESTAMPTZ,
            duration_ms INT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS workflow_execution_steps (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            execution_id UUID NOT NULL REFERENCES workflow_executions(id) ON DELETE CASCADE,
            node_id TEXT NOT NULL,
            node_type TEXT NOT NULL,
            category TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','success','failed','skipped')),
            attempt INT NOT NULL DEFAULT 1,
            input JSONB NOT NULL DEFAULT '{}'::jsonb,
            output JSONB NOT NULL DEFAULT '{}'::jsonb,
            error TEXT,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at TIMESTAMPTZ,
            duration_ms INT
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_workflows_org ON workflows(org_id, bot_id, status);",
        "CREATE INDEX IF NOT EXISTS idx_workflows_trigger ON workflows(org_id, trigger_type, status);",
        "CREATE INDEX IF NOT EXISTS idx_workflow_executions_workflow ON workflow_executions(workflow_id, started_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_workflow_executions_org ON workflow_executions(org_id, started_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_workflow_execution_steps_execution ON workflow_execution_steps(execution_id, started_at);",
        """
        CREATE TABLE IF NOT EXISTS whatsapp_embedded_accounts (
            org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            bot_id UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
            waba_id TEXT,
            phone_number_id TEXT,
            business_id TEXT,
            access_token_enc TEXT NOT NULL DEFAULT '',
            token_expires_at TIMESTAMPTZ,
            connection_status TEXT NOT NULL DEFAULT 'disconnected',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (org_id, bot_id)
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_whatsapp_embedded_accounts_phone ON whatsapp_embedded_accounts(phone_number_id);",
        # ── Intent Router: routing columns per assistant message ──────────────
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS intent TEXT;",
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS selected_agent TEXT;",
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS routing_confidence FLOAT;",
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS handoff_status TEXT;",
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS allow_human_handoff BOOLEAN;",
        "CREATE INDEX IF NOT EXISTS idx_messages_intent ON messages(intent) WHERE intent IS NOT NULL;",
        # ── Memory Agent: long-term memory dipindah dari file JSON lokal
        # (data/memory.json) ke Postgres -- shared antar proses/worker,
        # tidak hilang/tidak sinkron lagi saat scale ke multi-instance.
        # org_id/bot_id/end_user_id sengaja TEXT tanpa FK (end_user_id bukan
        # baris di tabel users, dan beberapa context test/internal memakai
        # ID non-UUID) -- konsisten dengan longgarnya skema file lama.
        """
        CREATE TABLE IF NOT EXISTS user_memory_profiles (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            org_id TEXT NOT NULL,
            bot_id TEXT NOT NULL,
            end_user_id TEXT NOT NULL,
            facts JSONB NOT NULL DEFAULT '{}'::jsonb,
            total_convs INT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (org_id, bot_id, end_user_id)
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_user_memory_profiles_lookup ON user_memory_profiles(org_id, bot_id, end_user_id);",
        """
        CREATE TABLE IF NOT EXISTS conversation_memory_summaries (
            conversation_id TEXT PRIMARY KEY,
            summary TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
    ]
    async with pool.acquire() as conn:
        for sql in stmts:
            try:
                await conn.execute(sql)
            except Exception:
                # Jangan bikin server gagal start kalau optional schema gagal
                pass
        try:
            from bn_platform.agent_marketplace_catalog import seed_professional_marketplace
            await seed_professional_marketplace(conn)
        except Exception:
            logger.exception("Professional marketplace seed failed")


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

def create_token(user_id: str, org_id: str, session_id: str | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=cfg.jwt_expire_hours)
    payload = {"sub": user_id, "org": org_id, "exp": expire}
    if session_id:
        payload["sid"] = session_id
    return jwt.encode(payload, cfg.secret_key, algorithm=cfg.jwt_algorithm)

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

    # Token dengan klaim `sid` (sesi tercatat di tabel sessions) — tolak jika
    # sesi sudah di-revoke (logout / "revoke session" dari security dashboard)
    # atau sudah lewat expires_at. Token lama tanpa `sid` tidak punya sesi
    # tercatat dan tetap berlaku sampai JWT-nya sendiri expired.
    session_id = payload.get("sid")
    if session_id and _platform_touch_session:
        try:
            if not await _platform_touch_session(pool, session_id):
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesi sudah berakhir, silakan login kembali")
        except HTTPException:
            raise
        except Exception:
            pass

    row = await pool.fetchrow(
        "SELECT id, org_id, email, role FROM users WHERE id=$1 AND is_active=TRUE",
        user_id,
    )
    if not row:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User tidak ditemukan")
    user = dict(row)
    user["session_id"] = session_id
    return user


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
    computer_agent_enabled: bool | None = None

class ChatReq(BaseModel):
    message:    str = Field(max_length=2000)
    session_id: str | None = None   # UUID conv yang sedang berjalan
    user_meta:  dict | None = None  # dari ChatbotWidget.identify()


# ─── ROUTE: AUTH ──────────────────────────────────────────────

async def _start_session(pool, *, user_id: str, org_id: str, email: str,
                          request: Request, action: str = "login") -> str | None:
    """Catat sesi baru (tabel `sessions`, deteksi login mencurigakan) +
    audit log `action`. Return session_id (utk klaim `sid` JWT) atau None
    jika bn_platform.security belum termuat."""
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    session_id: str | None = None
    is_suspicious = False
    if _platform_create_session:
        try:
            expires_at = datetime.now(timezone.utc) + timedelta(hours=cfg.jwt_expire_hours)
            sess = await _platform_create_session(
                pool, user_id=user_id, org_id=org_id,
                ip_address=ip_address, user_agent=user_agent, expires_at=expires_at,
            )
            session_id = str(sess["id"])
            is_suspicious = bool(sess["is_suspicious"])
        except Exception:
            pass
    if _platform_write_audit:
        try:
            await _platform_write_audit(
                pool, org_id=org_id, actor_user_id=user_id, actor_email=email,
                action=action, resource_type="user", resource_id=user_id,
                ip_address=ip_address, user_agent=user_agent,
                metadata={"suspicious": is_suspicious},
            )
        except Exception:
            pass
    return session_id


@app.post("/auth/register", status_code=201)
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
        # Biasanya: schema belum dibuat / permission CREATE EXTENSION / tabel belum ada
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Register gagal: {e}",
        )

    session_id = await _start_session(pool, user_id=user_id, org_id=org_id, email=email, request=request)
    token = create_token(user_id, org_id, session_id)
    return {"token": token, "org_id": org_id, "trial_ends": trial_end.isoformat()}


@app.post("/auth/login")
async def login(body: LoginReq, request: Request, pool=Depends(get_pool)):
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    async def _log_failed(org_id: str | None, user_id: str | None, email: str, reason: str) -> None:
        if not _platform_write_audit:
            return
        try:
            await _platform_write_audit(
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
        session_id = await _start_session(
            pool, user_id=str(row["id"]), org_id=str(row["org_id"]), email=email, request=request,
        )
        return {"token": create_token(str(row["id"]), str(row["org_id"]), session_id)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login gagal: {e}",
        )


@app.post("/auth/logout")
async def logout(
    user: Annotated[dict, Depends(get_current_user)],
    pool=Depends(get_pool),
):
    session_id = user.get("session_id")
    if session_id and _platform_revoke_session:
        try:
            await _platform_revoke_session(pool, session_id=session_id, org_id=str(user["org_id"]), reason="logout")
        except Exception:
            pass
    if _platform_write_audit:
        try:
            await _platform_write_audit(
                pool, org_id=str(user["org_id"]), actor_user_id=str(user["id"]), actor_email=user.get("email"),
                action="logout", resource_type="user", resource_id=str(user["id"]), metadata={},
            )
        except Exception:
            pass
    return {"ok": True}


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
    if _platform_require_permission:
        await _platform_require_permission("billing.manage")(user=user, pool=pool)

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


# ─── ROUTE: WHATSAPP EMBEDDED SIGNUP ────────────────────────────
#
# "Connect WhatsApp" tanpa copy-paste token: Dashboard -> Connect WhatsApp
# -> Meta Embedded Signup (FB JS SDK popup, config dari GET /connect) ->
# frontend menerima `code` + waba_id + phone_number_id + business_id ->
# POST /callback -> backend menukar code, register nomor, subscribe webhook
# WABA, lalu simpan kredensial TERENKRIPSI per tenant (org_id + bot_id) di
# tabel whatsapp_embedded_accounts. Tidak ada token global — setiap baris
# terikat ke (org_id, bot_id) dan semua query di-scope dengan org_id dari
# get_current_user (tenant isolation).
#
# Referensi (cek dokumentasi resmi untuk parameter terbaru):
# https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/overview
# https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/implementation/

def _whatsapp_account_public(acc: dict) -> dict:
    """Bentuk aman untuk response — tidak pernah menyertakan access token mentah."""
    return {
        "tenant_id": acc["tenant_id"],
        "bot_id": acc["bot_id"],
        "waba_id": acc.get("waba_id"),
        "phone_number_id": acc.get("phone_number_id"),
        "business_id": acc.get("business_id"),
        "connection_status": acc.get("connection_status"),
        "token_expires_at": acc.get("token_expires_at"),
        "connected": acc.get("connection_status") == "connected",
        "has_access_token": bool(acc.get("customer_access_token")),
    }


@app.get("/integrations/whatsapp/connect")
async def whatsapp_embedded_connect(
    bot_id: str,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    """Mulai flow Meta WhatsApp Embedded Signup untuk satu agent (bot).

    Embedded Signup berbasis FB JS SDK (popup), bukan redirect — jadi
    endpoint ini mengembalikan konfigurasi yang dibutuhkan frontend untuk
    memanggil FB.init() + FB.login({config_id, response_type:'code',
    override_default_response_type:true, ...}), bukan `auth_url`.
    """
    if not cfg.meta_app_id or not cfg.meta_embedded_signup_config_id:
        raise HTTPException(400, "META_APP_ID / META_EMBEDDED_SIGNUP_CONFIG_ID belum diisi di .env")

    bot = await pool.fetchrow(
        "SELECT id FROM bots WHERE id=$1 AND org_id=$2",
        bot_id, user["org_id"],
    )
    if not bot:
        raise HTTPException(404, "Bot tidak ditemukan untuk org ini")

    state = secrets.token_urlsafe(24)
    # `redirect_uri` direuse untuk membawa bot_id ke /callback — Embedded
    # Signup adalah popup flow (tidak ada redirect URI sungguhan).
    await db_set_oauth_state(
        pool,
        provider="whatsapp_embedded",
        state=state,
        org_id=str(user["org_id"]),
        redirect_uri=str(bot_id),
    )

    return {
        "app_id": cfg.meta_app_id,
        "config_id": cfg.meta_embedded_signup_config_id,
        "graph_api_version": cfg.meta_api_version,
        "state": state,
        "bot_id": str(bot_id),
    }


class WhatsAppEmbeddedCallbackReq(BaseModel):
    state: str
    code: str
    waba_id: str
    phone_number_id: str
    business_id: str | None = None


@app.post("/integrations/whatsapp/callback")
async def whatsapp_embedded_callback(
    body: WhatsAppEmbeddedCallbackReq,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    """Selesaikan Embedded Signup: tukar code -> register nomor -> subscribe
    webhook WABA -> simpan kredensial terenkripsi per tenant (org_id+bot_id)."""
    org_id, bot_id = await db_pop_oauth_state(pool, provider="whatsapp_embedded", state=body.state)
    if not org_id or not bot_id:
        raise HTTPException(400, "State tidak valid/sudah expired")
    if org_id != str(user["org_id"]):
        raise HTTPException(403, "State ini bukan milik tenant Anda")

    bot = await pool.fetchrow("SELECT id FROM bots WHERE id=$1 AND org_id=$2", bot_id, org_id)
    if not bot:
        raise HTTPException(404, "Bot tidak ditemukan untuk org ini")

    if not cfg.meta_app_id or not cfg.meta_app_secret:
        raise HTTPException(400, "META_APP_ID / META_APP_SECRET belum diisi di .env")

    api_ver = cfg.meta_api_version

    token_res = await wa_exchange_code_for_token(
        app_id=cfg.meta_app_id, app_secret=cfg.meta_app_secret, code=body.code, api_version=api_ver,
    )
    if not token_res.get("success"):
        await db_set_whatsapp_account(
            pool, org_id=org_id, bot_id=bot_id,
            waba_id=body.waba_id, phone_number_id=body.phone_number_id, business_id=body.business_id or "",
            customer_access_token="", token_expires_at=None, connection_status="error",
            secret_key=cfg.secret_key,
        )
        raise HTTPException(400, f"Tukar code dengan Meta gagal: {token_res.get('error')}")

    token_data = token_res.get("data") or {}
    access_token = token_data.get("access_token", "")
    expires_in = token_data.get("expires_in")
    token_expires_at = None
    if expires_in:
        try:
            token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        except (TypeError, ValueError):
            token_expires_at = None

    reg_res = await wa_register_phone_number(
        phone_number_id=body.phone_number_id, access_token=access_token,
        pin=cfg.meta_register_pin, api_version=api_ver,
    )
    sub_res = await wa_subscribe_app_to_waba(
        waba_id=body.waba_id, access_token=access_token, api_version=api_ver,
    )

    if reg_res.get("success") and sub_res.get("success"):
        connection_status = "connected"
        error_detail = None
    else:
        connection_status = "error"
        error_detail = reg_res.get("error") or sub_res.get("error")

    # Simpan apa pun hasilnya — supaya /status bisa menunjukkan connection_status
    # ("connected" atau "error") tanpa kehilangan waba_id/phone_number_id yang
    # sudah dipilih user di popup Embedded Signup.
    await db_set_whatsapp_account(
        pool, org_id=org_id, bot_id=bot_id,
        waba_id=body.waba_id, phone_number_id=body.phone_number_id, business_id=body.business_id or "",
        customer_access_token=access_token, token_expires_at=token_expires_at,
        connection_status=connection_status, secret_key=cfg.secret_key,
    )

    if connection_status != "connected":
        raise HTTPException(400, f"WhatsApp terautentikasi tapi setup gagal: {error_detail}")

    # Routing inbound webhook -> org/bot yang benar.
    await db_set_meta_phone_mapping(
        pool, phone_number_id=body.phone_number_id, org_id=org_id, bot_id=bot_id,
    )

    return {
        "message": "WhatsApp berhasil terhubung",
        "tenant_id": org_id,
        "bot_id": bot_id,
        "waba_id": body.waba_id,
        "phone_number_id": body.phone_number_id,
        "business_id": body.business_id,
        "connection_status": connection_status,
        "token_expires_at": token_expires_at.isoformat() if token_expires_at else None,
    }


@app.get("/integrations/whatsapp/status")
async def whatsapp_embedded_status(
    bot_id: str | None = None,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    org_id = str(user["org_id"])
    if bot_id:
        bot = await pool.fetchrow("SELECT id FROM bots WHERE id=$1 AND org_id=$2", bot_id, org_id)
        if not bot:
            raise HTTPException(404, "Bot tidak ditemukan untuk org ini")
        acc = await db_get_whatsapp_account(pool, org_id=org_id, bot_id=bot_id, secret_key=cfg.secret_key)
        if not acc:
            return {
                "tenant_id": org_id, "bot_id": str(bot_id),
                "connected": False, "connection_status": "disconnected",
            }
        return _whatsapp_account_public(acc)

    accounts = await db_get_whatsapp_accounts(pool, org_id=org_id, secret_key=cfg.secret_key)
    return {"accounts": [_whatsapp_account_public(a) for a in accounts]}


class WhatsAppEmbeddedDisconnectReq(BaseModel):
    bot_id: str


@app.post("/integrations/whatsapp/disconnect")
async def whatsapp_embedded_disconnect(
    body: WhatsAppEmbeddedDisconnectReq,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    org_id = str(user["org_id"])
    bot = await pool.fetchrow("SELECT id FROM bots WHERE id=$1 AND org_id=$2", body.bot_id, org_id)
    if not bot:
        raise HTTPException(404, "Bot tidak ditemukan untuk org ini")

    acc = await db_get_whatsapp_account(pool, org_id=org_id, bot_id=body.bot_id, secret_key=cfg.secret_key)
    if not acc:
        raise HTTPException(404, "WhatsApp belum terhubung untuk bot ini")

    # Best-effort: lepas subscription webhook WABA di sisi Meta.
    if acc.get("customer_access_token") and acc.get("waba_id"):
        try:
            await wa_unsubscribe_app_from_waba(
                waba_id=acc["waba_id"], access_token=acc["customer_access_token"],
                api_version=cfg.meta_api_version,
            )
        except Exception:
            pass

    if acc.get("phone_number_id"):
        try:
            await db_clear_meta_phone_mapping(pool, phone_number_id=acc["phone_number_id"])
        except Exception:
            pass

    await db_clear_whatsapp_account(pool, org_id=org_id, bot_id=body.bot_id)
    return {
        "message": "WhatsApp diputuskan",
        "tenant_id": org_id, "bot_id": body.bot_id,
        "connection_status": "disconnected",
    }


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


async def _moderate_prompt(text: str) -> bool:
    """True kalau prompt aman digenerate. Fail-open kalau Groq tidak bisa dihubungi —
    moderasi ini lapisan tambahan, bukan satu-satunya filter (provider gambar punya
    safety filter sendiri juga), jadi tidak menjatuhkan fitur saat Groq sedang flaky."""
    if not cfg.image_moderation_enabled or not cfg.groq_api_key:
        return True
    try:
        headers = {"Authorization": f"Bearer {cfg.groq_api_key}", "Content-Type": "application/json"}
        payload = {
            "model": "llama-guard-3-8b",
            "messages": [{"role": "user", "content": text}],
            "temperature": 0,
            "max_tokens": 20,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{cfg.groq_base_url.rstrip('/')}/chat/completions", json=payload, headers=headers,
            )
        if resp.status_code != 200:
            return True
        choices = (resp.json() or {}).get("choices") or []
        if not choices:
            return True
        content = str((choices[0].get("message") or {}).get("content") or "").strip().lower()
        return not content.startswith("unsafe")
    except Exception as exc:
        logger.debug("Image moderation check gagal, fail-open: %s", exc)
        return True


def _image_provider_kwargs() -> dict:
    return {
        "openai_api_key": cfg.openai_api_key,
        "google_api_key": cfg.effective_gemini_api_key,
        "stability_api_key": cfg.stability_api_key,
        "fal_api_key": cfg.fal_api_key,
        "replicate_tokens": _get_replicate_tokens(),
        "replicate_version": cfg.replicate_image_version,
        "replicate_model": cfg.replicate_image_model,
        "replicate_input_overrides": _parse_json_dict(cfg.replicate_image_input_json),
    }


async def _run_image_generation(
    *,
    org_id: str,
    pool,
    prompt: str,
    user_id: str | None = None,
    provider_name: str = "",
    size: str = "1024x1024",
    style: str = "",
    quality: str = "medium",
    bot_id: str | None = None,
    conversation_id: str | None = None,
) -> dict:
    """Logika inti generate image, dipakai bersama oleh /media/image (legacy),
    /api/images/generate, dan integrasi Chat + Image.

    Jika caller TIDAK meminta provider spesifik (provider_name kosong), coba
    berurutan sesuai `cfg.image_provider_fallback_order` (default Google Imagen
    -> Replicate) dan pakai provider pertama yang tersedia & berhasil. Jika
    caller secara eksplisit meminta provider tertentu, perilaku persis seperti
    sebelumnya: hanya provider itu yang dicoba, tidak ada override diam-diam."""
    org_id = str(org_id)
    explicit_provider = bool((provider_name or "").strip())

    if _platform_check_limit:
        ok, detail = await _platform_check_limit(pool, org_id, "image_generations")
        if not ok:
            raise HTTPException(
                402,
                f"Kuota generate gambar paket '{detail['plan']}' tercapai "
                f"({detail['used']}/{detail['limit']}). Upgrade paket untuk lanjut generate gambar.",
            )

    if not await _moderate_prompt(prompt):
        raise HTTPException(422, "Permintaan gambar ini tidak bisa diproses karena melanggar kebijakan konten.")

    async def _attempt(name: str):
        candidate = image_providers.get_provider(name, **_image_provider_kwargs())
        if not candidate.available:
            raise image_providers.ImageProviderError(f"Provider gambar '{name}' belum dikonfigurasi (API key kosong).")
        attempt_started = time.monotonic()
        if candidate.name == "replicate":
            res = await _replicate_image_queue.submit(
                lambda: candidate.generate(prompt, size=size, style=style, quality=quality)
            )
        else:
            res = await candidate.generate(prompt, size=size, style=style, quality=quality)
        return res, round(time.monotonic() - attempt_started, 2)

    if explicit_provider:
        name = provider_name.strip().lower()
        try:
            result, generation_time = await _attempt(name)
        except image_providers.ImageProviderError as exc:
            raise HTTPException(400 if "belum dikonfigurasi" in str(exc) else 502, str(exc))
        except Exception as exc:
            raise _friendly_replicate_error(exc, "gambar")
    else:
        fallback_order = [p.strip().lower() for p in (cfg.image_provider_fallback_order or "").split(",") if p.strip()]
        candidates = fallback_order or [(cfg.image_provider or "replicate").strip().lower()]
        result = None
        generation_time = 0.0
        last_exc: Exception | None = None
        for name in candidates:
            try:
                result, generation_time = await _attempt(name)
                break
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Provider gambar '%s' gagal/tidak tersedia, mencoba provider berikutnya: %s", name, exc,
                )
        if result is None:
            if isinstance(last_exc, image_providers.ImageProviderError):
                raise HTTPException(502, f"Semua provider gambar gagal: {last_exc}")
            raise _friendly_replicate_error(last_exc, "gambar") if last_exc else HTTPException(502, "Gagal generate gambar")

    ext = ".webp" if result.content_type == "image/webp" else ".png"
    _, url = storage_backend.save_bytes("generated", result.data, ext=ext)
    cost = image_providers.estimate_image_cost_usd(result.provider)

    try:
        await pool.execute(
            """INSERT INTO image_generations
                   (org_id, bot_id, conversation_id, user_id, kind, provider, model,
                    prompt, revised_prompt, image_url, size, style, status, estimated_cost)
               VALUES ($1,$2,$3,$4,'generate',$5,$6,$7,$8,$9,$10,$11,'completed',$12)""",
            org_id, bot_id, conversation_id, user_id, result.provider, result.model,
            prompt, result.revised_prompt, url, size, style, cost,
        )
    except Exception:
        logger.warning("Gagal mencatat image_generations", exc_info=True)
    try:
        await pool.execute(
            """INSERT INTO cost_records (id, tenant_id, conversation_id, model_name, agent_name, estimated_cost, channel)
               VALUES ($1,$2,$3,$4,'image_generator',$5,'images_api')""",
            str(uuid.uuid4()), org_id, conversation_id, f"{result.provider}:{result.model}", cost,
        )
    except Exception:
        logger.warning("Gagal mencatat cost_records image", exc_info=True)

    return {
        "image_url": url,
        "provider": result.provider,
        "model": result.model,
        "generation_time": generation_time,
        "revised_prompt": result.revised_prompt,
    }


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
    from tts_engine import normalize_tts_text

    text = normalize_tts_text(body.text)
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
            rate="+7%",
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
                "X-TTS-Rate": "+7%",
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
    pool=Depends(get_pool),
):
    """Legacy endpoint (dipertahankan untuk kompatibilitas). Selalu pakai provider Replicate,
    sama seperti sebelumnya — logika baru ada di `/api/images/generate` (multi-provider)."""
    retry_after = _check_media_cooldown(str(user["id"]), "image")
    if retry_after > 0:
        raise HTTPException(
            429,
            f"Tunggu {retry_after} detik sebelum generate gambar lagi.",
            headers={"Retry-After": str(retry_after)},
        )
    result = await _run_image_generation(
        org_id=user["org_id"], user_id=str(user["id"]), pool=pool, prompt=body.prompt,
        provider_name="replicate", size=body.size, quality=body.quality,
    )
    return {"type": "image", "url": result["image_url"]}


class ImageGenerateReq(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)
    style: str = ""
    size: str = "1024x1024"
    quality: str = "medium"
    provider: str = ""  # kosong = pakai IMAGE_PROVIDER default dari .env
    bot_id: str | None = None
    conversation_id: str | None = None


@app.post("/api/images/generate")
async def api_generate_image(
    body: ImageGenerateReq,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    retry_after = _check_media_cooldown(str(user["id"]), "image")
    if retry_after > 0:
        raise HTTPException(
            429,
            f"Tunggu {retry_after} detik sebelum generate gambar lagi.",
            headers={"Retry-After": str(retry_after)},
        )
    result = await _run_image_generation(
        org_id=user["org_id"], user_id=str(user["id"]), pool=pool, prompt=body.prompt,
        provider_name=body.provider, size=body.size, style=body.style, quality=body.quality,
        bot_id=body.bot_id, conversation_id=body.conversation_id,
    )
    return {
        "image_url": result["image_url"],
        "provider": result["provider"],
        "generation_time": result["generation_time"],
    }


@app.get("/api/images/history")
async def api_image_history(
    user=Depends(get_current_user),
    pool=Depends(get_pool),
    bot_id: str | None = None,
    limit: int = 30,
    offset: int = 0,
):
    limit = max(1, min(int(limit or 30), 100))
    offset = max(0, int(offset or 0))
    if bot_id:
        rows = await pool.fetch(
            """SELECT id, bot_id, conversation_id, kind, provider, model, prompt, image_url,
                      size, style, status, estimated_cost, created_at
               FROM image_generations WHERE org_id=$1 AND bot_id=$2
               ORDER BY created_at DESC LIMIT $3 OFFSET $4""",
            user["org_id"], bot_id, limit, offset,
        )
    else:
        rows = await pool.fetch(
            """SELECT id, bot_id, conversation_id, kind, provider, model, prompt, image_url,
                      size, style, status, estimated_cost, created_at
               FROM image_generations WHERE org_id=$1
               ORDER BY created_at DESC LIMIT $2 OFFSET $3""",
            user["org_id"], limit, offset,
        )
    return {"items": [dict(r) for r in rows]}


_IMAGE_ANALYZE_ALLOWED_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}
_IMAGE_ANALYZE_MAX_BYTES = 10 * 1024 * 1024


@app.post("/api/images/analyze")
async def api_analyze_image(
    file: UploadFile = File(...),
    question: str = "",
    mode: str = "describe",
    bot_id: str | None = None,
    conversation_id: str | None = None,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    retry_after = _check_media_cooldown(str(user["id"]), "image_analyze")
    if retry_after > 0:
        raise HTTPException(
            429,
            f"Tunggu {retry_after} detik sebelum analisis gambar lagi.",
            headers={"Retry-After": str(retry_after)},
        )

    content_type = (file.content_type or "").lower().split(";", 1)[0].strip()
    if content_type and content_type not in _IMAGE_ANALYZE_ALLOWED_TYPES:
        raise HTTPException(415, f"Format gambar tidak didukung: {content_type}")

    data = await file.read(_IMAGE_ANALYZE_MAX_BYTES + 1)
    if not data:
        raise HTTPException(400, "Gambar kosong.")
    if len(data) > _IMAGE_ANALYZE_MAX_BYTES:
        raise HTTPException(413, "Gambar maksimal 10 MB.")

    mode = (mode or "describe").strip().lower()
    if mode not in vision_engine.MODE_PROMPTS:
        mode = "describe"

    try:
        answer = await vision_engine.analyze_image(
            data, content_type or "image/png",
            api_key=cfg.groq_api_key, model=cfg.groq_model,
            question=question, mode=mode,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"Vision AI gagal: HTTP {exc.response.status_code}") from exc
    except Exception as exc:
        raise HTTPException(502, f"Vision AI gagal: {exc}") from exc

    try:
        await pool.execute(
            """INSERT INTO image_generations
                   (org_id, bot_id, conversation_id, user_id, kind, provider, model,
                    prompt, image_url, status)
               VALUES ($1,$2,$3,$4,'analyze','vision',$5,$6,NULL,'completed')""",
            str(user["org_id"]), bot_id, conversation_id, str(user["id"]), cfg.groq_model,
            (question or mode),
        )
    except Exception:
        logger.warning("Gagal mencatat image_generations (analyze)", exc_info=True)

    return {"answer": answer, "mode": mode, "model": cfg.groq_model}


class DocumentGenerateReq(BaseModel):
    format: str = Field(pattern="^(pdf|docx|xlsx|pptx)$")
    prompt: str = Field(min_length=3, max_length=2000)
    bot_id: str | None = None


@app.post("/api/documents/generate")
async def api_generate_document(
    body: DocumentGenerateReq,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    retry_after = _check_media_cooldown(str(user["id"]), "document")
    if retry_after > 0:
        raise HTTPException(
            429,
            f"Tunggu {retry_after} detik sebelum generate dokumen lagi.",
            headers={"Retry-After": str(retry_after)},
        )
    if not cfg.groq_api_key:
        raise HTTPException(503, "GROQ_API_KEY belum dikonfigurasi.")

    outline_prompt = (
        "Ubah permintaan berikut menjadi outline dokumen dalam format JSON dengan struktur:\n"
        '{"title": str, "sections": [{"heading": str, "body": str}], '
        '"table_rows": [[str, ...]], "slides": [{"title": str, "bullets": [str]}]}\n'
        "Isi table_rows hanya jika permintaan berbentuk data tabular (laporan, daftar angka). "
        "Isi slides hanya jika formatnya presentasi. Jawab dalam Bahasa Indonesia, dan jawab dalam format JSON.\n\n"
        f"Permintaan user: {body.prompt}"
    )
    headers = {"Authorization": f"Bearer {cfg.groq_api_key}", "Content-Type": "application/json"}
    payload = {
        "model": cfg.groq_model,
        "messages": [{"role": "user", "content": outline_prompt}],
        "temperature": 0.3,
        "max_tokens": 2048,
        "response_format": {"type": "json_object"},
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{cfg.groq_base_url.rstrip('/')}/chat/completions", json=payload, headers=headers,
            )
        resp.raise_for_status()
        choices = (resp.json() or {}).get("choices") or []
        raw = str((choices[0].get("message") or {}).get("content") or "") if choices else ""
        from base import parse_json_response
        spec = parse_json_response(raw, default={})
    except Exception as exc:
        logger.warning("Gagal membuat outline dokumen: %s", exc)
        spec = {}

    spec = document_generator.normalize_spec(spec, fallback_title=body.prompt[:80])
    try:
        file_bytes, _content_type = document_generator.generate_document(body.format, spec)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    _, url = storage_backend.save_bytes("documents", file_bytes, ext=f".{body.format}")
    try:
        await pool.execute(
            """INSERT INTO generated_documents (org_id, bot_id, user_id, format, title, prompt, file_url, status)
               VALUES ($1,$2,$3,$4,$5,$6,$7,'completed')""",
            str(user["org_id"]), body.bot_id, str(user["id"]), body.format, spec["title"], body.prompt, url,
        )
    except Exception:
        logger.warning("Gagal mencatat generated_documents", exc_info=True)

    return {"file_url": url, "format": body.format, "title": spec["title"]}


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

    # X-Hub-Signature-256 (HMAC-SHA256) WAJIB diverifikasi -- sebelumnya cek
    # ini di-skip total kalau META_APP_SECRET kosong (fail-open: siapa pun
    # bisa POST payload palsu dan memicu auto-reply WhatsApp/FB/IG atas nama
    # tenant manapun yang ke-resolve dari payload). Tanpa secret terkonfigurasi,
    # tolak semua request -- operator harus isi META_APP_SECRET dulu sebelum
    # channel Meta benar-benar live, bukan diam-diam menerima tanpa autentikasi.
    app_secret = (cfg.meta_app_secret or "").strip()
    if not app_secret:
        logger.error("META_APP_SECRET belum dikonfigurasi -- webhook Meta ditolak (fail-closed).")
        raise HTTPException(503, "Meta webhook belum dikonfigurasi di server ini")
    sig = (request.headers.get("X-Hub-Signature-256") or "").strip()
    expected = "sha256=" + hmac.new(app_secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    if not (sig and hmac.compare_digest(sig, expected)):
        raise HTTPException(403, "Invalid signature")

    try:
        payload = json.loads(body_bytes.decode("utf-8") or "{}")
    except Exception:
        payload = {}
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
        await _handle_meta_social_inbound(payload)
    except Exception:
        # jangan bikin webhook gagal
        logger.exception("Meta webhook processing failed")

    return {"status": "ok"}


async def _handle_meta_social_inbound(payload: dict) -> None:
    object_type = str(payload.get("object") or "").lower()
    channel_type = "instagram" if object_type == "instagram" else "facebook" if object_type == "page" else None
    if not channel_type or not _platform_route_inbound:
        return
    pool = await get_pool_safe()
    if not pool:
        return
    from bn_platform.channel_manager import ChannelManager
    for entry in payload.get("entry") or []:
        external_id = str((entry or {}).get("id") or "")
        if not external_id:
            continue
        row = await pool.fetchrow(
            """SELECT cc.id FROM meta_asset_routes mar
               JOIN channel_connections cc ON cc.id=mar.connection_id
               WHERE mar.external_id=$1 AND mar.channel_type=$2
               AND cc.status='connected'""",
            external_id, channel_type,
        )
        if not row:
            continue
        manager = ChannelManager(
            pool, route_inbound_message=_platform_route_inbound,
            app_url=cfg.app_url, webhook_secret="",
        )
        await manager.receive_message(
            connection_id=str(row["id"]),
            payload={"object": object_type, "entry": [entry]},
        )


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

    # Sumber utama: kredensial per-tenant terenkripsi dari Embedded Signup.
    if bot_id and org_id and not wa_token:
        try:
            acc = await db_get_whatsapp_account(
                pool, org_id=str(org_id), bot_id=str(bot_id), secret_key=cfg.secret_key,
            )
            if acc and acc.get("connection_status") == "connected":
                wa_token = (acc.get("customer_access_token") or "").strip()
        except Exception:
            wa_token = ""

    # Fallback lama: konfigurasi integrations manual (meta.wa_token).
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
    if _platform_require_permission:
        await _platform_require_permission("bots.write")(user=user, pool=pool)

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
    if _platform_require_permission:
        await _platform_require_permission("bots.write")(user=user, pool=pool)

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

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024  # 20MB — cukup untuk dokumen knowledge base wajar
_ALLOWED_DOCUMENT_EXTENSIONS = (".pdf", ".docx", ".csv", ".md", ".markdown", ".txt")


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

    filename_l = (file.filename or "").lower()
    if not filename_l.endswith(_ALLOWED_DOCUMENT_EXTENSIONS):
        raise HTTPException(
            400,
            f"Tipe file tidak didukung. Format yang didukung: {', '.join(_ALLOWED_DOCUMENT_EXTENSIONS)}.",
        )

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
    if len(contents) > MAX_DOCUMENT_BYTES:
        raise HTTPException(
            413,
            f"Ukuran file melebihi batas {MAX_DOCUMENT_BYTES // (1024*1024)}MB.",
        )
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

    if _platform_write_audit:
        try:
            await _platform_write_audit(
                pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
                action="create", resource_type="document", resource_id=doc_id,
                metadata={"bot_id": bot_id, "filename": file.filename, "status": row["status"]},
            )
        except Exception:
            pass

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

        doc_meta = await pool.fetchrow("SELECT org_id, filename FROM documents WHERE id=$1", doc_id)
        if not doc_meta:
            raise ValueError("Dokumen tidak ditemukan.")
        filename_l = (doc_meta["filename"] or "").lower()

        if source_type == "url":
            text = await _fetch_website_text(source_url or "")
        else:
            raw = contents or b""
            if "pdf" in mime_l or filename_l.endswith(".pdf"):
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
            elif ("word" in mime_l) or ("docx" in mime_l) or filename_l.endswith(".docx"):
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
            elif "csv" in mime_l or filename_l.endswith(".csv"):
                try:
                    text = _csv_to_text(raw.decode("utf-8-sig", errors="ignore"))
                except Exception as e:
                    raise ValueError(f"Gagal membaca CSV: {e}")
            elif "markdown" in mime_l or filename_l.endswith((".md", ".markdown")):
                text = _clean_markdown_text(raw.decode("utf-8", errors="ignore"))
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

        org_id = str(doc_meta["org_id"])

        async with pool.acquire() as conn:
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
                       source_type=$2, source_url=$3, kb_status='pending', kb_error=NULL
                   WHERE id=$4""",
                len(chunks), source_type, source_url, doc_id,
            )

        # Auto Knowledge Builder: generate summary/categories/FAQ/SOP/quality
        # secara asinkron, tidak menghambat response upload (fire-and-forget).
        asyncio.create_task(_run_knowledge_builder_pipeline(doc_id))
    except Exception as e:
        await pool.execute(
            "UPDATE documents SET status='failed', error_msg=$1 WHERE id=$2",
            str(e), doc_id,
        )


def _csv_to_text(raw_text: str, max_rows: int = 500) -> str:
    """Ubah isi CSV jadi teks naratif untuk chunking/embedding.

    Jika kolom pertanyaan/jawaban (question/pertanyaan, answer/jawaban) terdeteksi,
    setiap baris diformat sebagai pasangan Q&A agar mudah diekstrak jadi FAQ.
    Jika tidak, setiap baris diformat sebagai daftar "kolom: nilai".
    """
    reader = csv.reader(io.StringIO(raw_text))
    rows = [r for r in reader if any((c or "").strip() for c in r)]
    if not rows:
        return ""

    header = [(c or "").strip().lower() for c in rows[0]]
    data_rows = rows[1:max_rows + 1]

    q_idx = next((i for i, h in enumerate(header) if h in ("question", "pertanyaan", "q")), None)
    a_idx = next((i for i, h in enumerate(header) if h in ("answer", "jawaban", "a")), None)

    lines: list[str] = []
    if q_idx is not None and a_idx is not None:
        for r in data_rows:
            if len(r) > max(q_idx, a_idx):
                q = (r[q_idx] or "").strip()
                a = (r[a_idx] or "").strip()
                if q and a:
                    lines.append(f"Q: {q}\nA: {a}")
    else:
        for r in data_rows:
            cells = []
            for i, v in enumerate(r):
                v = (v or "").strip()
                if not v:
                    continue
                col = header[i] if i < len(header) and header[i] else f"col{i + 1}"
                cells.append(f"{col}: {v}")
            if cells:
                lines.append(" | ".join(cells))

    return "\n\n".join(lines)


_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def _clean_markdown_text(text: str) -> str:
    """Bersihkan sintaks markdown dasar agar teks lebih natural untuk embedding/LLM."""
    t = _MD_LINK_RE.sub(r"\1", text or "")
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"(\*\*|__|\*|_|`)", "", t)
    t = re.sub(r"^[-*+]\s+", "- ", t, flags=re.MULTILINE)
    t = re.sub(r"^>\s*", "", t, flags=re.MULTILINE)
    return t.strip()


async def _run_knowledge_builder_pipeline(doc_id: str) -> None:
    """Auto Knowledge Builder: ringkasan, kategori, tag, intent, FAQ, SOP, dan
    Knowledge Quality Score untuk satu dokumen.

    Dipanggil fire-and-forget via asyncio.create_task setelah dokumen berhasil
    di-chunk & di-embed, supaya tidak menghambat response upload.
    """
    pool = await get_pool_safe()
    if not pool:
        return
    try:
        doc = await pool.fetchrow(
            "SELECT id, org_id, bot_id, filename, status FROM documents WHERE id=$1", doc_id
        )
        if not doc or doc["status"] != "ready":
            return

        await pool.execute(
            "UPDATE documents SET kb_status='processing', kb_error=NULL WHERE id=$1", doc_id
        )

        chunk_rows = await pool.fetch(
            "SELECT content FROM doc_chunks WHERE document_id=$1 ORDER BY chunk_index", doc_id
        )
        text = "\n\n".join(r["content"] for r in chunk_rows).strip()
        if not text:
            await pool.execute(
                "UPDATE documents SET kb_status='failed', kb_error=$1 WHERE id=$2",
                "Tidak ada konten untuk dianalisis.", doc_id,
            )
            return

        if not cfg.groq_api_key:
            await pool.execute(
                "UPDATE documents SET kb_status='skipped', kb_error=$1 WHERE id=$2",
                "AI belum dikonfigurasi (GROQ_API_KEY kosong).", doc_id,
            )
            return

        agent = get_knowledge_builder_agent()
        title = doc["filename"] or ""
        org_id = str(doc["org_id"])
        bot_id = doc["bot_id"]

        classification = await agent.classify(title=title, text=text)
        summary = await agent.summarize(title=title, text=text)
        faqs = await agent.generate_faqs(title=title, text=text)
        sops = await agent.generate_sops(title=title, text=text)
        quality = await agent.assess_quality(
            title=title, text=text,
            faq_count=len(faqs.get("faqs", [])),
            sop_count=len(sops.get("sops", [])),
            existing_categories=classification.get("categories"),
        )

        if any(part.get("_llm_unavailable") for part in (classification, summary, faqs, sops, quality)):
            await pool.execute(
                "UPDATE documents SET kb_status='failed', kb_error=$1 WHERE id=$2",
                "AI sedang tidak tersedia (limit/quota). Coba generate ulang nanti.", doc_id,
            )
            return

        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """UPDATE documents
                       SET summary=$1, categories=$2::jsonb, tags=$3::jsonb,
                           suggested_intents=$4::jsonb, kb_status='ready', kb_error=NULL
                       WHERE id=$5""",
                    summary.get("summary") or "",
                    json.dumps(classification.get("categories") or []),
                    json.dumps(classification.get("tags") or []),
                    json.dumps(classification.get("suggested_intents") or []),
                    doc_id,
                )

                await conn.execute(
                    "DELETE FROM kb_generated_faqs WHERE document_id=$1 AND source='ai'", doc_id
                )
                for item in faqs.get("faqs", []):
                    await conn.execute(
                        """INSERT INTO kb_generated_faqs
                           (id, org_id, bot_id, document_id, question, answer, category, source, status)
                           VALUES ($1,$2,$3,$4,$5,$6,$7,'ai','suggested')""",
                        str(uuid.uuid4()), org_id, bot_id, doc_id,
                        item["question"], item["answer"], item.get("category"),
                    )

                await conn.execute("DELETE FROM kb_generated_sops WHERE document_id=$1", doc_id)
                for item in sops.get("sops", []):
                    await conn.execute(
                        """INSERT INTO kb_generated_sops
                           (id, org_id, bot_id, document_id, title, steps, category, status)
                           VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,'suggested')""",
                        str(uuid.uuid4()), org_id, bot_id, doc_id,
                        item["title"], json.dumps(item["steps"]), item.get("category"),
                    )

                await conn.execute(
                    """INSERT INTO kb_quality_reports
                       (id, org_id, bot_id, document_id, completeness_score, redundancy_score,
                        coverage_score, overall_score, missing_topics, duplicate_groups)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb)""",
                    str(uuid.uuid4()), org_id, bot_id, doc_id,
                    quality["completeness_score"], quality["redundancy_score"],
                    quality["coverage_score"], quality["overall_score"],
                    json.dumps(quality["missing_topics"]), json.dumps(quality["duplicate_groups"]),
                )
    except Exception as e:
        logger.exception("Knowledge Builder pipeline gagal untuk dokumen %s", doc_id)
        try:
            await pool.execute(
                "UPDATE documents SET kb_status='failed', kb_error=$1 WHERE id=$2",
                str(e)[:500], doc_id,
            )
        except Exception:
            pass


def get_workflow_agent_config() -> dict:
    """Kredensial LLM untuk node kategori 'agent' di AI Workflow Builder.

    Juga dipakai bn_platform/research.py untuk kredensial web search
    (searxng_url/search_api_key) -- caller lain (workflow builder) cukup
    mengabaikan 2 key tambahan ini."""
    return {
        "api_key": cfg.groq_api_key,
        "model": cfg.groq_cheap_model or cfg.groq_model,
        "base_url": (cfg.groq_base_url or "").strip() or None,
        "app_url": cfg.app_url,
        "searxng_url": cfg.searxng_url,
        "search_api_key": cfg.search_api_key,
    }


def _real_client_ip(request: Request) -> str:
    """IP visitor sebenarnya di belakang Cloudflare Tunnel -- request.client.host
    saja akan selalu memberi IP edge Cloudflare, bukan IP visitor."""
    forwarded = request.headers.get("X-Forwarded-For") or request.headers.get("CF-Connecting-IP")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.post("/api/public/investor-demo", include_in_schema=False)
async def public_investor_demo(request: Request):
    """Investor Demo Mode publik, TANPA login -- untuk link demo yang dibagikan ke
    investor/pemerintah/inkubator. Memanggil exec_agent_module.run_investor_demo()
    yang sudah ada (AI Workforce Phase Next 15) APA ADANYA: skenario 100% sintetis,
    tidak pernah menyentuh data tenant manapun, jadi aman dipanggil tanpa auth.
    Rate-limit per IP (bukan per org_id, karena pengunjung anonim)."""
    ip = _real_client_ip(request)
    if _platform_check_rate_limit:
        _platform_check_rate_limit(f"public-demo:{ip}", 5)
    agent_cfg = get_workflow_agent_config()
    agent = exec_agent_module.ExecutiveAgent(
        api_key=agent_cfg.get("api_key"), model=agent_cfg.get("model"),
        base_url=agent_cfg.get("base_url"), app_url=agent_cfg.get("app_url", "https://botnesia.id"),
    )
    return await exec_agent_module.run_investor_demo(agent=agent)


async def _dispatch_workflow_trigger(
    trigger_type: str, payload: dict, *, org_id: str, bot_id: str | None,
) -> None:
    """Cari & jalankan AI Workflow yang published untuk event trigger ini.

    Dipanggil fire-and-forget via asyncio.create_task supaya tidak menghambat
    response endpoint pemicu (chat/handoff/dll).
    """
    pool = await get_pool_safe()
    if not pool:
        return
    try:
        from workflow_engine import trigger_workflows
        await trigger_workflows(
            pool, org_id=org_id, bot_id=bot_id, trigger_type=trigger_type, payload=payload,
            agent_config=get_workflow_agent_config(), enqueue_handoff_fn=_platform_enqueue_handoff,
        )
    except Exception:
        logger.exception("Workflow trigger dispatch gagal (trigger=%s org=%s)", trigger_type, org_id)


async def _on_new_lead_workflow_trigger(*, org_id: str, bot_id: str, end_user_id: str, category: str, score, end_user: dict) -> None:
    """Callback untuk lead_engine.recompute_leads — picu workflow trigger 'new_lead'
    saat kategori lead seorang pelanggan berubah menjadi warm/hot."""
    payload = {
        "end_user_id": end_user_id,
        "bot_id": bot_id,
        "category": category,
        "score": float(score) if score is not None else None,
        "customer_type": category,
        "end_user_name": end_user.get("display_name"),
        "end_user_email": end_user.get("email"),
        "tags": list(end_user.get("preferred_topics") or []),
    }
    await _dispatch_workflow_trigger("new_lead", payload, org_id=org_id, bot_id=bot_id)


class KnowledgeBaseUrlReq(BaseModel):
    url: str
    title: str | None = None


class KnowledgeUrlSeedEntry(BaseModel):
    url: str
    title: str | None = None
    category: str | None = None
    priority: str = "normal"
    agent: str | None = None
    language: str = "id"
    trusted: bool = False


class KnowledgeBulkUrlReq(BaseModel):
    bot_id: str
    urls: list[KnowledgeUrlSeedEntry] = Field(default_factory=list)
    crawl: bool = True


class KnowledgeSeedReq(BaseModel):
    bot_id: str
    crawl: bool = True


class MarketplaceKnowledgeSeedReq(BaseModel):
    bot_id: str | None = None
    crawl: bool = False
    installed_only: bool = False


class KnowledgeRetryFailedReq(BaseModel):
    bot_id: str | None = None
    agent_id: str | None = None
    category: str | None = None
    crawl: bool = False


async def _require_owned_bot(pool: asyncpg.Pool, bot_id: str, org_id: str):
    bot = await pool.fetchrow(
        "SELECT id, org_id, name FROM bots WHERE id=$1 AND org_id=$2", bot_id, org_id
    )
    if not bot:
        raise HTTPException(404, "Bot tidak ditemukan")
    return bot


def _schedule_knowledge_crawl(pool: asyncpg.Pool, *, org_id: str, bot_id: str, batch_size: int = 10) -> None:
    asyncio.create_task(
        knowledge_seeder.run_crawler_batch(
            pool,
            org_id=str(org_id),
            bot_id=str(bot_id),
            fetch_fn=_fetch_website_text,
            process_fn=_process_document_sync,
            batch_size=batch_size,
        )
    )


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


@app.post("/api/knowledge/urls/bulk")
async def knowledge_bulk_urls(
    body: KnowledgeBulkUrlReq,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    """Bulk import URL ke queue knowledge_sources, lalu crawl background terbatas."""
    await _require_owned_bot(pool, body.bot_id, user["org_id"])
    result = await knowledge_seeder.bulk_import_urls(
        pool,
        org_id=str(user["org_id"]),
        bot_id=str(body.bot_id),
        urls_data=[entry.model_dump() for entry in body.urls],
    )
    result["stats"] = await knowledge_seeder.get_source_stats(
        pool, org_id=str(user["org_id"]), bot_id=str(body.bot_id)
    )
    if body.crawl and result.get("imported", 0) > 0:
        _schedule_knowledge_crawl(pool, org_id=user["org_id"], bot_id=body.bot_id)
        result["crawler"] = "scheduled"
    return result


@app.get("/api/knowledge/sources")
async def knowledge_sources(
    bot_id: str | None = None,
    status: str | None = None,
    category: str | None = None,
    agent_id: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    if bot_id:
        await _require_owned_bot(pool, bot_id, user["org_id"])
    rows, stats = await asyncio.gather(
        knowledge_seeder.get_sources(
            pool,
            org_id=str(user["org_id"]),
            bot_id=bot_id,
            status=status,
            category=category,
            agent_id=agent_id,
            search=search,
            limit=max(1, min(200, int(limit or 50))),
            offset=max(0, int(offset or 0)),
        ),
        knowledge_seeder.get_source_stats(pool, org_id=str(user["org_id"]), bot_id=bot_id),
    )
    return {"sources": rows, "stats": stats}


@app.get("/api/knowledge/sources/{source_id}")
async def knowledge_source_detail(
    source_id: str,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    row = await pool.fetchrow(
        """SELECT id, org_id, bot_id, url, title, category, agent_type, priority, language,
                  trusted, status, error_message, retry_count, document_id, last_crawled_at, created_at
             FROM knowledge_sources WHERE id=$1 AND org_id=$2""",
        source_id,
        user["org_id"],
    )
    if not row:
        raise HTTPException(404, "Knowledge source tidak ditemukan")
    return dict(row)


@app.post("/api/knowledge/sources/{source_id}/retry")
async def knowledge_source_retry(
    source_id: str,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    row = await pool.fetchrow(
        "SELECT id, bot_id FROM knowledge_sources WHERE id=$1 AND org_id=$2",
        source_id,
        user["org_id"],
    )
    if not row:
        raise HTTPException(404, "Knowledge source tidak ditemukan")
    ok = await knowledge_seeder.retry_source(pool, source_id=source_id, org_id=str(user["org_id"]))
    if not ok:
        raise HTTPException(400, "Source tidak bisa diretry atau sudah mencapai batas retry")
    _schedule_knowledge_crawl(pool, org_id=user["org_id"], bot_id=str(row["bot_id"]), batch_size=5)
    return {"message": "Retry dijadwalkan", "source_id": source_id}


@app.delete("/api/knowledge/sources/{source_id}")
async def knowledge_source_delete(
    source_id: str,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    ok = await knowledge_seeder.delete_source(pool, source_id=source_id, org_id=str(user["org_id"]))
    if not ok:
        raise HTTPException(404, "Knowledge source tidak ditemukan")
    return {"message": "Knowledge source dihapus"}


@app.post("/api/knowledge/seed/general")
async def knowledge_seed_general(
    body: KnowledgeSeedReq,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    await _require_owned_bot(pool, body.bot_id, user["org_id"])
    result = await knowledge_seeder.seed_agent_urls(
        pool, org_id=str(user["org_id"]), bot_id=body.bot_id, agent_type="general_ai"
    )
    result["stats"] = await knowledge_seeder.get_source_stats(pool, org_id=str(user["org_id"]), bot_id=body.bot_id)
    if body.crawl and result.get("imported", 0) > 0:
        _schedule_knowledge_crawl(pool, org_id=user["org_id"], bot_id=body.bot_id)
        result["crawler"] = "scheduled"
    return result


@app.post("/api/knowledge/seed/agents")
async def knowledge_seed_all_agents(
    body: KnowledgeSeedReq,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    await _require_owned_bot(pool, body.bot_id, user["org_id"])
    agent_types = [
        "travel_agent", "ecommerce_agent", "clinic_agent", "school_agent", "sales_agent",
        "property_agent", "faq_agent", "customer_service_agent", "botnesia_business",
    ]
    results = {}
    for agent_type in agent_types:
        results[agent_type] = await knowledge_seeder.seed_agent_urls(
            pool, org_id=str(user["org_id"]), bot_id=body.bot_id, agent_type=agent_type
        )
    if body.crawl:
        _schedule_knowledge_crawl(pool, org_id=user["org_id"], bot_id=body.bot_id)
    return {"results": results, "stats": await knowledge_seeder.get_source_stats(pool, org_id=str(user["org_id"]), bot_id=body.bot_id)}


@app.post("/api/knowledge/seed/marketplace-1000")
async def knowledge_seed_marketplace_1000(
    body: MarketplaceKnowledgeSeedReq,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    """Queue 1000+ marketplace URL seeds. Does not crawl by default."""
    if body.bot_id:
        await _require_owned_bot(pool, body.bot_id, user["org_id"])
    result = await knowledge_seeder.bulk_import_marketplace_seed(
        pool,
        org_id=str(user["org_id"]),
        fallback_bot_id=body.bot_id,
        installed_only=body.installed_only,
    )
    result["status"] = await knowledge_seeder.get_marketplace_seed_status(
        pool, org_id=str(user["org_id"]), bot_id=body.bot_id,
    )
    if body.crawl and result.get("imported", 0) > 0:
        for touched_bot in result.get("touched_bots", [])[:3]:
            _schedule_knowledge_crawl(pool, org_id=user["org_id"], bot_id=touched_bot, batch_size=5)
        result["crawler"] = "scheduled_limited_batch"
    else:
        result["crawler"] = "not_scheduled"
    return result


@app.get("/api/knowledge/seed/status")
async def knowledge_seed_status(
    bot_id: str | None = None,
    agent_id: str | None = None,
    category: str | None = None,
    search: str | None = None,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    if bot_id:
        await _require_owned_bot(pool, bot_id, user["org_id"])
    return await knowledge_seeder.get_marketplace_seed_status(
        pool,
        org_id=str(user["org_id"]),
        bot_id=bot_id,
        agent_id=agent_id,
        category=category,
        search=search,
    )


@app.post("/api/knowledge/sources/retry-failed")
async def knowledge_sources_retry_failed(
    body: KnowledgeRetryFailedReq,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    if body.bot_id:
        await _require_owned_bot(pool, body.bot_id, user["org_id"])
    retried = await knowledge_seeder.retry_failed_sources(
        pool,
        org_id=str(user["org_id"]),
        bot_id=body.bot_id,
        agent_id=body.agent_id,
        category=body.category,
    )
    if body.crawl and body.bot_id and retried:
        _schedule_knowledge_crawl(pool, org_id=user["org_id"], bot_id=body.bot_id, batch_size=5)
    return {"retried": retried, "crawler": "scheduled_limited_batch" if body.crawl and body.bot_id and retried else "not_scheduled"}


@app.post("/api/knowledge/seed/{agent_id}")
async def knowledge_seed_agent(
    agent_id: str,
    body: KnowledgeSeedReq,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    await _require_owned_bot(pool, body.bot_id, user["org_id"])
    agent_type = agent_id.strip().lower().replace("-", "_")
    result = await knowledge_seeder.seed_agent_urls(
        pool, org_id=str(user["org_id"]), bot_id=body.bot_id, agent_type=agent_type
    )
    result["stats"] = await knowledge_seeder.get_source_stats(pool, org_id=str(user["org_id"]), bot_id=body.bot_id)
    if body.crawl and result.get("imported", 0) > 0:
        _schedule_knowledge_crawl(pool, org_id=user["org_id"], bot_id=body.bot_id)
        result["crawler"] = "scheduled"
    return result


@app.post("/bots/{bot_id}/documents/faq-import", status_code=201)
async def import_faq_csv(
    bot_id: str,
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    pool=Depends(get_pool),
):
    """Import FAQ langsung dari CSV (kolom question/pertanyaan & answer/jawaban,
    opsional category/kategori). Setiap baris otomatis di-approve dan langsung
    masuk knowledge base (doc_chunks + embeddings) tanpa melalui AI generation."""
    bot = await pool.fetchrow(
        "SELECT id FROM bots WHERE id=$1 AND org_id=$2", bot_id, user["org_id"]
    )
    if not bot:
        raise HTTPException(404, "Bot tidak ditemukan")

    if _platform_check_limit:
        ok, detail = await _platform_check_limit(pool, user["org_id"], "knowledge")
        if not ok:
            raise HTTPException(
                402,
                f"Limit jumlah dokumen knowledge base paket '{detail['plan']}' tercapai "
                f"({detail['used']}/{detail['limit']}). Upgrade di /api/billing/checkout.",
            )

    contents = await file.read()
    try:
        reader = csv.reader(io.StringIO(contents.decode("utf-8-sig", errors="ignore")))
        rows = [r for r in reader if any((c or "").strip() for c in r)]
    except Exception as e:
        raise HTTPException(400, f"Gagal membaca CSV: {e}")

    if len(rows) < 2:
        raise HTTPException(400, "CSV harus memiliki header dan minimal 1 baris data.")

    header = [(c or "").strip().lower() for c in rows[0]]
    q_idx = next((i for i, h in enumerate(header) if h in ("question", "pertanyaan", "q")), None)
    a_idx = next((i for i, h in enumerate(header) if h in ("answer", "jawaban", "a")), None)
    c_idx = next((i for i, h in enumerate(header) if h in ("category", "kategori")), None)
    if q_idx is None or a_idx is None:
        raise HTTPException(400, "CSV harus memiliki kolom 'question'/'pertanyaan' dan 'answer'/'jawaban'.")

    pairs: list[tuple[str, str, str | None]] = []
    for r in rows[1:]:
        if len(r) <= max(q_idx, a_idx):
            continue
        q = (r[q_idx] or "").strip()
        a = (r[a_idx] or "").strip()
        if not q or not a:
            continue
        category = (r[c_idx] or "").strip() if c_idx is not None and len(r) > c_idx else ""
        pairs.append((q, a, category or None))

    if not pairs:
        raise HTTPException(400, "Tidak ada pasangan pertanyaan/jawaban valid di CSV.")

    doc_id = str(uuid.uuid4())
    org_id = user["org_id"]
    await pool.execute(
        """INSERT INTO documents
           (id, org_id, bot_id, filename, file_size, mime_type, status, source_type, source_url,
            kb_status, chunk_count, processed_at)
           VALUES ($1,$2,$3,$4,$5,'text/csv','ready','faq_import',NULL,'ready',$6,NOW())""",
        doc_id, org_id, bot_id, file.filename or "faq-import.csv", len(contents), len(pairs),
    )

    async with pool.acquire() as conn:
        async with conn.transaction():
            chunk_rows: list[tuple[str, str]] = []
            for i, (q, a, category) in enumerate(pairs):
                chunk_id = str(uuid.uuid4())
                chunk_text = f"Q: {q}\nA: {a}"
                await conn.execute(
                    """INSERT INTO doc_chunks (id, document_id, org_id, chunk_index, content, token_count)
                       VALUES ($1,$2,$3,$4,$5,$6)""",
                    chunk_id, doc_id, org_id, i, chunk_text, len(chunk_text.split()),
                )
                chunk_rows.append((chunk_id, chunk_text))
                await conn.execute(
                    """INSERT INTO kb_generated_faqs
                       (id, org_id, bot_id, document_id, question, answer, category, source, status, chunk_id)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,'import','approved',$8)""",
                    str(uuid.uuid4()), org_id, bot_id, doc_id, q, a, category, chunk_id,
                )
            await _store_chunk_embeddings(conn, str(org_id), chunk_rows)

    return {"doc_id": doc_id, "imported": len(pairs), "status": "ready"}


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

    if _platform_write_audit:
        try:
            await _platform_write_audit(
                pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
                action="delete", resource_type="document", resource_id=doc_id,
                metadata={"bot_id": bot_id},
            )
        except Exception:
            pass

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
                  b.computer_agent_enabled,
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
    internal_channel = str(user_meta.get("_channel") or user_meta.get("channel") or "widget")
    safe_user_meta = {key: value for key, value in user_meta.items() if key not in {"channel", "_channel"}}
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
        # Jangan sampai rate limiter crash chat -- tapi tetap log supaya
        # operator tahu rate limiting diam-diam tidak aktif untuk request ini,
        # bukan cuma "tidak ada apa-apa" di log.
        logger.exception(
            "Rate limiter gagal, request dilanjutkan TANPA rate limiting org=%s bot=%s",
            bot["org_id"], bot_id,
        )

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
    conv = None
    if conv_id:
        conv = await pool.fetchrow(
            "SELECT id, language FROM conversations WHERE id=$1 AND bot_id=$2", conv_id, bot_id
        )
        # Connector internal memakai UUID deterministik agar seluruh pesan user
        # dari channel yang sama tetap berada pada satu memory thread.
        if not conv and not user_meta.get("_channel"):
            conv_id = None

    is_new_conversation = not bool(conv)
    if not conv:
        conv_id = conv_id or str(uuid.uuid4())
        user_meta = body.user_meta or {}
        await pool.execute(
            """INSERT INTO conversations
               (id, bot_id, org_id, end_user_id, end_user_name, end_user_email, end_user_meta, channel)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
            conv_id, bot_id, bot["org_id"],
            user_meta.get("userId"), user_meta.get("name") or user_meta.get("display_name"),
            user_meta.get("email"), json.dumps(safe_user_meta), internal_channel,
        )
        asyncio.create_task(_dispatch_workflow_trigger(
            "new_customer",
            {
                "conversation_id": conv_id, "bot_id": bot_id,
                "end_user_id": user_meta.get("userId"), "end_user_name": user_meta.get("name"),
                "end_user_email": user_meta.get("email"), "customer_type": "new",
            },
            org_id=str(bot["org_id"]), bot_id=bot_id,
        ))

    # 4. Simpan pesan user
    user_msg_id = str(uuid.uuid4())
    await pool.execute(
        "INSERT INTO messages (id, conversation_id, role, content) VALUES ($1,$2,'user',$3)",
        user_msg_id, conv_id, body.message,
    )

    # Percakapan yang sedang diambil alih manusia tidak boleh memanggil AI.
    try:
        active_handoff = await pool.fetchrow(
            """SELECT id, status FROM human_queue
               WHERE conversation_id=$1 AND status IN ('waiting','assigned')""",
            conv_id,
        )
    except Exception:
        active_handoff = None
    if active_handoff:
        handoff_answer = (
            "Percakapan ini sedang ditangani oleh tim manusia kami. "
            "Pesan Anda sudah diteruskan dan agent akan membalas secepatnya."
        )
        await pool.execute(
            """INSERT INTO messages
               (id, conversation_id, role, content, model, input_tokens, output_tokens, latency_ms)
               VALUES ($1,$2,'assistant',$3,'system:human-handoff',0,0,0)""",
            str(uuid.uuid4()), conv_id, handoff_answer,
        )
        await pool.execute(
            "UPDATE conversations SET msg_count=msg_count+2, last_msg_at=NOW() WHERE id=$1",
            conv_id,
        )
        return {
            "answer": handoff_answer, "session_id": conv_id, "latency_ms": 0,
            "handoff": True, "handoff_status": str(active_handoff["status"]),
            "intent": "human_handoff", "selected_agent": "Human Handoff Agent",
            "confidence": None, "handoff_offered": True,
            "sources": [], "follow_up_questions": [],
        }

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
    _kb_started = time.perf_counter()
    relevant_chunks = await _retrieve_chunks(pool, bot["org_id"], body.message, bot_id=bot_id)
    _kb_ms = (time.perf_counter() - _kb_started) * 1000
    logger.info(
        "kb_retrieval org_id=%s bot_id=%s conv_id=%s chunks=%s latency_ms=%.1f",
        bot["org_id"], bot_id, conv_id, len(relevant_chunks), _kb_ms,
    )
    if _kb_ms > KB_RETRIEVAL_LATENCY_BUDGET_MS:
        logger.warning(
            "Knowledge retrieval melebihi budget %sms: %.1fms (org_id=%s, bot_id=%s, conv_id=%s, chunks=%s)",
            KB_RETRIEVAL_LATENCY_BUDGET_MS, _kb_ms, bot["org_id"], bot_id, conv_id, len(relevant_chunks),
        )

    # 7. Resolve effective language and build system prompt
    effective_lang = language_middleware.resolve_language(
        user_message=body.message,
        agent_language=bot.get("language"),
        conversation_language=(conv.get("language") if conv else None),
    )
    await pool.execute(
        "UPDATE conversations SET language=$2 WHERE id=$1",
        conv_id, effective_lang,
    )
    system = language_middleware.build_system_prompt(
        bot["system_prompt"], relevant_chunks, effective_lang
    )
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
                market_title = "Financial market data (real-time)" if effective_lang == "en" else "Data pasar finansial (real-time)"
                market_instruction = (
                    "Important instruction: If the user asks about prices, exchange rates, stock moves, or crypto moves, use the market data above as the primary basis for the answer. Do not say you lack real-time access when market data is available."
                    if effective_lang == "en" else
                    "Instruksi penting: Jika user bertanya harga/kurs/perubahan saham atau kripto, gunakan data pasar di atas sebagai jawaban utama. Jangan bilang tidak punya akses real-time jika data pasar tersedia."
                )
                system = (
                    system
                    + f"\n\n## {market_title}:\n"
                    + "\n\n".join(market_blocks)
                    + "\n\n"
                    + market_instruction
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
            # RSS discovery and article-body fetching are sequential stages.
            # Give detailed requests enough total time to complete both stages.
            total_news_timeout = news_timeout * (2 if news_needs_bodies else 1) + 2.0
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
                timeout=total_news_timeout,
            )
            if news_ctx:
                news_title = "Latest news (real-time)" if effective_lang == "en" else "Berita terkini (real-time)"
                news_instruction = (
                    "Important instruction: Answer based on the news data above and do not add unavailable facts. For each story, include the title, media/feed, publication date when available, and source URL. If article text is available, use that text and quotes as the primary basis. If only an RSS summary is available, summarize it and briefly state that the full article details are not available. If the user asks for solutions or business impact, clearly separate news facts from your analysis."
                    if effective_lang == "en" else
                    "Instruksi penting: Jawab berdasarkan data berita di atas dan jangan menambah fakta yang tidak tersedia. Untuk setiap berita, cantumkan judul, media/feed, tanggal terbit jika ada, dan URL sumber. Jika teks artikel tersedia, gunakan teks dan kutipan sebagai dasar utama. Jika hanya ringkasan RSS yang tersedia, tetap rangkum informasi tersebut dan jelaskan singkat bahwa detail artikel penuh belum tersedia. Jika user meminta solusi atau dampak bisnis, pisahkan dengan jelas antara fakta berita dan analisismu."
                )
                system = (
                    system
                    + f"\n\n## {news_title}:\n"
                    + news_ctx
                    + "\n\n"
                    + news_instruction
                )
        except Exception as exc:
            logger.warning(
                "News retrieval failed for query=%r: %s",
                body.message[:120],
                exc,
            )

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

    # 7.55 AI Workforce Phase 8 — Self Learning Company: insight yang sudah
    # di-approve manusia (lihat self_learning_engine.py) disuntik sebagai
    # konteks tambahan, no LLM di sini supaya tidak nambah latensi/biaya.
    try:
        from self_learning_engine import build_organizational_learning_context
        learning_context = await build_organizational_learning_context(pool, str(bot["org_id"]), bot_id)
    except Exception:
        learning_context = ""
    if learning_context:
        system = system + "\n\n" + learning_context

    # 7.6 Chat + Image: deteksi & generate gambar inline (seperti ChatGPT). Dijalankan
    # SEBELUM supervisor supaya jawaban LLM bisa menjelaskan gambar yang sudah dibuat.
    chat_image_url: str | None = None
    chat_image_provider: str | None = None
    if image_providers.looks_like_image_request(body.message):
        img_retry_after = _check_media_cooldown(f"chat-image:{bot_id}", "image")
        if img_retry_after == 0:
            try:
                img_result = await _run_image_generation(
                    org_id=str(bot["org_id"]), user_id=user_meta.get("userId"),
                    pool=pool, prompt=body.message, bot_id=bot_id, conversation_id=conv_id,
                )
                chat_image_url = img_result["image_url"]
                chat_image_provider = img_result["provider"]
                image_note = (
                    "## Image generated successfully\nThe system has generated the requested image and it will be displayed directly in chat. Write a brief answer (1-2 sentences) explaining the generated image according to the user's request. Do not say you cannot create images."
                    if effective_lang == "en" else
                    "## Gambar berhasil dibuat\nSistem sudah berhasil membuat gambar sesuai permintaan user dan akan ditampilkan langsung di chat. Tulis jawaban singkat (1-2 kalimat) yang menjelaskan gambar yang dibuat sesuai permintaan user. Jangan bilang tidak bisa membuat gambar."
                )
                system = system + "\n\n" + image_note
            except HTTPException as exc:
                logger.info("Chat+Image dilewati conv=%s: %s", conv_id, exc.detail)
                image_error_note = (
                    f"## Image generation failed\nThe system failed to generate the image ({exc.detail}). Briefly and politely explain this to the user without technical jargon."
                    if effective_lang == "en" else
                    f"## Gambar gagal dibuat\nSistem gagal membuat gambar ({exc.detail}). Jelaskan ke user secara singkat dan sopan, tanpa istilah teknis."
                )
                system = system + "\n\n" + image_error_note
            except Exception as exc:
                logger.warning("Chat+Image error conv=%s: %s", conv_id, exc)

    # 7.7 Chat + Computer Agent: deteksi & jalankan browsing (AI Agent Platform
    # Phase 3). Opt-in per bot (default FALSE -- bot lama tidak terpengaruh).
    # Aksi baca-saja auto-execute (mirip Chat+Image); aksi tulis (klik/isi
    # form/submit) TIDAK pernah auto-execute -- hanya disimpan sebagai task
    # pending_approval, dieksekusi nanti lewat endpoint approve setelah
    # disetujui staf tenant (lihat bn_platform/computer_agent.py).
    chat_ca_screenshot_url: str | None = None
    if bot.get("computer_agent_enabled") and computer_agent.looks_like_computer_agent_request(body.message):
        ca_retry_after = _check_media_cooldown(f"chat-computer-agent:{bot_id}", "computer_agent")
        if ca_retry_after == 0:
            try:
                ca_agent = computer_agent.ComputerAgent(
                    api_key=cfg.groq_api_key, model=cfg.groq_cheap_model or cfg.groq_model,
                    base_url=(cfg.groq_base_url or "").strip() or None,
                )
                ca_steps = await ca_agent.plan_actions(body.message)
                if computer_agent.is_write_plan(ca_steps):
                    await computer_agent.create_task(
                        pool, org_id=str(bot["org_id"]), bot_id=bot_id, conversation_id=conv_id,
                        goal=body.message, steps=ca_steps, status="pending_approval",
                        created_by=user_meta.get("userId"),
                    )
                    approval_note = (
                        "## Request requires approval\nThe user's request involves an action that changes something on another site (clicking, filling a form, or submitting). The system did NOT run it automatically; it has been recorded and is waiting for team approval. Briefly and politely tell the user that the request is waiting for team approval before execution."
                        if effective_lang == "en" else
                        "## Permintaan butuh approval\nPermintaan user melibatkan aksi yang mengubah sesuatu di situs lain (klik/isi form/submit) -- sistem TIDAK menjalankannya otomatis, sudah dicatat dan menunggu persetujuan tim. Beri tahu user secara singkat dan sopan bahwa permintaannya sedang menunggu persetujuan tim sebelum dijalankan."
                    )
                    system = system + "\n\n" + approval_note
                else:
                    ca_result = await ca_agent.execute_read_only(ca_steps)
                    await computer_agent.create_task(
                        pool, org_id=str(bot["org_id"]), bot_id=bot_id, conversation_id=conv_id,
                        goal=body.message, steps=ca_steps,
                        status="completed" if ca_result.get("success") else "failed",
                        result=ca_result, created_by=user_meta.get("userId"),
                    )
                    if ca_result.get("success"):
                        chat_ca_screenshot_url = ca_result.get("screenshot_url")
                        screenshot_note = (
                            "\n\nThe system also captured a screenshot of this page and will display it directly in chat. Mention that; do not say you cannot take screenshots." if (chat_ca_screenshot_url and effective_lang == "en") else
                            "\n\nSistem juga sudah mengambil screenshot halaman ini dan akan menampilkannya langsung di chat -- sebutkan itu, jangan bilang tidak bisa mengambil screenshot." if chat_ca_screenshot_url else ""
                        )
                        system = (
                            system
                            + ("\n\n## Computer Agent result\n" if effective_lang == "en" else "\n\n## Hasil Computer Agent\n")
                            + (ca_result.get("text") or ("(the page has no readable text. Do not invent page contents; be honest that no text was readable)" if effective_lang == "en" else "(halaman tidak punya teks yang bisa dibaca -- jangan mengarang isi halaman, katakan jujur kalau tidak ada teks yang terbaca)"))
                            + screenshot_note
                            + "\n\n" + computer_agent.COMPUTER_AGENT_DATA_BLOCK
                        )
                    else:
                        computer_error_note = (
                            f"## Computer Agent failed\nThe system failed to run the request ({ca_result.get('error')}). Briefly and politely explain this to the user without technical jargon."
                            if effective_lang == "en" else
                            f"## Computer Agent gagal\nSistem gagal menjalankan permintaan ({ca_result.get('error')}). Jelaskan ke user secara singkat dan sopan, tanpa istilah teknis."
                        )
                        system = system + "\n\n" + computer_error_note
            except Exception as exc:
                logger.warning("Chat+ComputerAgent error conv=%s: %s", conv_id, exc)

    # 8. Panggil AI (Multi-Agent pipeline buatan kamu)
    t_start = time.monotonic()
    agent_meta: dict | None = None
    result = None
    should_handoff = False
    handoff_reason: str | None = None
    handoff_priority = "medium"
    intent_routing: dict = {}
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
            "metadata": safe_user_meta,
            "reasoning_mode": bot["reasoning_mode"],
            "self_knowledge_context": self_knowledge_context,
            "business_context": business_context,
            "_observability_pool": pool,
            "_cheap_model": cfg.groq_cheap_model,
            "_strong_model": cfg.groq_model,
            "_search_api_key": cfg.search_api_key,
            "_searxng_url": cfg.searxng_url,
            "kb_chunks_count": len(relevant_chunks),
            "selected_language": effective_lang,
        }
        result = await supervisor.process(intelligence_context)
        answer = result.final_answer

        # Output language validation — regenerate if language mismatch detected.
        # The first retry re-runs the full supervisor with a stronger language rule.
        # If KB language still pulls the answer off-target, the second pass rewrites
        # only the draft answer in an isolated language-correction prompt.
        if answer and not language_middleware.validate_output_language(answer, effective_lang):
            logger.info(
                "Language mismatch (expected=%s) conv=%s — retrying with enforcement suffix",
                effective_lang, conv_id,
            )
            retry_context = dict(intelligence_context)
            retry_context["knowledge_base_context"] = (
                system + language_middleware.language_enforcement_suffix(effective_lang)
            )
            try:
                retry_result = await supervisor.process(retry_context)
                if retry_result.final_answer:
                    answer = retry_result.final_answer
                    result = retry_result
            except Exception as _lang_retry_exc:
                logger.warning("Language retry failed: %s", _lang_retry_exc)

        if answer and not language_middleware.validate_output_language(answer, effective_lang):
            logger.info(
                "Language mismatch persisted (expected=%s) conv=%s — rewriting final answer only",
                effective_lang, conv_id,
            )
            rewrite_system = (
                "You are a language correction layer. Rewrite the draft answer entirely in English. "
                "Preserve the meaning and factual content. Do not add new facts. Return only the rewritten answer."
                if effective_lang == "en" else
                "Kamu adalah lapisan koreksi bahasa. Tulis ulang draft jawaban sepenuhnya dalam Bahasa Indonesia. "
                "Pertahankan makna dan fakta. Jangan menambah fakta baru. Kembalikan hanya jawaban yang sudah ditulis ulang."
            )
            rewrite_user = (
                f"User message:\n{body.message}\n\nDraft answer:\n{answer}"
                if effective_lang == "en" else
                f"Pesan pengguna:\n{body.message}\n\nDraft jawaban:\n{answer}"
            )
            try:
                rewritten_answer = (await supervisor.cs_agent._call_llm(
                    [
                        {"role": "system", "content": rewrite_system},
                        {"role": "user", "content": rewrite_user},
                    ],
                    temperature=0.1,
                    max_tokens=1400,
                )).strip()
                if rewritten_answer:
                    answer = rewritten_answer
            except Exception as _lang_rewrite_exc:
                logger.warning("Language rewrite failed: %s", _lang_rewrite_exc)

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
        model = result.routed_model or cfg.groq_model
        model_used = "system:market-data" if use_market_shortcut else f"multi-agent:cloud:{provider}:{model}"
        input_tokens = result.prompt_tokens
        output_tokens = result.completion_tokens
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
            "socratic_risk": (result.socratic_review or {}).get("risk_if_wrong"),
            "socratic_needs_clarification": bool((result.socratic_review or {}).get("needs_clarification")),
            "devil_advocate_severity": (result.devil_advocate_review or {}).get("severity"),
            "devil_advocate_revision_applied": bool(result.devil_revision_applied),
            "first_principle_causal_links": int((result.first_principle_analysis or {}).get("causal_links_count", 0)),
            "first_principle_root_hypotheses": int((result.first_principle_analysis or {}).get("root_hypotheses_count", 0)),
            "uncertainty_band": result.uncertainty_band,
            "uncertainty_score": result.uncertainty_score,
            "uncertainty_reasons": result.uncertainty_reasons,
        }

        intent_routing = result.intent_routing or {}
        if _platform_evaluate_handoff:
            should_handoff, handoff_reason, handoff_priority = _platform_evaluate_handoff(
                allow_human_handoff=intent_routing.get("allow_human_handoff", False),
                handoff_reason=intent_routing.get("reason") or result.escalation_reason,
                escalation_urgency=result.escalation_urgency,
                friction_points=result.friction_points,
            )
        else:
            should_handoff = bool(intent_routing.get("allow_human_handoff", False))
            handoff_reason = intent_routing.get("reason") or result.escalation_reason or "escalation_requested"
            handoff_priority = (result.escalation_urgency or "medium").lower()
        if should_handoff:
            handoff_message = result.escalation_message or (
                "Saya akan menghubungkan percakapan ini ke tim manusia agar dapat ditangani lebih lanjut."
            )
            if handoff_message.lower() not in answer.lower():
                answer = answer.rstrip() + "\n\n" + handoff_message
            if _platform_enqueue_handoff:
                try:
                    await _platform_enqueue_handoff(
                        pool, org_id=bot["org_id"], conversation_id=conv_id,
                        reason=handoff_reason, priority=handoff_priority,
                    )
                    asyncio.create_task(_dispatch_workflow_trigger(
                        "new_ticket",
                        {
                            "conversation_id": conv_id, "bot_id": bot_id,
                            "reason": handoff_reason, "priority": handoff_priority,
                            "end_user_id": user_meta.get("userId"), "end_user_name": user_meta.get("name"),
                            "end_user_email": user_meta.get("email"),
                        },
                        org_id=str(bot["org_id"]), bot_id=bot_id,
                    ))
                except Exception:
                    logger.exception("Gagal membuat human handoff conversation=%s", conv_id)
    except Exception as e:
        logger.exception("CHAT EXCEPTION bot=%s conv=%s: %s", bot_id, conv_id, e)
        if market_answer:
            answer = market_answer
            model_used = "system:market-data"
            input_tokens = 0
            output_tokens = 0
            latency_ms = int((time.monotonic() - t_start) * 1000)
            agent_meta = {"errors": [str(e)], "fallback": "market-data"}
        else:
            answer = (
                "Maaf, AI sedang mengalami kendala. Percakapan ini sudah diteruskan "
                "ke tim manusia agar tetap dapat ditangani."
            )
            model_used = "system:human-handoff"
            input_tokens = 0
            output_tokens = 0
            latency_ms = int((time.monotonic() - t_start) * 1000)
            agent_meta = {"errors": [str(e)], "handoff_reason": "ai_error"}
            if _platform_enqueue_handoff:
                try:
                    await _platform_enqueue_handoff(
                        pool, org_id=bot["org_id"], conversation_id=conv_id,
                        reason="ai_error", priority="high",
                    )
                    asyncio.create_task(_dispatch_workflow_trigger(
                        "new_ticket",
                        {
                            "conversation_id": conv_id, "bot_id": bot_id,
                            "reason": "ai_error", "priority": "high",
                            "end_user_id": user_meta.get("userId"), "end_user_name": user_meta.get("name"),
                            "end_user_email": user_meta.get("email"),
                        },
                        org_id=str(bot["org_id"]), bot_id=bot_id,
                    ))
                except Exception:
                    logger.exception("Gagal membuat error handoff conversation=%s", conv_id)

    # Additive routing fields dari Intent Router (backward-compatible di resp dict)
    router_intent         = intent_routing.get("intent", "general")
    router_selected_agent = intent_routing.get("selected_agent", "General AI Agent")
    router_confidence     = intent_routing.get("confidence", result.confidence if result else None)
    handoff_offered       = bool(should_handoff)
    sources = [
        {"document": c.get("filename") or c.get("file_name"), "chunk_index": c.get("chunk_index")}
        for c in relevant_chunks
        if c.get("filename") or c.get("file_name")
    ]
    follow_up_questions = (
        [result.suggested_followup] if result and result.suggested_followup else []
    )

    # 9. Simpan respons bot
    bot_msg_id = str(uuid.uuid4())
    chunk_ids  = [c["id"] for c in relevant_chunks]
    await pool.execute(
        """INSERT INTO messages
           (id, conversation_id, role, content, model, input_tokens, output_tokens, latency_ms,
            source_chunks, intent, selected_agent, routing_confidence, handoff_status, allow_human_handoff)
           VALUES ($1,$2,'assistant',$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)""",
        bot_msg_id, conv_id, answer,
        model_used,
        input_tokens, output_tokens, latency_ms,
        chunk_ids,
        router_intent, router_selected_agent, router_confidence,
        (handoff_reason if should_handoff else None),
        intent_routing.get("allow_human_handoff", False),
    )
    logger.info(
        "chat_routing org_id=%s bot_id=%s conv_id=%s intent=%s selected_agent=%s confidence=%s "
        "handoff_offered=%s latency_ms=%s",
        bot["org_id"], bot_id, conv_id, router_intent, router_selected_agent, router_confidence,
        handoff_offered, latency_ms,
    )

    # 10. Update stats
    await pool.execute(
        """UPDATE conversations SET msg_count=msg_count+2, last_msg_at=NOW() WHERE id=$1""",
        conv_id,
    )

    if agent_meta is not None and result is not None:
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

        asyncio.create_task(_dispatch_workflow_trigger(
            "message_received",
            {
                "conversation_id": conv_id, "bot_id": bot_id,
                "message": body.message, "answer": answer,
                "intent": result.intent, "confidence": result.confidence,
                "tags": result.topics,
                "customer_type": "new" if is_new_conversation else "returning",
                "end_user_id": user_meta.get("userId"), "end_user_name": user_meta.get("name"),
                "end_user_email": user_meta.get("email"),
            },
            org_id=str(bot["org_id"]), bot_id=bot_id,
        ))

    resp = {
        "answer":               answer,
        "session_id":           conv_id,
        "message_id":           bot_msg_id,
        "latency_ms":           latency_ms,
        "intent":               router_intent,
        "selected_agent":       router_selected_agent,
        "confidence":           router_confidence,
        "handoff_offered":      handoff_offered,
        "sources":              sources,
        "follow_up_questions":  follow_up_questions,
        "image_url":            chat_image_url,
        "image_provider":       chat_image_provider,
        "computer_agent_screenshot_url": chat_ca_screenshot_url,
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

    query_vec, query_model = await _generate_kb_embedding(q)
    query_tokens = _tokenize_text(q)
    scored: list[tuple[float, dict]] = []
    for row in rows:
        score = _score_kb_candidate(
            query_tokens, query_vec, row.get("content") or "", row.get("embedding"),
            query_model=query_model, chunk_model=row.get("model"),
        )
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

# Performance target dari spec: knowledge retrieval wajib < 500ms. Cuma
# di-log saat MELANGGAR target supaya tidak membanjiri log pada jalur cepat.
KB_RETRIEVAL_LATENCY_BUDGET_MS = 500


def _tokenize_text(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9_]+", (text or "").lower())
    return [t for t in tokens if len(t) >= 2]


def _chunk_text(text: str, size: int = 350) -> list[str]:
    words = (text or "").split()
    if not words:
        return []
    size = max(80, min(700, int(size)))
    return [" ".join(words[i:i + size]).strip() for i in range(0, len(words), size)]


async def _generate_kb_embedding(text: str, dim: int | None = None) -> tuple[list[float], str]:
    """Embedding semantik sungguhan: provider lokal (sentence-transformers,
    gratis, prioritas utama) -> OpenAI (cadangan, kalau lokal gagal load DAN
    OPENAI_API_KEY terisi) -> hash lokal (fallback terakhir kalau keduanya
    tidak tersedia). Model tag dikembalikan supaya _score_kb_candidate tahu
    kapan dua vektor sebanding (provider sama)."""
    dim = int(dim or cfg.kb_embedding_dim or KB_EMBED_DIM)

    vec = await kb_embeddings.generate_local_embedding(text)
    if vec is not None:
        return vec, kb_embeddings.LOCAL_EMBEDDING_TAG

    if cfg.openai_api_key:
        vec = await kb_embeddings.generate_openai_embedding(text, cfg.openai_api_key, dim)
        if vec is not None:
            return vec, kb_embeddings.OPENAI_EMBEDDING_TAG

    return _text_to_embedding(text, dim), f"hash-emb-{dim}"


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


def _score_kb_candidate(
    query_tokens: list[str],
    query_vec: list[float],
    content: str,
    embedding: object,
    *,
    query_model: str | None = None,
    chunk_model: str | None = None,
) -> float:
    content_lower = (content or "").lower()
    keyword_hits = sum(1 for t in query_tokens if t in content_lower)
    kw_score = keyword_hits / max(1, len(query_tokens))
    emb_score = 0.0
    # asyncpg tidak auto-decode kolom JSONB ke Python list — selalu balik
    # sebagai str mentah. Tanpa json.loads() di sini, scoring embedding
    # (bobot 78%) diam-diam tidak pernah jalan dan retrieval hanya
    # mengandalkan keyword match (22%).
    if isinstance(embedding, str):
        try:
            embedding = json.loads(embedding)
        except (TypeError, ValueError):
            embedding = None
    # Chunk lama (hash) dan baru (OpenAI) hidup di vector space berbeda
    # walau dimensinya sama — bandingkan model tag dulu, kalau beda jangan
    # hitung cosine similarity-nya (akan jadi angka tak bermakna), cukup
    # andalkan keyword match untuk baris itu sampai chunk-nya di-reindex.
    if isinstance(embedding, list) and (not query_model or not chunk_model or query_model == chunk_model):
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
    """Ambil teks halaman web untuk knowledge base. SSRF-safe: setiap URL
    (termasuk tujuan redirect) divalidasi via tool_registry._validate_url()
    (tolak host privat/loopback/link-local/metadata cloud) sebelum di-fetch
    — sebelumnya endpoint ini fetch URL apa pun yang dikirim tenant tanpa
    validasi sama sekali (follow_redirects=True tanpa cek ulang tujuan)."""
    url = (url or "").strip()
    if not url:
        return ""
    ok, _reason = tool_registry._validate_url(url)
    if not ok:
        return ""
    headers = {"User-Agent": "BotNesia/1.0 (+knowledge-base)"}
    async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=False, headers=headers) as client:
        try:
            current_url = url
            for _ in range(5):
                res = await client.get(current_url)
                if res.is_redirect:
                    location = res.headers.get("location")
                    if not location:
                        break
                    next_url = urllib.parse.urljoin(current_url, location)
                    ok, _reason = tool_registry._validate_url(next_url)
                    if not ok:
                        return ""
                    current_url = next_url
                    continue
                res.raise_for_status()
                text = _extract_web_text(res.text, max_chars=16000)
                if len(text) >= 300:
                    return text
                break
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
        embedding, model_tag = await _generate_kb_embedding(chunk_text)
        await conn.execute(
            """INSERT INTO doc_chunk_embeddings (chunk_id, org_id, embedding, model)
               VALUES ($1,$2,$3,$4)
               ON CONFLICT (chunk_id) DO UPDATE
               SET org_id=EXCLUDED.org_id,
                   embedding=EXCLUDED.embedding,
                   model=EXCLUDED.model""",
            chunk_id,
            org_id,
            json.dumps(embedding),  # asyncpg tidak auto-encode list -> JSONB
            model_tag,
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
               d.filename, d.source_type, d.source_url, e.embedding, e.model
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
        context += (
            "\n\nInstruksi knowledge-first: gunakan sumber knowledge di atas sebagai dasar utama. "
            "Jika sumber belum cukup, jawab best effort dan bedakan informasi dari knowledge dengan asumsi umum. "
            "Jangan langsung human handoff hanya karena sumber tidak lengkap; tanyakan klarifikasi jika perlu."
        )

    base = custom_prompt or (
        "Kamu adalah asisten AI yang helpful, sopan, dan profesional. "
        "Prioritaskan knowledge base tenant dan agent ini. Kalau konteks kurang lengkap, "
        "jawab best effort, minta klarifikasi bila perlu, dan baru tawarkan human handoff untuk kasus yang memang butuh tim manusia."
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
        "kabar",
        "terbaru",
        "terkini",
        "hari ini",
        "kemarin",
        "minggu ini",
        "bulan ini",
        "sekarang",
        "saat ini",
        "baru-baru ini",
        "breaking",
        "viral",
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
           WHERE c.bot_id=$1 AND c.org_id=$2 AND c.started_at >= $3""",
        bot_id, user["org_id"], since,
    )

    # Volume harian
    daily = await pool.fetch(
        """SELECT DATE(started_at) AS date, COUNT(*) AS convs
           FROM conversations WHERE bot_id=$1 AND org_id=$2 AND started_at >= $3
           GROUP BY DATE(started_at) ORDER BY date""",
        bot_id, user["org_id"], since,
    )

    # Top pertanyaan
    top_q = await pool.fetch(
        """SELECT m.content, COUNT(*) AS frequency
           FROM messages m
           JOIN conversations c ON c.id = m.conversation_id
           WHERE c.bot_id=$1 AND c.org_id=$2 AND m.role='user' AND m.created_at >= $3
           GROUP BY m.content ORDER BY frequency DESC LIMIT 10""",
        bot_id, user["org_id"], since,
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
        """SELECT m.id, m.role, m.content, m.model, m.latency_ms, m.created_at, m.source_chunks,
                  m.intent, m.selected_agent, m.routing_confidence, m.handoff_status, m.allow_human_handoff,
                  fr.rating AS feedback_rating, fr.comment AS feedback_comment
           FROM messages m
           LEFT JOIN feedback_records fr ON fr.message_id=m.id AND fr.tenant_id=$2
           WHERE m.conversation_id=$1 ORDER BY m.created_at""",
        conv_id, user["org_id"],
    )
    return [dict(r) for r in rows]


@app.get("/bots/{bot_id}/routing-logs")
async def get_routing_logs(
    bot_id: str,
    user=Depends(get_current_user),
    pool=Depends(get_pool),
    limit: int = 50,
    offset: int = 0,
):
    bot = await pool.fetchrow(
        "SELECT id FROM bots WHERE id=$1 AND org_id=$2",
        bot_id, user["org_id"],
    )
    if not bot:
        raise HTTPException(404, "Bot tidak ditemukan")
    rows = await pool.fetch(
        """SELECT m.id, m.conversation_id, m.content, m.intent, m.selected_agent,
                  m.routing_confidence, m.handoff_status, m.allow_human_handoff, m.created_at,
                  c.end_user_name, c.end_user_email
           FROM messages m
           JOIN conversations c ON c.id = m.conversation_id
           WHERE c.bot_id=$1 AND c.org_id=$2 AND m.role='assistant' AND m.intent IS NOT NULL
           ORDER BY m.created_at DESC LIMIT $3 OFFSET $4""",
        bot_id, user["org_id"], limit, offset,
    )
    return {"logs": [dict(r) for r in rows]}


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
    key_id  = str(uuid.uuid4())

    expires_at = None
    expires_in_days = body.get("expires_in_days")
    if expires_in_days is not None:
        try:
            expires_at = datetime.now(timezone.utc) + timedelta(days=max(1, int(expires_in_days)))
        except (TypeError, ValueError):
            raise HTTPException(400, "expires_in_days harus berupa angka")

    await pool.execute(
        """INSERT INTO api_keys (id, org_id, name, key_hash, key_prefix, expires_at)
           VALUES ($1,$2,$3,$4,$5,$6)""",
        key_id, user["org_id"],
        body.get("name", "API Key"),
        hash_password(raw_key), prefix, expires_at,
    )
    if _platform_write_audit:
        try:
            await _platform_write_audit(
                pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
                action="create", resource_type="api_key", resource_id=key_id,
                metadata={"name": body.get("name", "API Key"), "expires_at": expires_at.isoformat() if expires_at else None},
            )
        except Exception:
            pass

    return {
        "key":  raw_key,
        "key_id": key_id,
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
            "configured": bool(cfg.effective_gemini_api_key or cfg.groq_api_key),
            "primary_provider": "gemini" if cfg.effective_gemini_api_key else ("groq" if cfg.groq_api_key else None),
            "primary_model": cfg.gemini_model if cfg.effective_gemini_api_key else (cfg.groq_model if cfg.groq_api_key else None),
            "pro_model": cfg.gemini_pro_model if cfg.effective_gemini_api_key else None,
            "fallback_provider": "groq" if (cfg.effective_gemini_api_key and cfg.groq_api_key) else None,
            "fallback_model": cfg.groq_model if (cfg.effective_gemini_api_key and cfg.groq_api_key) else None,
        },
        "model": f"gemini:{cfg.gemini_model}" if cfg.effective_gemini_api_key else f"groq:{cfg.groq_model}",
        "version": "1.0.0",
    }


@app.get("/ready")
async def ready():
    """Liveness probe — process is running. Does not touch the DB."""
    return {"status": "ok"}


# ───────────────────────────────────────────────────────────────────────
# CASPER BLOCKCHAIN INTEGRATION — Casper Agentic Buildathon 2026
# Anchors AI session hashes to Casper Testnet so agent activity is
# permanently verifiable on-chain. Judges can look up the deploy_hash
# on https://testnet.cspr.live
# ───────────────────────────────────────────────────────────────────────
class CasperAnchorRequest(BaseModel):
    session_id: str
    summary: str = ""


@app.post("/api/casper/anchor")
async def casper_anchor(
    req: CasperAnchorRequest,
    user=Depends(get_current_user),
):
    """Submit a signed Casper deploy to store an AI session proof on Casper Testnet.
    Falls back to demo mode (deterministic hash, no real transaction) if the
    testnet is unreachable, pycspr is missing, or the account has no balance."""
    import hashlib, time as _time
    org_id = str(user["org_id"])

    # ── real mode ──────────────────────────────────────────────────────────
    try:
        import casper_anchor as _ca
        result = await _ca.anchor_session(
            org_id=org_id,
            session_id=req.session_id,
            summary=req.summary,
        )
        result.setdefault("proof_mode", "real")
        return result
    except Exception as exc:
        real_error = str(exc)
        logger.warning("casper_anchor real-mode failed (falling back to demo): %s", real_error)

    # ── demo fallback ──────────────────────────────────────────────────────
    # Always succeeds: deterministic proof without a live blockchain call.
    session_hash = hashlib.sha256(
        f"{org_id}:{req.session_id}:{req.summary}".encode()
    ).hexdigest()
    deploy_hash = "demo-" + hashlib.sha256(
        f"{session_hash}:{int(_time.time() // 60)}".encode()  # stable per minute
    ).hexdigest()[:56]
    CONTRACT_PKG = "897c4bd670325c1f17ab1704633a470f55eeeb1ec2b357ef48e5d26ecb78a9f0"
    return {
        "deploy_hash": deploy_hash,
        "session_hash": session_hash,
        "contract_package_hash": CONTRACT_PKG,
        "account_key": "demo-mode",
        "explorer_url": f"https://testnet.cspr.live/deploy/{deploy_hash}",
        "contract_url": f"https://testnet.cspr.live/contract-package/{CONTRACT_PKG}",
        "proof_mode": "demo",
        "real_mode_error": real_error[:200],
    }


# ═══════════════════════════════════════════════════════════════════════
# CASPER AGENTIC WORKFLOW — Buildathon 2026
# ═══════════════════════════════════════════════════════════════════════
try:
    from casper.workflow import build_router as _build_casper_router
    _casper_workflow_router = _build_casper_router(get_pool, get_current_user)
    app.include_router(_casper_workflow_router)
    logger.info("Casper Agentic Workflow routes mounted")
except Exception as _e:
    logger.warning("Casper workflow router skipped: %s", _e)


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
    from bn_platform.handoff import build_handoff_router, enqueue_handoff, evaluate_handoff_trigger
    from bn_platform.omnichannel import build_omnichannel_router
    from bn_platform.lead_engine import build_lead_router
    from bn_platform.marketplace import build_marketplace_router
    from bn_platform.revenue_intel import build_revenue_router
    from bn_platform.founder_os import build_founder_router
    from bn_platform.security import (
        build_security_router,
        write_audit_log as _platform_audit_log_fn,
        create_session as _platform_create_session_fn,
        touch_session as _platform_touch_session_fn,
        revoke_session as _platform_revoke_session_fn,
        _check_rate_limit as _platform_check_rate_limit_fn,
    )
    from bn_platform.observability import instrument_app, record_db_pool_stats
    from bn_platform.ai_observability import build_ai_observability_router
    from bn_platform.cost_intelligence import build_cost_intelligence_router
    from bn_platform.feedback_learning import build_feedback_learning_router
    from bn_platform.knowledge_builder import build_knowledge_builder_router
    from bn_platform.workflow_builder import build_workflow_builder_router
    from bn_platform.improvement_engine import build_improvement_router
    from bn_platform.finance import build_finance_router
    from bn_platform.marketing import build_marketing_router
    from bn_platform.hr import build_hr_router
    from bn_platform.operations import build_operations_router
    from bn_platform.executive import build_executive_router
    from bn_platform.workforce import build_workforce_router
    from bn_platform.research import build_research_router
    from bn_platform.computer_agent import build_computer_agent_router
    from bn_platform.channel_messaging import build_channel_messaging_router
    from bn_platform.execution_log import build_execution_log_router
    from bn_platform.agent_center import build_agent_center_router
    from bn_platform.self_learning import build_self_learning_router
    from bn_platform.system_health import build_system_health_router
    from bn_platform.meta_oauth import build_meta_oauth_router

    # ── 0. Set platform callbacks untuk Phase 1 endpoints ───────
    # (variabel sudah dideklarasikan di level modul — tidak perlu global keyword)
    _platform_check_limit = check_limit
    _platform_enqueue_handoff = enqueue_handoff
    _platform_evaluate_handoff = evaluate_handoff_trigger
    _platform_write_audit = _platform_audit_log_fn
    _platform_create_session = _platform_create_session_fn
    _platform_touch_session = _platform_touch_session_fn
    _platform_revoke_session = _platform_revoke_session_fn
    _platform_check_rate_limit = _platform_check_rate_limit_fn

    # ── 1. Prometheus middleware + GET /metrics ──────────────────
    instrument_app(app)

    # ── 2. RBAC require_permission dependency factory ────────────
    require_permission = make_permission_checker(
        get_current_user=get_current_user, get_pool=get_pool,
    )
    _platform_require_permission = require_permission

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
        user_meta = {"userId": external_user_id, "name": display_name, "_channel": channel}
        req = ChatReq(message=text, session_id=session_id, user_meta=user_meta)
        try:
            resp = await chat(bot_id=bot_id, body=req, pool=pool)
            return (resp.get("answer") if isinstance(resp, dict) else None) or ""
        except Exception:
            logger.exception("Route inbound platform message failed (org=%s bot=%s channel=%s)", org_id, bot_id, channel)
            return "Maaf, terjadi kesalahan. Tim kami sudah diberitahu."

    _platform_route_inbound = _route_inbound_platform_message

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
        build_meta_oauth_router(
            get_pool=get_pool, get_current_user=get_current_user,
            require_permission=require_permission,
            route_inbound_message=_route_inbound_platform_message,
        ),
        prefix="/api",
    )
    app.include_router(
        build_lead_router(
            get_pool=get_pool, get_current_user=get_current_user,
            require_permission=require_permission,
            on_new_lead=_on_new_lead_workflow_trigger,
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
        build_founder_router(get_pool=get_pool, get_current_user=get_current_user),
        prefix="/api",
    )
    app.include_router(
        build_security_router(
            get_pool=get_pool, get_current_user=get_current_user,
            require_permission=require_permission,
            hash_password=hash_password,
            get_agent_config=get_workflow_agent_config,
        ),
        prefix="/api",
    )
    app.include_router(
        build_ai_observability_router(
            get_pool=get_pool, get_current_user=get_current_user,
        ),
        prefix="/api",
    )
    app.include_router(
        build_cost_intelligence_router(
            get_pool=get_pool, get_current_user=get_current_user,
        ),
        prefix="/api",
    )
    app.include_router(
        build_feedback_learning_router(
            get_pool=get_pool, get_current_user=get_current_user,
        ),
        prefix="/api",
    )
    app.include_router(
        build_knowledge_builder_router(
            get_pool=get_pool, get_current_user=get_current_user,
            run_pipeline=_run_knowledge_builder_pipeline,
            store_chunk_embeddings=_store_chunk_embeddings,
        ),
        prefix="/api",
    )
    app.include_router(
        build_workflow_builder_router(
            get_pool=get_pool, get_current_user=get_current_user,
            get_agent_config=get_workflow_agent_config,
            require_permission=require_permission,
            enqueue_handoff_fn=_platform_enqueue_handoff,
        ),
        prefix="/api",
    )
    app.include_router(
        build_improvement_router(
            get_pool=get_pool, get_current_user=get_current_user,
            require_permission=require_permission,
        ),
        prefix="/api",
    )
    app.include_router(
        build_finance_router(
            get_pool=get_pool, get_current_user=get_current_user,
            require_permission=require_permission,
            get_agent_config=get_workflow_agent_config,
        ),
        prefix="/api",
    )
    app.include_router(
        build_marketing_router(
            get_pool=get_pool, get_current_user=get_current_user,
            require_permission=require_permission,
            get_agent_config=get_workflow_agent_config,
        ),
        prefix="/api",
    )
    app.include_router(
        build_hr_router(
            get_pool=get_pool, get_current_user=get_current_user,
            require_permission=require_permission,
            get_agent_config=get_workflow_agent_config,
        ),
        prefix="/api",
    )
    app.include_router(
        build_operations_router(
            get_pool=get_pool, get_current_user=get_current_user,
            require_permission=require_permission,
            get_agent_config=get_workflow_agent_config,
        ),
        prefix="/api",
    )
    app.include_router(
        build_executive_router(
            get_pool=get_pool, get_current_user=get_current_user,
            require_permission=require_permission,
            get_agent_config=get_workflow_agent_config,
        ),
        prefix="/api",
    )
    app.include_router(
        build_workforce_router(
            get_pool=get_pool, get_current_user=get_current_user,
            require_permission=require_permission,
            get_agent_config=get_workflow_agent_config,
        ),
        prefix="/api",
    )
    app.include_router(
        build_self_learning_router(
            get_pool=get_pool, get_current_user=get_current_user,
            require_permission=require_permission,
            get_agent_config=get_workflow_agent_config,
        ),
        prefix="/api",
    )
    app.include_router(
        build_research_router(
            get_pool=get_pool, get_current_user=get_current_user,
            require_permission=require_permission,
            get_agent_config=get_workflow_agent_config,
        ),
        prefix="/api",
    )
    app.include_router(
        build_computer_agent_router(
            get_pool=get_pool, get_current_user=get_current_user,
            require_permission=require_permission,
            get_agent_config=get_workflow_agent_config,
        ),
        prefix="/api",
    )
    app.include_router(
        build_channel_messaging_router(
            get_pool=get_pool, get_current_user=get_current_user,
            require_permission=require_permission,
            app_url=cfg.app_url,
        ),
        prefix="/api",
    )
    app.include_router(
        build_execution_log_router(
            get_pool=get_pool, get_current_user=get_current_user,
            require_permission=require_permission,
            get_agent_config=get_workflow_agent_config,
        ),
        prefix="/api",
    )
    app.include_router(
        build_agent_center_router(
            get_pool=get_pool, get_current_user=get_current_user,
            require_permission=require_permission,
            get_agent_config=get_workflow_agent_config,
        ),
        prefix="/api",
    )
    app.include_router(
        build_system_health_router(
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
