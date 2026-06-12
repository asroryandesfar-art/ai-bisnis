"""
intelligence/config.py — Pengaturan modul Intelligence Platform.

Mengikuti pola Settings di agent_api.py (pydantic-settings, baca dari .env).
Semua key baru bersifat opsional dengan default aman, supaya modul ini
bisa "menumpang" di proses agent_api.py tanpa perlu .env baru.
"""
from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class IntelligenceSettings(BaseSettings):
    # Database (default: pakai DATABASE_URL yang sama dengan BotNesia/agent_api)
    database_url: str = os.environ.get("DATABASE_URL", "postgresql://user:pass@localhost/botnesia")

    # LLM (dipakai untuk ringkasan percakapan & ekstraksi sales signal) —
    # sengaja membaca env var yang sama dengan agent_api.Settings supaya satu sumber konfigurasi.
    groq_api_key:  str = os.environ.get("GROQ_API_KEY", "")
    groq_model:    str = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    groq_base_url: str = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

    # Redis — broker Celery + cache agregasi dashboard
    redis_url: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    # Embedding — default memakai generator lokal (gratis, deterministik, lihat embeddings.py).
    # Ganti ke "external" + isi embedding_api_url/embedding_api_key untuk pakai
    # provider seperti OpenAI/Cohere tanpa mengubah kode lain (lihat embeddings.py).
    embedding_provider: str = os.environ.get("EMBEDDING_PROVIDER", "local")
    embedding_dim:      int = int(os.environ.get("EMBEDDING_DIM", "384"))
    embedding_api_url:  str = os.environ.get("EMBEDDING_API_URL", "")
    embedding_api_key:  str = os.environ.get("EMBEDDING_API_KEY", "")
    embedding_model:    str = os.environ.get("EMBEDDING_MODEL", "local-hash-384")

    # FAQ Engine — ambang batas clustering
    faq_similarity_threshold: float = float(os.environ.get("FAQ_SIMILARITY_THRESHOLD", "0.84"))
    faq_min_cluster_size:     int   = int(os.environ.get("FAQ_MIN_CLUSTER_SIZE", "3"))

    # Sales Intelligence — ambang batas pengelompokan pola
    sales_pattern_similarity_threshold: float = float(os.environ.get("SALES_PATTERN_SIMILARITY_THRESHOLD", "0.80"))

    # Auto Learning — jadwal job malam (UTC hour:minute, dipakai celery_app beat schedule)
    nightly_job_hour:   int = int(os.environ.get("NIGHTLY_JOB_HOUR", "19"))    # 19:00 UTC ≈ 02:00 WIB
    nightly_job_minute: int = int(os.environ.get("NIGHTLY_JOB_MINUTE", "0"))

    # Shared secret (dipakai ulang dari agent_api agar satu sumber otorisasi)
    agent_secret: str = os.environ.get("AGENT_SECRET", "")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


cfg = IntelligenceSettings()
