"""
recovery_manager.py — Recovery Manager (AI Agent Platform).

Menangani pemulihan otomatis dari kegagalan dalam pipeline ActionExecutor:
  - Retry dengan backoff eksponensial
  - Fallback ke tool alternatif
  - Deteksi error pattern (network error, permission error, timeout, dll)
  - Circuit breaker untuk tool yang berulang kali gagal
  - Log semua recovery attempt

Dipanggil oleh ActionExecutor — bukan oleh agent atau user langsung.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BASE_DELAY = 1.0   # detik
_DEFAULT_MAX_DELAY = 30.0
_CIRCUIT_BREAKER_THRESHOLD = 5  # kegagalan berturut-turut


@dataclass
class RecoveryContext:
    action_type: str
    error: str
    attempt: int
    metadata: dict = field(default_factory=dict)


@dataclass
class CircuitState:
    failures: int = 0
    last_failure: float = 0.0
    open: bool = False
    reset_after: float = 60.0  # detik sebelum circuit di-reset

    def record_failure(self) -> None:
        self.failures += 1
        self.last_failure = time.time()
        if self.failures >= _CIRCUIT_BREAKER_THRESHOLD:
            self.open = True
            logger.warning("circuit breaker TERBUKA setelah %d kegagalan", self.failures)

    def record_success(self) -> None:
        self.failures = 0
        self.open = False

    def is_open(self) -> bool:
        if not self.open:
            return False
        if time.time() - self.last_failure > self.reset_after:
            self.open = False
            self.failures = 0
            logger.info("circuit breaker DIRESET (timeout tercapai)")
            return False
        return True


def _classify_error(error: str) -> str:
    """Klasifikasi error untuk menentukan strategi recovery."""
    err_lower = (error or "").lower()
    if any(k in err_lower for k in ["timeout", "timed out", "time out"]):
        return "timeout"
    if any(k in err_lower for k in ["connection", "network", "unreachable", "refused"]):
        return "network"
    if any(k in err_lower for k in ["permission", "access denied", "forbidden", "unauthorized"]):
        return "permission"
    if any(k in err_lower for k in ["not found", "404", "tidak ditemukan"]):
        return "not_found"
    if any(k in err_lower for k in ["rate limit", "429", "too many requests"]):
        return "rate_limit"
    if any(k in err_lower for k in ["syntax", "parse", "json", "invalid"]):
        return "parse_error"
    return "unknown"


def _should_retry(error_class: str, attempt: int, max_retries: int) -> bool:
    """Apakah error layak di-retry?"""
    if attempt >= max_retries:
        return False
    # Jangan retry untuk permission error atau parse error
    no_retry_classes = {"permission", "not_found", "parse_error"}
    return error_class not in no_retry_classes


def _backoff_delay(attempt: int, *, base: float = _DEFAULT_BASE_DELAY, max_delay: float = _DEFAULT_MAX_DELAY) -> float:
    """Eksponensial backoff dengan jitter."""
    import random
    delay = min(base * (2 ** attempt) + random.uniform(0, 0.5), max_delay)
    return delay


class RecoveryManager:
    """
    Manager recovery untuk pipeline agent.

    Usage:
        rm = RecoveryManager()
        result = await rm.with_retry(my_async_func, arg1, arg2, action_type="browser_read")
    """

    def __init__(self, max_retries: int = _DEFAULT_MAX_RETRIES):
        self._max_retries = max_retries
        self._circuits: dict[str, CircuitState] = {}
        self._recovery_log: list[dict] = []

    def _get_circuit(self, action_type: str) -> CircuitState:
        if action_type not in self._circuits:
            self._circuits[action_type] = CircuitState()
        return self._circuits[action_type]

    async def with_retry(
        self,
        func: Callable[..., Awaitable[dict]],
        *args: Any,
        action_type: str = "unknown",
        **kwargs: Any,
    ) -> dict:
        """
        Jalankan func dengan auto-retry dan circuit breaker.

        func harus return dict dengan key "success" (bool) dan opsional "error" (str).
        """
        circuit = self._get_circuit(action_type)

        if circuit.is_open():
            return {
                "success": False,
                "error": f"Circuit breaker terbuka untuk '{action_type}' — terlalu banyak kegagalan berturut-turut. Coba lagi dalam {int(circuit.reset_after)}s.",
                "circuit_open": True,
            }

        last_error = ""
        for attempt in range(self._max_retries + 1):
            try:
                result = await func(*args, **kwargs)
            except Exception as exc:
                result = {"success": False, "error": str(exc)}

            if result.get("success"):
                circuit.record_success()
                if attempt > 0:
                    logger.info("recovery: berhasil pada attempt %d untuk %s", attempt + 1, action_type)
                return result

            last_error = result.get("error", "unknown error")
            error_class = _classify_error(last_error)
            circuit.record_failure()

            self._recovery_log.append({
                "action_type": action_type,
                "attempt": attempt + 1,
                "error": last_error,
                "error_class": error_class,
            })

            if not _should_retry(error_class, attempt, self._max_retries):
                logger.debug(
                    "recovery: tidak retry untuk error_class=%s attempt=%d/%d",
                    error_class, attempt + 1, self._max_retries,
                )
                break

            if attempt < self._max_retries:
                delay = _backoff_delay(attempt)
                logger.debug("recovery: retry %d/%d setelah %.1fs (error: %s)", attempt + 1, self._max_retries, delay, error_class)
                await asyncio.sleep(delay)

        return {
            "success": False,
            "error": last_error,
            "attempts": min(attempt + 1, self._max_retries + 1),
            "recovered": False,
        }

    async def with_fallback(
        self,
        primary: Callable[..., Awaitable[dict]],
        fallback: Callable[..., Awaitable[dict]],
        *args: Any,
        action_type: str = "unknown",
        **kwargs: Any,
    ) -> dict:
        """
        Coba primary dulu, jika gagal jalankan fallback.
        """
        result = await self.with_retry(primary, *args, action_type=action_type, **kwargs)
        if not result.get("success"):
            logger.info("recovery: primary gagal, mencoba fallback untuk %s", action_type)
            fallback_result = await self.with_retry(fallback, *args, action_type=f"{action_type}_fallback", **kwargs)
            if fallback_result.get("success"):
                fallback_result["used_fallback"] = True
            return fallback_result
        return result

    def get_recovery_log(self) -> list[dict]:
        return list(self._recovery_log[-50:])

    def get_circuit_status(self) -> dict:
        return {
            name: {
                "failures": s.failures,
                "open": s.is_open(),
                "last_failure": s.last_failure,
            }
            for name, s in self._circuits.items()
        }

    def reset_circuit(self, action_type: str) -> None:
        if action_type in self._circuits:
            self._circuits[action_type] = CircuitState()
