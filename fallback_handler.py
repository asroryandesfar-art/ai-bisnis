"""
fallback_handler.py — Fallback Handler
Menangani kegagalan agen secara graceful dengan strategi bertingkat.

Strategi fallback (urutan prioritas):
  1. Retry          — coba ulang dengan delay exponential
  2. Model fallback — ganti ke model yang lebih murah/stabil
  3. Agent fallback — ganti ke agen cadangan yang lebih sederhana
  4. Cache          — pakai jawaban cache dari pertanyaan serupa
  5. Template       — pakai template respons statis
  6. Hardcoded      — respons default terakhir sebelum error

Setiap kegagalan dicatat untuk monitoring dan alert otomatis.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable


# ─── ENUMS & DATA CLASSES ─────────────────────────────────────

class FallbackStrategy(Enum):
    RETRY           = "retry"
    MODEL_FALLBACK  = "model_fallback"
    AGENT_FALLBACK  = "agent_fallback"
    CACHE           = "cache"
    TEMPLATE        = "template"
    HARDCODED       = "hardcoded"


class FailureType(Enum):
    TIMEOUT         = "timeout"
    API_ERROR       = "api_error"
    RATE_LIMITED    = "rate_limited"
    INVALID_OUTPUT  = "invalid_output"
    NETWORK_ERROR   = "network_error"
    UNKNOWN         = "unknown"


@dataclass
class FallbackResult:
    success:          bool
    response:         str
    strategy_used:    FallbackStrategy
    original_error:   str
    attempts:         int
    latency_ms:       int
    from_cache:       bool = False
    degraded:         bool = False   # True = berhasil tapi kualitas mungkin lebih rendah


@dataclass
class FailureRecord:
    agent:        str
    failure_type: FailureType
    error:        str
    context_hash: str
    ts:           str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    recovered:    bool = False
    strategy:     str = ""


# ─── RESPONSE CACHE ───────────────────────────────────────────

class ResponseCache:
    """
    Cache sederhana untuk respons LLM.
    Key: hash dari (bot_id + pertanyaan yang dinormalisasi).
    Di production: ganti dengan Redis + TTL.
    """

    def __init__(self, max_size: int = 500, ttl_seconds: int = 3600):
        self._store:      dict[str, dict] = {}
        self._access_log: dict[str, int]  = {}
        self.max_size    = max_size
        self.ttl_seconds = ttl_seconds

    def _key(self, bot_id: str, question: str) -> str:
        normalized = " ".join(question.lower().split())[:200]
        return hashlib.md5(f"{bot_id}:{normalized}".encode()).hexdigest()

    def get(self, bot_id: str, question: str) -> str | None:
        key   = self._key(bot_id, question)
        entry = self._store.get(key)
        if not entry:
            return None
        # Cek TTL
        age = time.time() - entry["stored_at"]
        if age > self.ttl_seconds:
            del self._store[key]
            return None
        self._access_log[key] = self._access_log.get(key, 0) + 1
        return entry["response"]

    def set(self, bot_id: str, question: str, response: str, confidence: float = 1.0):
        if confidence < 0.7:
            return  # Jangan cache jawaban yang kurang yakin
        key = self._key(bot_id, question)
        # Evict jika penuh — hapus yang paling jarang diakses
        if len(self._store) >= self.max_size:
            lru = min(self._access_log, key=self._access_log.get, default=None)
            if lru and lru in self._store:
                del self._store[lru]
                del self._access_log[lru]
        self._store[key] = {
            "response":   response,
            "stored_at":  time.time(),
            "bot_id":     bot_id,
            "confidence": confidence,
        }

    def stats(self) -> dict:
        total     = len(self._store)
        total_hits = sum(self._access_log.values())
        return {"cached_responses": total, "total_hits": total_hits}


# ─── TEMPLATE ENGINE ──────────────────────────────────────────

RESPONSE_TEMPLATES: dict[str, list[str]] = {
    "default": [
        "Maaf, saya sedang mengalami gangguan sementara. Silakan coba lagi dalam beberapa saat.",
        "Sistem kami sedang dalam pemeliharaan singkat. Terima kasih atas kesabaran Anda.",
    ],
    "timeout": [
        "Permintaan Anda membutuhkan waktu lebih lama dari biasanya. Silakan ulangi pertanyaan Anda.",
        "Maaf, respons terlambat. Coba tanyakan kembali dan saya akan segera membantu.",
    ],
    "rate_limited": [
        "Maaf, banyak permintaan masuk sekarang. Silakan tunggu sebentar dan coba lagi.",
        "Sistem sedang ramai. Pertanyaan Anda akan diproses segera — mohon sabar.",
    ],
    "api_error": [
        "Terjadi gangguan teknis sementara. Tim kami sudah diberitahu dan sedang menangani.",
        "Maaf atas ketidaknyamanan ini. Silakan hubungi tim kami jika masalah berlanjut.",
    ],
    "escalation_needed": [
        "Pertanyaan Anda membutuhkan penanganan khusus. Saya akan sambungkan dengan tim kami segera.",
        "Untuk masalah ini, tim CS kami yang berpengalaman akan membantu Anda lebih baik.",
    ],
    "greeting": [
        "Halo! Saya siap membantu Anda. Ada yang bisa saya bantu?",
        "Selamat datang! Ada pertanyaan apa yang bisa saya jawab untuk Anda?",
    ],
}

_template_index: dict[str, int] = defaultdict(int)

def get_template(template_key: str, bot_id: str = "") -> str:
    """Ambil template dengan rotasi untuk variasi."""
    templates = RESPONSE_TEMPLATES.get(template_key, RESPONSE_TEMPLATES["default"])
    key       = f"{bot_id}:{template_key}"
    idx       = _template_index[key] % len(templates)
    _template_index[key] += 1
    return templates[idx]


# ─── FALLBACK HANDLER ─────────────────────────────────────────

class FallbackHandler:
    """
    Handler terpusat untuk semua kegagalan di sistem multi-agent.

    Alur per kegagalan:
      error → classify → pilih strategi → eksekusi → log → return
    """

    # Model fallback chain: dari paling canggih ke paling ringan
    MODEL_CHAIN = [
        "anthropic/claude-sonnet-4-5",
        "anthropic/claude-haiku-4-5",
        "groq/llama-3.3-70b-versatile",
        "google/gemini-2.0-flash-001",
        "meta-llama/llama-3.1-8b-instruct",
    ]

    def __init__(
        self,
        primary_model:  str   = "anthropic/claude-sonnet-4-5",
        max_retries:    int   = 3,
        base_delay_s:   float = 1.0,
        cache:          ResponseCache | None = None,
    ):
        self.primary_model = primary_model
        self.max_retries   = max_retries
        self.base_delay_s  = base_delay_s
        self.cache         = cache or ResponseCache()
        self._failure_log: list[FailureRecord] = []
        self._circuit_breakers: dict[str, dict] = {}  # agent → state

    # ── CIRCUIT BREAKER ─────────────────────────────────────────

    def _is_circuit_open(self, agent: str) -> bool:
        """Circuit breaker: buka sirkuit jika agen terlalu sering gagal."""
        cb = self._circuit_breakers.get(agent)
        if not cb:
            return False
        if cb["state"] == "open":
            # Auto-close setelah 60 detik
            if time.time() - cb["opened_at"] > 60:
                cb["state"]      = "half-open"
                cb["fail_count"] = 0
                return False
            return True
        return False

    def _record_failure_cb(self, agent: str):
        """Catat kegagalan ke circuit breaker."""
        cb = self._circuit_breakers.setdefault(agent, {
            "state": "closed", "fail_count": 0, "opened_at": 0
        })
        cb["fail_count"] += 1
        if cb["fail_count"] >= 5:  # Buka setelah 5 kegagalan berturut
            cb["state"]     = "open"
            cb["opened_at"] = time.time()
            print(f"[Fallback] Circuit OPEN untuk '{agent}' — terlalu banyak kegagalan")

    def _record_success_cb(self, agent: str):
        cb = self._circuit_breakers.get(agent)
        if cb:
            cb["state"]      = "closed"
            cb["fail_count"] = 0

    # ── FAILURE CLASSIFIER ──────────────────────────────────────

    def _classify(self, error: str) -> FailureType:
        error_lower = error.lower()
        if any(k in error_lower for k in ["timeout", "timed out", "time out"]):
            return FailureType.TIMEOUT
        if any(k in error_lower for k in ["429", "rate limit", "too many"]):
            return FailureType.RATE_LIMITED
        if any(k in error_lower for k in ["network", "connection", "connect", "unreachable"]):
            return FailureType.NETWORK_ERROR
        if any(k in error_lower for k in ["500", "502", "503", "504", "server error"]):
            return FailureType.API_ERROR
        if any(k in error_lower for k in ["json", "parse", "invalid", "format"]):
            return FailureType.INVALID_OUTPUT
        return FailureType.UNKNOWN

    # ── RETRY WITH EXPONENTIAL BACKOFF ──────────────────────────

    async def with_retry(
        self,
        fn:      Callable,
        context: dict = None,
        agent:   str  = "unknown",
    ) -> tuple[Any, int]:
        """
        Jalankan fn dengan retry exponential backoff.
        Return: (result, attempts)
        """
        context = context or {}
        last_error = ""

        for attempt in range(1, self.max_retries + 1):
            try:
                if self._is_circuit_open(agent):
                    raise RuntimeError(f"Circuit open untuk {agent}")

                result = await fn()
                self._record_success_cb(agent)
                return result, attempt

            except Exception as e:
                last_error = str(e)
                self._record_failure_cb(agent)

                if attempt < self.max_retries:
                    delay = self.base_delay_s * (2 ** (attempt - 1))  # 1s, 2s, 4s
                    print(f"[Fallback] Retry {attempt}/{self.max_retries} untuk '{agent}' "
                          f"dalam {delay:.1f}s — {last_error[:80]}")
                    await asyncio.sleep(delay)

        raise RuntimeError(f"Semua {self.max_retries} retry gagal: {last_error}")

    # ── MODEL FALLBACK ──────────────────────────────────────────

    async def with_model_fallback(
        self,
        fn_factory: Callable[[str], Callable],
        current_model: str,
        agent: str = "unknown",
    ) -> tuple[Any, str]:
        """
        Coba model utama, jika gagal turun ke model berikutnya.
        fn_factory(model) → coroutine yang bisa dijalankan.
        Return: (result, model_yang_berhasil)
        """
        chain = [current_model] + [
            m for m in self.MODEL_CHAIN if m != current_model
        ]

        for model in chain:
            try:
                print(f"[Fallback] Mencoba model: {model}")
                result = await fn_factory(model)()
                if model != current_model:
                    print(f"[Fallback] Model fallback berhasil: {model}")
                return result, model
            except Exception as e:
                print(f"[Fallback] Model {model} gagal: {e}")
                if model == chain[-1]:
                    raise

        raise RuntimeError("Semua model dalam chain gagal")

    # ── MAIN HANDLER ────────────────────────────────────────────

    async def handle(
        self,
        error:   str,
        context: dict,
        agent:   str = "unknown",
        fn:      Callable | None = None,
    ) -> FallbackResult:
        """
        Entry point utama untuk semua kegagalan.
        Coba strategi satu per satu sampai ada yang berhasil.
        """
        t_start      = time.monotonic()
        failure_type = self._classify(error)
        bot_id       = context.get("bot_id", "")
        user_msg     = context.get("user_message", "")
        attempts     = 0

        # Log kegagalan
        self._failure_log.append(FailureRecord(
            agent        = agent,
            failure_type = failure_type,
            error        = error[:300],
            context_hash = hashlib.md5(user_msg[:100].encode()).hexdigest(),
        ))
        if len(self._failure_log) > 2000:
            self._failure_log = self._failure_log[-2000:]

        # ── Strategi 1: Cache ──────────────────────────────────
        if user_msg and bot_id:
            cached = self.cache.get(bot_id, user_msg)
            if cached:
                print(f"[Fallback] Cache hit untuk bot={bot_id}")
                return FallbackResult(
                    success        = True,
                    response       = cached,
                    strategy_used  = FallbackStrategy.CACHE,
                    original_error = error,
                    attempts       = 0,
                    latency_ms     = int((time.monotonic() - t_start) * 1000),
                    from_cache     = True,
                    degraded       = False,
                )

        # ── Strategi 2: Retry (jika fn tersedia) ──────────────
        if fn and failure_type not in (FailureType.RATE_LIMITED,):
            try:
                result, attempts = await self.with_retry(fn, context, agent)
                latency_ms = int((time.monotonic() - t_start) * 1000)
                # Simpan ke cache
                if hasattr(result, "output") and result.output.get("answer"):
                    self.cache.set(
                        bot_id, user_msg,
                        result.output["answer"],
                        result.output.get("confidence", 0.8),
                    )
                return FallbackResult(
                    success        = True,
                    response       = result.output.get("answer", ""),
                    strategy_used  = FallbackStrategy.RETRY,
                    original_error = error,
                    attempts       = attempts,
                    latency_ms     = latency_ms,
                    degraded       = False,
                )
            except Exception as retry_err:
                print(f"[Fallback] Retry gagal: {retry_err}")

        # ── Strategi 3: Template ───────────────────────────────
        template_key = {
            FailureType.TIMEOUT:      "timeout",
            FailureType.RATE_LIMITED: "rate_limited",
            FailureType.API_ERROR:    "api_error",
        }.get(failure_type, "default")

        template_response = get_template(template_key, bot_id)

        record = next(
            (r for r in reversed(self._failure_log) if r.context_hash ==
             hashlib.md5(user_msg[:100].encode()).hexdigest()),
            None,
        )
        if record:
            record.recovered = True
            record.strategy  = FallbackStrategy.TEMPLATE.value

        return FallbackResult(
            success        = True,
            response       = template_response,
            strategy_used  = FallbackStrategy.TEMPLATE,
            original_error = error,
            attempts       = attempts,
            latency_ms     = int((time.monotonic() - t_start) * 1000),
            degraded       = True,
        )

    # ── MONITORING ──────────────────────────────────────────────

    def failure_stats(self, agent: str | None = None) -> dict:
        logs = self._failure_log if not agent else [
            r for r in self._failure_log if r.agent == agent
        ]
        total     = len(logs)
        recovered = sum(1 for r in logs if r.recovered)
        by_type: dict[str, int] = {}
        for r in logs:
            k = r.failure_type.value
            by_type[k] = by_type.get(k, 0) + 1

        cb_status = {
            ag: cb["state"]
            for ag, cb in self._circuit_breakers.items()
        }

        return {
            "total_failures":    total,
            "recovered":         recovered,
            "recovery_rate":     round(recovered / total, 3) if total else 0,
            "by_type":           by_type,
            "circuit_breakers":  cb_status,
            "cache_stats":       self.cache.stats(),
        }

    def recent_failures(self, limit: int = 20) -> list[dict]:
        return [
            {
                "agent":        r.agent,
                "failure_type": r.failure_type.value,
                "error":        r.error,
                "ts":           r.ts,
                "recovered":    r.recovered,
                "strategy":     r.strategy,
            }
            for r in self._failure_log[-limit:]
        ]


# ─── SINGLETON ────────────────────────────────────────────────

_global_fallback: FallbackHandler | None = None

def get_fallback_handler(primary_model: str = "anthropic/claude-sonnet-4-5") -> FallbackHandler:
    global _global_fallback
    if _global_fallback is None:
        _global_fallback = FallbackHandler(primary_model=primary_model)
    return _global_fallback
