"""
rate_limiter.py — Rate Limiter
Multi-layer rate limiting untuk melindungi sistem dan API.

Layer yang dilindungi:
  1. Per end-user    — batasi spam dari satu pelanggan
  2. Per bot         — batasi total request ke satu bot
  3. Per org         — batasi sesuai plan (starter/growth/scale)
  4. Per agent       — batasi call ke setiap LLM agent
  5. Global          — batas total sistem

Algoritma: Token Bucket + Sliding Window
  - Token Bucket  → burst handling (trafik lonjakan singkat diizinkan)
  - Sliding Window → average rate enforcement (rata-rata jangka panjang)

Di production: ganti _store dengan Redis untuk multi-instance.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ─── ENUMS ────────────────────────────────────────────────────

class LimitStatus(Enum):
    ALLOWED  = "allowed"
    THROTTLED = "throttled"   # boleh lanjut tapi diperlambat
    BLOCKED  = "blocked"      # ditolak sepenuhnya


class PlanTier(Enum):
    STARTER = "starter"
    GROWTH  = "growth"
    SCALE   = "scale"


# ─── DATA CLASSES ─────────────────────────────────────────────

@dataclass
class RateLimit:
    """Konfigurasi limit untuk satu layer."""
    requests_per_minute: int
    requests_per_hour:   int
    requests_per_day:    int
    burst_allowance:     int   = 5    # extra requests yang diizinkan sesekali
    cooldown_seconds:    int   = 60   # waktu tunggu setelah blocked


@dataclass
class CheckResult:
    """Hasil pengecekan rate limit."""
    status:        LimitStatus
    layer:         str           # layer mana yang trigger
    key:           str           # key yang kena limit
    limit:         RateLimit | None
    current_rpm:   int = 0       # current requests per minute
    retry_after_s: int = 0       # berapa detik sebelum bisa coba lagi
    message:       str = ""


# ─── PLAN LIMITS ──────────────────────────────────────────────

PLAN_LIMITS: dict[str, RateLimit] = {
    PlanTier.STARTER.value: RateLimit(
        requests_per_minute = 10,
        requests_per_hour   = 200,
        requests_per_day    = 500,
        burst_allowance     = 3,
        cooldown_seconds    = 60,
    ),
    PlanTier.GROWTH.value: RateLimit(
        requests_per_minute = 60,
        requests_per_hour   = 2000,
        requests_per_day    = 5000,
        burst_allowance     = 15,
        cooldown_seconds    = 30,
    ),
    PlanTier.SCALE.value: RateLimit(
        requests_per_minute = 300,
        requests_per_hour   = 10000,
        requests_per_day    = 25000,
        burst_allowance     = 50,
        cooldown_seconds    = 10,
    ),
}

# Limit per end-user (independen dari plan)
USER_LIMITS = RateLimit(
    requests_per_minute = 5,
    requests_per_hour   = 50,
    requests_per_day    = 200,
    burst_allowance     = 2,
    cooldown_seconds    = 30,
)

# Limit per LLM agent call (lindungi budget API)
AGENT_LIMITS: dict[str, RateLimit] = {
    "cs_agent":        RateLimit(300, 5000, 20000, burst_allowance=20),
    "escalation_agent": RateLimit(300, 5000, 20000, burst_allowance=20),
    "analytics_agent": RateLimit(200, 3000, 10000, burst_allowance=10),
    "trainer_agent":   RateLimit(100, 1000, 5000,  burst_allowance=5),
    "memory_agent":    RateLimit(200, 4000, 15000, burst_allowance=15),
    "supervisor":      RateLimit(300, 5000, 20000, burst_allowance=20),
}

# Global system limit
GLOBAL_LIMIT = RateLimit(
    requests_per_minute = 1000,
    requests_per_hour   = 30000,
    requests_per_day    = 200000,
    burst_allowance     = 100,
)


# ─── TOKEN BUCKET ─────────────────────────────────────────────

class TokenBucket:
    """
    Token Bucket untuk burst handling.
    Token diisi ulang secara bertahap.
    """

    def __init__(self, capacity: int, refill_rate: float):
        """
        capacity:    max token yang bisa ditampung
        refill_rate: token yang ditambahkan per detik
        """
        self.capacity     = capacity
        self.refill_rate  = refill_rate
        self.tokens       = float(capacity)
        self.last_refill  = time.monotonic()
        self._lock        = asyncio.Lock()

    async def consume(self, tokens: int = 1) -> bool:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            refill  = elapsed * self.refill_rate
            self.tokens = min(self.capacity, self.tokens + refill)
            self.last_refill = now

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def wait_time(self) -> float:
        """Berapa detik sampai ada token tersedia."""
        deficit = max(0, 1.0 - self.tokens)
        return deficit / self.refill_rate if self.refill_rate > 0 else 999


# ─── SLIDING WINDOW COUNTER ───────────────────────────────────

class SlidingWindowCounter:
    """
    Sliding window counter menggunakan deque timestamps.
    Memory-efficient untuk request rate tracking.
    """

    def __init__(self):
        self._timestamps: deque = deque()

    def add(self, now: float = None):
        ts = now or time.monotonic()
        self._timestamps.append(ts)

    def count_in_window(self, window_seconds: int, now: float = None) -> int:
        ts = now or time.monotonic()
        cutoff = ts - window_seconds
        # Buang timestamps lama
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
        return len(self._timestamps)

    def last_request_at(self) -> float | None:
        return self._timestamps[-1] if self._timestamps else None


# ─── RATE LIMITER ─────────────────────────────────────────────

class RateLimiter:
    """
    Multi-layer rate limiter.
    Check semua layer sekaligus, return layer pertama yang kena limit.
    """

    def __init__(self):
        # Sliding window counters: key → SlidingWindowCounter
        self._windows:  dict[str, SlidingWindowCounter] = defaultdict(SlidingWindowCounter)
        # Token buckets: key → TokenBucket
        self._buckets:  dict[str, TokenBucket] = {}
        # Blocked keys dan kapan bisa buka lagi
        self._blocked:  dict[str, float] = {}
        # Audit log
        self._log:      list[dict] = []
        self._lock = asyncio.Lock()

    def _get_bucket(self, key: str, limit: RateLimit) -> TokenBucket:
        if key not in self._buckets:
            self._buckets[key] = TokenBucket(
                capacity    = limit.requests_per_minute + limit.burst_allowance,
                refill_rate = limit.requests_per_minute / 60.0,
            )
        return self._buckets[key]

    async def check(
        self,
        user_id: str  = "anonymous",
        bot_id:  str  = "",
        org_id:  str  = "",
        plan:    str  = "starter",
        agent:   str  = "",
    ) -> CheckResult:
        """
        Cek semua layer rate limit sebelum memproses request.
        Return CheckResult — status ALLOWED, THROTTLED, atau BLOCKED.
        """
        now = time.monotonic()

        # ── Layer 1: Cek apakah sedang dalam cooldown ──────────
        for key in [f"user:{user_id}", f"bot:{bot_id}", f"org:{org_id}"]:
            if key in self._blocked:
                if now < self._blocked[key]:
                    retry_after = int(self._blocked[key] - now) + 1
                    return CheckResult(
                        status        = LimitStatus.BLOCKED,
                        layer         = key.split(":")[0],
                        key           = key,
                        limit         = None,
                        retry_after_s = retry_after,
                        message       = f"Terlalu banyak request. Coba lagi dalam {retry_after} detik.",
                    )
                else:
                    del self._blocked[key]

        # ── Layer 2: Per user ──────────────────────────────────
        user_key = f"user:{user_id}"
        w        = self._windows[user_key]
        w.add(now)

        for window, limit_val in [
            (60,   USER_LIMITS.requests_per_minute),
            (3600, USER_LIMITS.requests_per_hour),
            (86400, USER_LIMITS.requests_per_day),
        ]:
            count = w.count_in_window(window, now)
            if count > limit_val + USER_LIMITS.burst_allowance:
                self._blocked[user_key] = now + USER_LIMITS.cooldown_seconds
                self._audit("blocked", "user", user_key, count, bot_id)
                return CheckResult(
                    status        = LimitStatus.BLOCKED,
                    layer         = "user",
                    key           = user_key,
                    limit         = USER_LIMITS,
                    current_rpm   = self._windows[user_key].count_in_window(60, now),
                    retry_after_s = USER_LIMITS.cooldown_seconds,
                    message       = "Terlalu banyak pesan. Mohon tunggu sebentar.",
                )
            elif count > limit_val:
                self._audit("throttled", "user", user_key, count, bot_id)
                return CheckResult(
                    status      = LimitStatus.THROTTLED,
                    layer       = "user",
                    key         = user_key,
                    limit       = USER_LIMITS,
                    current_rpm = count,
                    message     = "Request dilambatkan sementara.",
                )

        # ── Layer 3: Per org / plan ────────────────────────────
        plan_limit = PLAN_LIMITS.get(plan, PLAN_LIMITS["starter"])
        org_key    = f"org:{org_id}"
        ow         = self._windows[org_key]
        ow.add(now)

        for window, attr in [
            (60,    "requests_per_minute"),
            (3600,  "requests_per_hour"),
            (86400, "requests_per_day"),
        ]:
            count = ow.count_in_window(window, now)
            limit_val = getattr(plan_limit, attr)
            if count > limit_val + plan_limit.burst_allowance:
                self._blocked[org_key] = now + plan_limit.cooldown_seconds
                self._audit("blocked", "org", org_key, count, bot_id)
                return CheckResult(
                    status        = LimitStatus.BLOCKED,
                    layer         = "org",
                    key           = org_key,
                    limit         = plan_limit,
                    current_rpm   = ow.count_in_window(60, now),
                    retry_after_s = plan_limit.cooldown_seconds,
                    message       = f"Quota plan {plan} tercapai. Upgrade untuk kapasitas lebih.",
                )
            elif count > limit_val:
                return CheckResult(
                    status      = LimitStatus.THROTTLED,
                    layer       = "org",
                    key         = org_key,
                    limit       = plan_limit,
                    current_rpm = count,
                    message     = f"Mendekati batas quota plan {plan}.",
                )

        # ── Layer 4: Per bot ───────────────────────────────────
        if bot_id:
            bot_key = f"bot:{bot_id}"
            bw      = self._windows[bot_key]
            bw.add(now)
            bot_rpm = bw.count_in_window(60, now)

            # Bot tidak boleh lebih dari 2x limit plan per menit
            bot_rpm_limit = plan_limit.requests_per_minute * 2
            if bot_rpm > bot_rpm_limit:
                return CheckResult(
                    status        = LimitStatus.THROTTLED,
                    layer         = "bot",
                    key           = bot_key,
                    limit         = plan_limit,
                    current_rpm   = bot_rpm,
                    retry_after_s = 10,
                    message       = "Bot sedang menerima terlalu banyak request.",
                )

        # ── Layer 5: Per agent (Token Bucket) ─────────────────
        if agent and agent in AGENT_LIMITS:
            agent_limit  = AGENT_LIMITS[agent]
            agent_key    = f"agent:{agent}"
            bucket       = self._get_bucket(agent_key, agent_limit)
            token_ok     = await bucket.consume()
            if not token_ok:
                wait = bucket.wait_time()
                return CheckResult(
                    status        = LimitStatus.THROTTLED,
                    layer         = "agent",
                    key           = agent_key,
                    limit         = agent_limit,
                    retry_after_s = int(wait) + 1,
                    message       = f"Agent '{agent}' sedang sibuk. Coba lagi dalam {int(wait)+1}s.",
                )

        # ── Layer 6: Global ────────────────────────────────────
        gw = self._windows["global"]
        gw.add(now)
        global_rpm = gw.count_in_window(60, now)
        if global_rpm > GLOBAL_LIMIT.requests_per_minute:
            return CheckResult(
                status        = LimitStatus.THROTTLED,
                layer         = "global",
                key           = "global",
                limit         = GLOBAL_LIMIT,
                current_rpm   = global_rpm,
                retry_after_s = 5,
                message       = "Sistem sedang ramai. Request diperlambat sementara.",
            )

        # ── Semua layer OK ─────────────────────────────────────
        return CheckResult(
            status      = LimitStatus.ALLOWED,
            layer       = "none",
            key         = "",
            limit       = None,
            current_rpm = ow.count_in_window(60, now),
        )

    async def wait_if_throttled(self, result: CheckResult) -> bool:
        """
        Jika THROTTLED, tunggu sebentar lalu izinkan.
        Jika BLOCKED, return False langsung.
        """
        if result.status == LimitStatus.ALLOWED:
            return True
        if result.status == LimitStatus.BLOCKED:
            return False
        # THROTTLED — tunggu sedikit
        wait = min(result.retry_after_s, 5)
        await asyncio.sleep(wait)
        return True

    def _audit(self, action: str, layer: str, key: str, count: int, bot_id: str):
        self._log.append({
            "action":  action,
            "layer":   layer,
            "key":     key,
            "count":   count,
            "bot_id":  bot_id,
            "ts":      datetime.now(timezone.utc).isoformat(),
        })
        if len(self._log) > 2000:
            self._log = self._log[-2000:]

    def stats(self) -> dict:
        blocked_count  = sum(1 for l in self._log if l["action"] == "blocked")
        throttled_count = sum(1 for l in self._log if l["action"] == "throttled")
        active_blocks  = len(self._blocked)

        by_layer: dict[str, int] = {}
        for l in self._log:
            if l["action"] in ("blocked", "throttled"):
                by_layer[l["layer"]] = by_layer.get(l["layer"], 0) + 1

        return {
            "total_blocked":    blocked_count,
            "total_throttled":  throttled_count,
            "active_blocks":    active_blocks,
            "blocked_keys":     list(self._blocked.keys()),
            "by_layer":         by_layer,
            "global_rpm":       self._windows["global"].count_in_window(60),
        }

    def recent_events(self, limit: int = 30) -> list[dict]:
        return [l for l in self._log[-limit:] if l["action"] in ("blocked", "throttled")]

    def reset_key(self, key: str):
        """Manual unblock — untuk admin."""
        self._blocked.pop(key, None)
        self._windows.pop(key, None)
        self._buckets.pop(key, None)


# ─── MIDDLEWARE HELPER ─────────────────────────────────────────

class RateLimitMiddleware:
    """
    Helper untuk integrasi ke FastAPI.

    Cara pakai di agent_api.py:
      from rate_limiter import RateLimitMiddleware
      rl = RateLimitMiddleware()

      @app.post("/process")
      async def process_message(req: ProcessRequest):
          check = await rl.check_request(
              user_id = req.metadata.get("userId", "anon"),
              bot_id  = req.bot_id,
              org_id  = req.org_id,
              plan    = req.metadata.get("plan", "starter"),
          )
          if not check.allowed:
              raise HTTPException(429, check.message)
          ...
    """

    def __init__(self):
        self.limiter = RateLimiter()

    @dataclass
    class CheckOutput:
        allowed:       bool
        status:        str
        message:       str
        retry_after_s: int
        current_rpm:   int

    async def check_request(
        self,
        user_id: str = "anonymous",
        bot_id:  str = "",
        org_id:  str = "",
        plan:    str = "starter",
        agent:   str = "",
    ) -> "RateLimitMiddleware.CheckOutput":
        result = await self.limiter.check(
            user_id=user_id, bot_id=bot_id,
            org_id=org_id, plan=plan, agent=agent,
        )
        allowed = result.status == LimitStatus.ALLOWED
        if result.status == LimitStatus.THROTTLED:
            # Throttled: tunggu dulu, lalu izinkan
            allowed = await self.limiter.wait_if_throttled(result)

        return self.CheckOutput(
            allowed       = allowed,
            status        = result.status.value,
            message       = result.message,
            retry_after_s = result.retry_after_s,
            current_rpm   = result.current_rpm,
        )

    def stats(self) -> dict:
        return self.limiter.stats()


# ─── SINGLETON ────────────────────────────────────────────────

_global_limiter: RateLimitMiddleware | None = None

def get_rate_limiter() -> RateLimitMiddleware:
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = RateLimitMiddleware()
    return _global_limiter
