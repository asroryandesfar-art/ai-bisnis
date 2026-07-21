"""platform_state.base — kontrak `StateStore` (async, lintas-worker).

Abstraksi shared-state BotNesia. DUA backend berbagi kontrak identik:
  - InProcessStateStore  (default; perilaku sekarang, per-proses)  → `inprocess.py`
  - RedisStateStore      (opt-in; lintas-worker)                    → ditambahkan di C2

Modul ini MANDIRI: tidak mengimpor `main`/`bn_platform`/`ai_providers` supaya
bisa diuji tanpa boot aplikasi dan dipakai ulang oleh worker Celery.

Semantik `rate_incr` sengaja meniru `bn_platform.security._check_rate_limit`
(sliding-window log; slot TIDAK dikonsumsi saat request ditolak) agar migrasi
rate-limiter bersifat behavior-preserving.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class StateStore(ABC):
    """Antarmuka penyimpanan state bersama. Semua operasi async; implementasi
    wajib atomik untuk `incr`, `rate_incr`, `acquire_lock`, `release_lock`."""

    # ── key / value ──────────────────────────────────────────────────────
    @abstractmethod
    async def get(self, key: str) -> str | None: ...

    @abstractmethod
    async def set(self, key: str, value: str, *, ttl_s: int | None = None) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def incr(self, key: str, *, amount: int = 1, ttl_s: int | None = None) -> int:
        """Increment atomik; set TTL hanya saat key pertama kali dibuat."""

    # ── hash (dipakai circuit-breaker: {fails, open_until}) ───────────────
    @abstractmethod
    async def hset(self, key: str, field: str, value: str, *, ttl_s: int | None = None) -> None: ...

    @abstractmethod
    async def hget(self, key: str, field: str) -> str | None: ...

    @abstractmethod
    async def hgetall(self, key: str) -> dict[str, str]: ...

    # ── list (dipakai working-memory STM buffer) ──────────────────────────
    @abstractmethod
    async def lpush_trim(self, key: str, value: str, *, maxlen: int, ttl_s: int | None = None) -> None:
        """Dorong ke kepala list lalu pangkas ke `maxlen` item terbaru."""

    @abstractmethod
    async def lrange(self, key: str, start: int = 0, stop: int = -1) -> list[str]:
        """Ambil rentang list (semantik Redis: `stop=-1` = seluruh list, inklusif)."""

    # ── rate limit (atomic sliding-window log) ────────────────────────────
    @abstractmethod
    async def rate_incr(self, key: str, *, window_s: int, limit: int) -> tuple[bool, int]:
        """Return `(allowed, count_in_window)`. Bila `allowed` False, slot TIDAK
        dikonsumsi (meniru `_check_rate_limit` lama). Wajib atomik."""

    # ── distributed lock (SET NX PX + token) ──────────────────────────────
    @abstractmethod
    async def acquire_lock(self, key: str, *, ttl_s: int, token: str) -> bool:
        """True bila lock berhasil diambil (belum ada / sudah kadaluarsa)."""

    @abstractmethod
    async def release_lock(self, key: str, *, token: str) -> bool:
        """Lepas lock HANYA bila `token` cocok (cegah lepas milik orang lain)."""

    # ── health ────────────────────────────────────────────────────────────
    @abstractmethod
    async def healthcheck(self) -> bool: ...
